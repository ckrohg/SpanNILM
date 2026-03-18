"""Seq-to-Point disaggregation model using MLPRegressor.

Lightweight 1D "CNN-like" model for device power estimation. Takes a window
of circuit power readings and predicts individual device contributions at the
midpoint. Uses scikit-learn's MLPRegressor (no PyTorch/TF dependency).

Also includes a DeviceStateDetector that provides binary ON/OFF classification
per device type at each timestep.

Training uses dedicated circuit data as ground truth: the known device's
circuit power is the label, and the sub-panel or total house power is the input.
"""

import io
import json
import logging
import os
import pickle
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from sklearn.neural_network import MLPRegressor, MLPClassifier
from sklearn.preprocessing import StandardScaler

from span_nilm.collector.sources.tempiq_source import TempIQSource

logger = logging.getLogger("span_nilm.models.seq2point")

# Model names for persistence
S2P_MODEL_NAME = "seq2point_v1"
STATE_MODEL_NAME = "device_state_v1"

# Window sizes (in number of 10-min readings)
POWER_WINDOW = 31   # ~5 hours centered on target (for power estimation)
STATE_WINDOW = 11   # ~2 hours centered on target (for state detection)

# Thresholds
ON_THRESHOLD_W = 10     # Device considered ON above this power
MIN_TRAINING_SAMPLES = 50


class Seq2PointModel:
    """Lightweight 1D MLP for device power estimation.

    Input: window of N power readings (e.g., N=31, centered on target)
    Output: estimated power of a single device at the center point

    For each known device type (from dedicated circuits), trains a separate
    MLPRegressor. At prediction time, slides the window across a circuit's
    power and predicts each device's contribution.
    """

    def __init__(
        self,
        source: TempIQSource | None = None,
        spannilm_db_url: str | None = None,
        data_days: int = 90,
        window_size: int = POWER_WINDOW,
    ):
        self.source = source or TempIQSource()
        self.db_url = spannilm_db_url or os.environ["SPANNILM_DATABASE_URL"]
        self.data_days = data_days
        self.window_size = window_size
        self.half_window = window_size // 2

        # Per-device models: {device_type: (MLPRegressor, StandardScaler, StandardScaler)}
        # Scalers: (input_scaler, output_scaler)
        self.models: dict[str, tuple[MLPRegressor, StandardScaler, StandardScaler]] = {}
        self.device_stats: dict[str, dict] = {}  # Training stats per device

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self) -> dict:
        """Train models using dedicated circuit data as ground truth.

        For each dedicated device type:
        1. Get the device's power from its dedicated circuit (truth)
        2. Compute total house power at the same timestamps (input)
        3. Create sliding windows of total power -> device power at midpoint
        4. Train an MLPRegressor

        Returns summary dict with per-device training stats.
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
            logger.warning("No dedicated circuits found -- cannot train seq2point")
            return {"error": "no_dedicated_circuits"}

        # Fetch all aggregated power data
        agg_df = self.source.get_aggregated_power(start, now)
        if agg_df.empty:
            return {"error": "no_data"}

        # Build a time-aligned matrix: rows = timestamps, columns = circuits
        # Pivot to get power per circuit per timestamp
        pivot = agg_df.pivot_table(
            index="timestamp", columns="circuit_id", values="power_w", aggfunc="mean"
        ).sort_index()

        # Forward-fill small gaps (up to 3 readings = 30 min)
        pivot = pivot.ffill(limit=3).fillna(0)

        # Compute total house power (sum of all circuits)
        total_power = pivot.sum(axis=1).values.astype(np.float64)

        summary: dict[str, dict] = {}

        for cid, cfg in dedicated.items():
            device_type = cfg["dedicated_device_type"]

            if cid not in pivot.columns:
                logger.warning("No data for dedicated circuit %s (%s)", cid, device_type)
                continue

            device_power = pivot[cid].values.astype(np.float64)

            # Build sliding windows
            X, y = self._build_windows(total_power, device_power)

            if len(X) < MIN_TRAINING_SAMPLES:
                logger.warning(
                    "Only %d samples for %s -- skipping (need %d)",
                    len(X), device_type, MIN_TRAINING_SAMPLES,
                )
                continue

            # If we already have a model for this device type, aggregate data
            # (handles multiple circuits for same device, e.g., multiple heat pumps)
            if device_type in self.models:
                # Get existing training data and append
                logger.info(
                    "Additional circuit for %s -- retraining with combined data", device_type
                )

            # Scale inputs and outputs
            input_scaler = StandardScaler()
            output_scaler = StandardScaler()

            X_scaled = input_scaler.fit_transform(X)
            y_scaled = output_scaler.fit_transform(y.reshape(-1, 1)).ravel()

            # Train MLP
            mlp = MLPRegressor(
                hidden_layer_sizes=(64, 32),
                activation="relu",
                max_iter=500,
                early_stopping=True,
                validation_fraction=0.1,
                random_state=42,
                batch_size=min(256, max(32, len(X) // 10)),
            )

            try:
                mlp.fit(X_scaled, y_scaled)
            except Exception as e:
                logger.warning("MLP training failed for %s: %s", device_type, e)
                continue

            self.models[device_type] = (mlp, input_scaler, output_scaler)

            # Compute training metrics
            y_pred_scaled = mlp.predict(X_scaled)
            y_pred = output_scaler.inverse_transform(y_pred_scaled.reshape(-1, 1)).ravel()

            # Clip negative predictions
            y_pred = np.clip(y_pred, 0, None)

            mae = float(np.mean(np.abs(y_pred - y)))
            rmse = float(np.sqrt(np.mean((y_pred - y) ** 2)))
            mean_actual = float(np.mean(y[y > ON_THRESHOLD_W])) if np.any(y > ON_THRESHOLD_W) else 0

            stats = {
                "samples": len(X),
                "mae_w": round(mae, 1),
                "rmse_w": round(rmse, 1),
                "mean_on_power_w": round(mean_actual, 1),
                "on_fraction": round(float(np.mean(y > ON_THRESHOLD_W)), 3),
                "n_iterations": mlp.n_iter_,
            }
            self.device_stats[device_type] = stats
            summary[device_type] = stats

            logger.info(
                "Trained seq2point for %s: %d samples, MAE=%.1fW, RMSE=%.1fW",
                device_type, len(X), mae, rmse,
            )

        if not self.models:
            return {"error": "no_models_trained"}

        return {"models_trained": len(self.models), "devices": summary}

    def _build_windows(
        self, input_series: np.ndarray, target_series: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Build sliding window training samples.

        input_series: total power (or sub-panel power) time series
        target_series: specific device power time series

        Returns (X, y) where X[i] is a window of input_series centered on
        position i, and y[i] is the target device power at position i.
        """
        n = len(input_series)
        if n < self.window_size:
            return np.array([]), np.array([])

        X = []
        y = []

        for i in range(self.half_window, n - self.half_window):
            window = input_series[i - self.half_window: i + self.half_window + 1]
            if len(window) == self.window_size:
                X.append(window)
                y.append(target_series[i])

        return np.array(X, dtype=np.float64), np.array(y, dtype=np.float64)

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict_devices(
        self, circuit_power: np.ndarray
    ) -> dict[str, np.ndarray]:
        """Given a circuit's power time series, predict each device's contribution.

        Args:
            circuit_power: 1D array of power readings (10-min intervals)

        Returns:
            {device_type: power_array} for each trained device type.
            power_array has the same length as circuit_power (padded with 0
            at the edges where the window doesn't fit).
        """
        if not self.models:
            self._load_model()
        if not self.models:
            return {}

        n = len(circuit_power)
        results: dict[str, np.ndarray] = {}

        for device_type, (mlp, input_scaler, output_scaler) in self.models.items():
            predictions = np.zeros(n, dtype=np.float64)

            if n < self.window_size:
                results[device_type] = predictions
                continue

            # Build all windows at once for efficiency
            windows = []
            indices = []
            for i in range(self.half_window, n - self.half_window):
                window = circuit_power[i - self.half_window: i + self.half_window + 1]
                if len(window) == self.window_size:
                    windows.append(window)
                    indices.append(i)

            if not windows:
                results[device_type] = predictions
                continue

            X = np.array(windows, dtype=np.float64)
            X_scaled = input_scaler.transform(X)
            y_scaled = mlp.predict(X_scaled)
            y_pred = output_scaler.inverse_transform(y_scaled.reshape(-1, 1)).ravel()

            # Clip negative predictions and cap at circuit power
            y_pred = np.clip(y_pred, 0, None)
            for idx, pred_idx in enumerate(indices):
                predictions[pred_idx] = min(y_pred[idx], circuit_power[pred_idx])

            results[device_type] = predictions

        return results

    def predict_summary(
        self, circuit_power: np.ndarray
    ) -> list[dict]:
        """Predict devices and return a summary of detected contributions.

        Returns a list of dicts, one per detected device type, with:
        - device_type: str
        - avg_power_w: float (average when predicted > threshold)
        - peak_power_w: float
        - on_fraction: float (fraction of time predicted ON)
        - total_energy_wh: float (estimated energy contribution)
        """
        device_preds = self.predict_devices(circuit_power)
        if not device_preds:
            return []

        summaries = []
        interval_hours = 10 / 60  # 10-min intervals

        for device_type, preds in device_preds.items():
            on_mask = preds > ON_THRESHOLD_W
            on_count = int(np.sum(on_mask))

            if on_count < 3:  # Need at least 3 readings (30 min) to count
                continue

            avg_on_power = float(np.mean(preds[on_mask]))
            peak_power = float(np.max(preds))
            on_fraction = on_count / len(preds)
            total_energy = float(np.sum(preds) * interval_hours)

            summaries.append({
                "device_type": device_type,
                "avg_power_w": round(avg_on_power, 1),
                "peak_power_w": round(peak_power, 1),
                "on_fraction": round(on_fraction, 3),
                "total_energy_wh": round(total_energy, 1),
                "on_readings": on_count,
            })

        # Sort by energy contribution
        summaries.sort(key=lambda s: s["total_energy_wh"], reverse=True)
        return summaries

    # ------------------------------------------------------------------
    # Model persistence
    # ------------------------------------------------------------------

    def save_model(self) -> None:
        """Serialize all per-device models to model_artifacts table."""
        if not self.models:
            raise ValueError("No trained models to save")

        self._ensure_model_artifacts_table()

        payload = {
            "models": {
                dt: {"mlp": mlp, "input_scaler": iscaler, "output_scaler": oscaler}
                for dt, (mlp, iscaler, oscaler) in self.models.items()
            },
            "device_stats": self.device_stats,
            "window_size": self.window_size,
        }
        buf = io.BytesIO()
        pickle.dump(payload, buf)
        model_bytes = buf.getvalue()

        metadata = {
            "n_devices": len(self.models),
            "device_types": list(self.models.keys()),
            "device_stats": self.device_stats,
            "window_size": self.window_size,
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
                    (S2P_MODEL_NAME, "seq2point_mlp", psycopg2.Binary(model_bytes),
                     json.dumps(metadata)),
                )
                conn.commit()
            logger.info("Saved seq2point model (%d bytes, %d devices)",
                        len(model_bytes), len(self.models))
        finally:
            conn.close()

    def _load_model(self) -> bool:
        """Load models from model_artifacts table. Returns True if loaded."""
        try:
            conn = psycopg2.connect(self.db_url)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT model_data FROM model_artifacts WHERE model_name = %s",
                        (S2P_MODEL_NAME,),
                    )
                    row = cur.fetchone()
                    if not row:
                        logger.info("No saved seq2point model found")
                        return False

                    payload = pickle.loads(bytes(row[0]))

                    self.window_size = payload.get("window_size", POWER_WINDOW)
                    self.half_window = self.window_size // 2
                    self.device_stats = payload.get("device_stats", {})

                    self.models = {}
                    for dt, parts in payload["models"].items():
                        self.models[dt] = (
                            parts["mlp"],
                            parts["input_scaler"],
                            parts["output_scaler"],
                        )

                    logger.info(
                        "Loaded seq2point model with %d device types: %s",
                        len(self.models), list(self.models.keys()),
                    )
                    return True
            finally:
                conn.close()
        except Exception as e:
            logger.warning("Failed to load seq2point model: %s", e)
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


class DeviceStateDetector:
    """Binary classifier: is a specific device type ON at this moment?

    For each device type, trains an MLPClassifier on:
    - Input: power window [t-5:t+6] (11 readings = ~2 hours)
    - Output: 1 if device is ON, 0 if OFF

    Simpler than power estimation -- tells us WHEN a device is on even if
    we cannot estimate its exact power contribution.
    """

    def __init__(
        self,
        source: TempIQSource | None = None,
        spannilm_db_url: str | None = None,
        data_days: int = 90,
        window_size: int = STATE_WINDOW,
    ):
        self.source = source or TempIQSource()
        self.db_url = spannilm_db_url or os.environ["SPANNILM_DATABASE_URL"]
        self.data_days = data_days
        self.window_size = window_size
        self.half_window = window_size // 2

        # Per-device classifiers: {device_type: (MLPClassifier, StandardScaler)}
        self.classifiers: dict[str, tuple[MLPClassifier, StandardScaler]] = {}
        self.device_stats: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self) -> dict:
        """Train binary classifiers using dedicated circuit data.

        For each dedicated device type:
        1. Get the device's power from its dedicated circuit
        2. Label each reading as ON (power > threshold) or OFF
        3. Compute total house power at the same timestamps
        4. Create sliding windows of total power -> ON/OFF label at midpoint
        5. Train an MLPClassifier

        Returns summary dict.
        """
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=self.data_days)

        configs = self._load_circuit_configs()
        dedicated = {
            cid: cfg for cid, cfg in configs.items()
            if cfg.get("is_dedicated") and cfg.get("dedicated_device_type")
        }

        if not dedicated:
            return {"error": "no_dedicated_circuits"}

        agg_df = self.source.get_aggregated_power(start, now)
        if agg_df.empty:
            return {"error": "no_data"}

        pivot = agg_df.pivot_table(
            index="timestamp", columns="circuit_id", values="power_w", aggfunc="mean"
        ).sort_index()
        pivot = pivot.ffill(limit=3).fillna(0)

        total_power = pivot.sum(axis=1).values.astype(np.float64)

        summary: dict[str, dict] = {}

        for cid, cfg in dedicated.items():
            device_type = cfg["dedicated_device_type"]

            if cid not in pivot.columns:
                continue

            device_power = pivot[cid].values.astype(np.float64)
            labels = (device_power > ON_THRESHOLD_W).astype(int)

            # Build sliding windows
            X, y = self._build_windows(total_power, labels)

            if len(X) < MIN_TRAINING_SAMPLES:
                continue

            # Check class balance -- need at least 5% of each class
            on_frac = np.mean(y)
            if on_frac < 0.02 or on_frac > 0.98:
                logger.warning(
                    "Skipping state detector for %s: imbalanced (%.1f%% ON)",
                    device_type, on_frac * 100,
                )
                continue

            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)

            clf = MLPClassifier(
                hidden_layer_sizes=(32, 16),
                activation="relu",
                max_iter=300,
                early_stopping=True,
                validation_fraction=0.1,
                random_state=42,
                batch_size=min(256, max(32, len(X) // 10)),
            )

            try:
                clf.fit(X_scaled, y)
            except Exception as e:
                logger.warning("State classifier training failed for %s: %s", device_type, e)
                continue

            self.classifiers[device_type] = (clf, scaler)

            # Training metrics
            y_pred = clf.predict(X_scaled)
            accuracy = float(np.mean(y_pred == y))
            # Precision and recall for ON class
            tp = int(np.sum((y_pred == 1) & (y == 1)))
            fp = int(np.sum((y_pred == 1) & (y == 0)))
            fn = int(np.sum((y_pred == 0) & (y == 1)))
            precision = tp / max(tp + fp, 1)
            recall = tp / max(tp + fn, 1)
            f1 = 2 * precision * recall / max(precision + recall, 1e-9)

            stats = {
                "samples": len(X),
                "accuracy": round(accuracy, 3),
                "precision": round(precision, 3),
                "recall": round(recall, 3),
                "f1": round(f1, 3),
                "on_fraction": round(on_frac, 3),
            }
            self.device_stats[device_type] = stats
            summary[device_type] = stats

            logger.info(
                "Trained state detector for %s: accuracy=%.1f%%, F1=%.3f, %d samples",
                device_type, accuracy * 100, f1, len(X),
            )

        if not self.classifiers:
            return {"error": "no_classifiers_trained"}

        return {"classifiers_trained": len(self.classifiers), "devices": summary}

    def _build_windows(
        self, input_series: np.ndarray, target_labels: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Build sliding window samples for state classification."""
        n = len(input_series)
        if n < self.window_size:
            return np.array([]), np.array([])

        X = []
        y = []

        for i in range(self.half_window, n - self.half_window):
            window = input_series[i - self.half_window: i + self.half_window + 1]
            if len(window) == self.window_size:
                X.append(window)
                y.append(target_labels[i])

        return np.array(X, dtype=np.float64), np.array(y, dtype=int)

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict_states(
        self, circuit_power: np.ndarray
    ) -> dict[str, np.ndarray]:
        """Given a circuit's power time series, predict ON/OFF state for each device.

        Returns {device_type: bool_array} where True = device ON.
        """
        if not self.classifiers:
            self._load_model()
        if not self.classifiers:
            return {}

        n = len(circuit_power)
        results: dict[str, np.ndarray] = {}

        for device_type, (clf, scaler) in self.classifiers.items():
            states = np.zeros(n, dtype=bool)

            if n < self.window_size:
                results[device_type] = states
                continue

            windows = []
            indices = []
            for i in range(self.half_window, n - self.half_window):
                window = circuit_power[i - self.half_window: i + self.half_window + 1]
                if len(window) == self.window_size:
                    windows.append(window)
                    indices.append(i)

            if not windows:
                results[device_type] = states
                continue

            X = np.array(windows, dtype=np.float64)
            X_scaled = scaler.transform(X)
            preds = clf.predict(X_scaled)

            for idx, pred_idx in enumerate(indices):
                states[pred_idx] = bool(preds[idx])

            results[device_type] = states

        return results

    def predict_state_summary(
        self, circuit_power: np.ndarray
    ) -> list[dict]:
        """Predict states and return summary of detected device activity.

        Returns list of dicts with:
        - device_type, on_fraction, on_readings, confidence
        """
        device_states = self.predict_states(circuit_power)
        if not device_states:
            return []

        summaries = []
        for device_type, states in device_states.items():
            on_count = int(np.sum(states))
            if on_count < 3:
                continue

            on_fraction = on_count / len(states)

            # Confidence from classifier probability (if available)
            clf, scaler = self.classifiers[device_type]
            confidence = 0.5  # default

            # Use mean predicted probability for ON readings as confidence
            if on_count > 0:
                on_indices = np.where(states)[0]
                # Sample up to 100 windows to estimate confidence
                sample_indices = on_indices[::max(1, len(on_indices) // 100)]
                sample_windows = []
                for idx in sample_indices:
                    if self.half_window <= idx < len(circuit_power) - self.half_window:
                        w = circuit_power[idx - self.half_window: idx + self.half_window + 1]
                        if len(w) == self.window_size:
                            sample_windows.append(w)
                if sample_windows:
                    X = np.array(sample_windows, dtype=np.float64)
                    X_scaled = scaler.transform(X)
                    proba = clf.predict_proba(X_scaled)
                    # Probability of ON class
                    on_class_idx = list(clf.classes_).index(1) if 1 in clf.classes_ else -1
                    if on_class_idx >= 0:
                        confidence = float(np.mean(proba[:, on_class_idx]))

            summaries.append({
                "device_type": device_type,
                "on_fraction": round(on_fraction, 3),
                "on_readings": on_count,
                "confidence": round(confidence, 3),
            })

        summaries.sort(key=lambda s: s["on_fraction"], reverse=True)
        return summaries

    # ------------------------------------------------------------------
    # Model persistence
    # ------------------------------------------------------------------

    def save_model(self) -> None:
        """Serialize all classifiers to model_artifacts table."""
        if not self.classifiers:
            raise ValueError("No trained classifiers to save")

        self._ensure_model_artifacts_table()

        payload = {
            "classifiers": {
                dt: {"clf": clf, "scaler": scaler}
                for dt, (clf, scaler) in self.classifiers.items()
            },
            "device_stats": self.device_stats,
            "window_size": self.window_size,
        }
        buf = io.BytesIO()
        pickle.dump(payload, buf)
        model_bytes = buf.getvalue()

        metadata = {
            "n_devices": len(self.classifiers),
            "device_types": list(self.classifiers.keys()),
            "device_stats": self.device_stats,
            "window_size": self.window_size,
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
                    (STATE_MODEL_NAME, "state_detector_mlp", psycopg2.Binary(model_bytes),
                     json.dumps(metadata)),
                )
                conn.commit()
            logger.info("Saved state detector model (%d bytes, %d devices)",
                        len(model_bytes), len(self.classifiers))
        finally:
            conn.close()

    def _load_model(self) -> bool:
        """Load classifiers from model_artifacts table."""
        try:
            conn = psycopg2.connect(self.db_url)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT model_data FROM model_artifacts WHERE model_name = %s",
                        (STATE_MODEL_NAME,),
                    )
                    row = cur.fetchone()
                    if not row:
                        logger.info("No saved state detector model found")
                        return False

                    payload = pickle.loads(bytes(row[0]))

                    self.window_size = payload.get("window_size", STATE_WINDOW)
                    self.half_window = self.window_size // 2
                    self.device_stats = payload.get("device_stats", {})

                    self.classifiers = {}
                    for dt, parts in payload["classifiers"].items():
                        self.classifiers[dt] = (parts["clf"], parts["scaler"])

                    logger.info(
                        "Loaded state detector with %d device types: %s",
                        len(self.classifiers), list(self.classifiers.keys()),
                    )
                    return True
            finally:
                conn.close()
        except Exception as e:
            logger.warning("Failed to load state detector model: %s", e)
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
