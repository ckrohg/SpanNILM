"""Supervised ML classifier trained on dedicated circuit sessions.

Extracts ON sessions from all 10 dedicated circuits, builds feature vectors,
trains a Random Forest classifier, and predicts device types for unknown
devices on shared circuits.  Includes Bayesian prior penalization so the
model doesn't predict device types that are already well-represented on
dedicated circuits.
"""

import io
import logging
import os
import pickle
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

from span_nilm.collector.sources.tempiq_source import TempIQSource
from span_nilm.profiler.shape_detector import ShapeDetector

logger = logging.getLogger("span_nilm.models.dedicated_learner")

MODEL_NAME = "dedicated_rf_v1"
UNKNOWN_CLASS = "unknown"


class DedicatedLearner:
    """Random Forest classifier trained from dedicated-circuit sessions."""

    def __init__(
        self,
        source: TempIQSource | None = None,
        spannilm_db_url: str | None = None,
        data_days: int = 90,
    ):
        self.source = source or TempIQSource()
        self.db_url = spannilm_db_url or os.environ["SPANNILM_DATABASE_URL"]
        self.data_days = data_days

        # Populated after train() or load()
        self.clf: Optional[RandomForestClassifier] = None
        self.scaler: Optional[StandardScaler] = None
        self.class_labels: list[str] = []
        self.device_type_counts: dict[str, int] = {}  # for Bayesian prior

    # ------------------------------------------------------------------
    # Feature extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _session_features(session, hour: float) -> dict:
        """Extract ML features from a single ON session.

        Returns a dict with the feature names and values used for training
        and prediction.
        """
        power = session.power_curve
        mean_w = float(np.mean(power))
        peak_w = float(np.max(power))
        std_w = float(np.std(power))
        duration_min = session.duration_min
        energy_wh = mean_w * duration_min / 60.0

        # Phase detection (simplified)
        if len(power) >= 5:
            phase_threshold = max(30, mean_w * 0.15)
            phases: list[list[float]] = [[float(power[0])]]
            for i in range(1, len(power)):
                cur_mean = float(np.mean(phases[-1]))
                if abs(float(power[i]) - cur_mean) > phase_threshold:
                    if len(phases[-1]) >= 2:
                        phases.append([float(power[i])])
                    else:
                        phases[-1].append(float(power[i]))
                else:
                    phases[-1].append(float(power[i]))
            unique_phases: list[float] = []
            for p in phases:
                pm = float(np.mean(p))
                if pm > 8 and not any(abs(pm - up) < phase_threshold for up in unique_phases):
                    unique_phases.append(pm)
            num_phases = max(1, len(unique_phases))
        else:
            num_phases = 1

        # Startup surge
        first_seg = power[: max(1, len(power) // 5)]
        has_surge = 1.0 if float(np.mean(first_seg)) > mean_w * 1.2 else 0.0

        return {
            "avg_power": mean_w,
            "peak_power": peak_w,
            "duration_min": duration_min,
            "log_energy_wh": float(np.log1p(energy_wh)),
            "power_stability": std_w / max(mean_w, 1.0),
            "hour_sin": float(np.sin(2 * np.pi * hour / 24)),
            "hour_cos": float(np.cos(2 * np.pi * hour / 24)),
            "num_phases": float(num_phases),
            "has_surge": has_surge,
        }

    @staticmethod
    def features_from_template(template: dict) -> dict:
        """Build the same feature vector from a DeviceTemplate dict (or shape_device dict).

        Used at prediction time when we don't have a raw Session object.
        """
        avg_power = template.get("avg_power_w", 0)
        peak_power = template.get("peak_power_w", avg_power)
        duration_min = template.get("avg_duration_min", 0)
        energy_wh = avg_power * duration_min / 60.0
        peak_hours = template.get("peak_hours", [12])
        hour = peak_hours[0] if peak_hours else 12
        num_phases = template.get("num_phases", 1)
        has_surge = 1.0 if template.get("has_startup_surge", False) else 0.0
        # power_stability: approximate from duty_cycle or default
        stability = template.get("power_stability", 0.15)
        if "std_power_w" in template and avg_power > 0:
            stability = template["std_power_w"] / avg_power

        return {
            "avg_power": float(avg_power),
            "peak_power": float(peak_power),
            "duration_min": float(duration_min),
            "log_energy_wh": float(np.log1p(energy_wh)),
            "power_stability": float(stability),
            "hour_sin": float(np.sin(2 * np.pi * hour / 24)),
            "hour_cos": float(np.cos(2 * np.pi * hour / 24)),
            "num_phases": float(num_phases),
            "has_surge": has_surge,
        }

    FEATURE_NAMES = [
        "avg_power", "peak_power", "duration_min", "log_energy_wh",
        "power_stability", "hour_sin", "hour_cos", "num_phases", "has_surge",
    ]

    def _features_to_array(self, feat_dict: dict) -> np.ndarray:
        return np.array([feat_dict[k] for k in self.FEATURE_NAMES])

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self) -> dict:
        """Train the Random Forest from dedicated circuit sessions.

        Returns a summary dict with class counts and accuracy info.
        """
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=self.data_days)

        # Load circuit configs
        configs = self._load_circuit_configs()
        dedicated = {
            cid: cfg for cid, cfg in configs.items()
            if cfg.get("is_dedicated") and cfg.get("dedicated_device_type")
        }

        if not dedicated:
            logger.warning("No dedicated circuits found — cannot train")
            return {"error": "no_dedicated_circuits"}

        # Fetch aggregated power data
        agg_df = self.source.get_aggregated_power(start, now)
        if agg_df.empty:
            return {"error": "no_data"}

        shape_det = ShapeDetector()
        feature_rows: list[np.ndarray] = []
        labels: list[str] = []
        device_type_counts: dict[str, int] = {}

        for cid, cfg in dedicated.items():
            device_type = cfg["dedicated_device_type"]
            device_type_counts[device_type] = device_type_counts.get(device_type, 0) + 1

            circuit_data = agg_df[agg_df["circuit_id"] == cid].sort_values("timestamp").reset_index(drop=True)
            if circuit_data.empty:
                continue

            sessions = shape_det._extract_sessions(circuit_data)
            logger.info(
                "Dedicated circuit %s (%s): %d sessions",
                cfg.get("name", cid), device_type, len(sessions),
            )

            for s in sessions:
                hour = s.start_time.hour + s.start_time.minute / 60.0
                feat = self._session_features(s, hour)
                feature_rows.append(self._features_to_array(feat))
                labels.append(device_type)

        if len(feature_rows) < 10:
            logger.warning("Only %d training sessions — too few", len(feature_rows))
            return {"error": "insufficient_sessions", "count": len(feature_rows)}

        self.device_type_counts = device_type_counts

        # Generate synthetic "unknown" class examples
        X_real = np.array(feature_rows)
        n_unknown = max(len(feature_rows) // 3, 20)
        rng = np.random.default_rng(42)
        X_unknown = []
        for _ in range(n_unknown):
            # Pick a random real sample and perturb it
            base = X_real[rng.integers(len(X_real))].copy()
            # Shift power by +/-50%
            power_factor = rng.uniform(0.5, 1.5)
            base[0] *= power_factor  # avg_power
            base[1] *= power_factor  # peak_power
            # Randomize time-of-day
            rand_hour = rng.uniform(0, 24)
            base[5] = np.sin(2 * np.pi * rand_hour / 24)
            base[6] = np.cos(2 * np.pi * rand_hour / 24)
            # Shift duration by +/-30%
            base[2] *= rng.uniform(0.7, 1.3)
            # Recompute log_energy
            base[3] = np.log1p(base[0] * base[2] / 60.0)
            X_unknown.append(base)

        X_all = np.vstack([X_real, np.array(X_unknown)])
        y_all = labels + [UNKNOWN_CLASS] * n_unknown

        # Scale features
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X_all)

        # Train Random Forest
        self.clf = RandomForestClassifier(
            n_estimators=100,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        self.clf.fit(X_scaled, y_all)
        self.class_labels = list(self.clf.classes_)

        # Compute training accuracy
        train_acc = float(self.clf.score(X_scaled, y_all))

        summary = {
            "classes": self.class_labels,
            "samples_per_class": {
                lbl: y_all.count(lbl) for lbl in set(y_all)
            },
            "total_samples": len(y_all),
            "train_accuracy": round(train_acc, 3),
            "device_type_counts": device_type_counts,
        }
        logger.info("Trained DedicatedLearner: %s", summary)
        return summary

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, features: dict) -> list[tuple[str, float]]:
        """Predict device type from feature dict.

        Returns [(device_type, probability), ...] sorted by probability desc.
        Applies Bayesian prior to penalize over-represented device types.
        """
        if self.clf is None or self.scaler is None:
            self._load_model()
        if self.clf is None:
            return [(UNKNOWN_CLASS, 1.0)]

        feat_arr = self._features_to_array(features).reshape(1, -1)
        feat_scaled = self.scaler.transform(feat_arr)

        proba = self.clf.predict_proba(feat_scaled)[0]
        raw_predictions = list(zip(self.class_labels, proba))

        # Apply Bayesian prior
        adjusted = []
        for device_type, prob in raw_predictions:
            prior = self._bayesian_prior(device_type)
            adjusted_prob = prob * prior
            adjusted.append((device_type, adjusted_prob))

        # Renormalize
        total = sum(p for _, p in adjusted)
        if total > 0:
            adjusted = [(dt, p / total) for dt, p in adjusted]

        adjusted.sort(key=lambda x: x[1], reverse=True)
        return adjusted

    def _bayesian_prior(self, device_type: str) -> float:
        """Compute prior probability for finding another instance of device_type.

        More dedicated circuits of this type already exist -> lower prior
        for finding it again on a shared circuit. Aggressive suppression
        to prevent the classifier from labeling everything as Heat Pump
        just because heat pump sessions dominate the training data.
        """
        if device_type == UNKNOWN_CLASS:
            return 1.0  # Always welcome unknown

        count = self.device_type_counts.get(device_type, 0)
        if count == 0:
            return 0.5  # Device type not seen — moderate prior
        elif count == 1:
            return 0.2  # One already — unlikely to find another
        elif count == 2:
            return 0.05  # Two already — very unlikely
        else:
            return 0.01  # 3+ already (e.g., 5 heat pumps) — effectively zero

    # ------------------------------------------------------------------
    # Model persistence
    # ------------------------------------------------------------------

    def save_model(self) -> None:
        """Serialize model + scaler + metadata to model_artifacts table."""
        if self.clf is None or self.scaler is None:
            raise ValueError("No trained model to save")

        self._ensure_model_artifacts_table()

        payload = {
            "clf": self.clf,
            "scaler": self.scaler,
            "class_labels": self.class_labels,
            "device_type_counts": self.device_type_counts,
        }
        buf = io.BytesIO()
        pickle.dump(payload, buf)
        model_bytes = buf.getvalue()

        metadata = {
            "n_estimators": self.clf.n_estimators,
            "n_classes": len(self.class_labels),
            "classes": self.class_labels,
            "device_type_counts": self.device_type_counts,
        }

        conn = psycopg2.connect(self.db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO model_artifacts (model_name, model_type, model_data, metadata)
                    VALUES (%s, %s, %s, %s::jsonb)
                    ON CONFLICT (model_name)
                    DO UPDATE SET model_data = EXCLUDED.model_data,
                                  metadata = EXCLUDED.metadata,
                                  created_at = now()
                    """,
                    (MODEL_NAME, "random_forest", psycopg2.Binary(model_bytes),
                     __import__("json").dumps(metadata)),
                )
                conn.commit()
            logger.info("Saved model '%s' (%d bytes)", MODEL_NAME, len(model_bytes))
        finally:
            conn.close()

    def _load_model(self) -> bool:
        """Load model from model_artifacts table.  Returns True if loaded."""
        try:
            conn = psycopg2.connect(self.db_url)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT model_data, metadata FROM model_artifacts WHERE model_name = %s",
                        (MODEL_NAME,),
                    )
                    row = cur.fetchone()
                    if not row:
                        logger.info("No saved model '%s' found", MODEL_NAME)
                        return False

                    model_bytes = bytes(row[0])
                    payload = pickle.loads(model_bytes)

                    self.clf = payload["clf"]
                    self.scaler = payload["scaler"]
                    self.class_labels = payload["class_labels"]
                    self.device_type_counts = payload.get("device_type_counts", {})

                    logger.info(
                        "Loaded model '%s' with %d classes",
                        MODEL_NAME, len(self.class_labels),
                    )
                    return True
            finally:
                conn.close()
        except Exception as e:
            logger.warning("Failed to load model: %s", e)
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_circuit_configs(self) -> dict[str, dict]:
        conn = psycopg2.connect(self.db_url)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM circuits")
                return {row["tempiq_equipment_id"]: dict(row) for row in cur.fetchall()}
        finally:
            conn.close()

    def _ensure_model_artifacts_table(self) -> None:
        conn = psycopg2.connect(self.db_url)
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS model_artifacts (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        model_name VARCHAR NOT NULL UNIQUE,
                        model_type VARCHAR NOT NULL,
                        model_data BYTEA,
                        metadata JSONB DEFAULT '{}',
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                conn.commit()
        finally:
            conn.close()
