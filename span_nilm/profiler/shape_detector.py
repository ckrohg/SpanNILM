"""Shape-based device detection engine.

Identifies devices by the shape of their power consumption curve over time,
not just power level snapshots. Each device has a distinctive waveform:
- Dishwasher: fill → wash → heat → rinse → dry (multi-phase)
- Heat pump: startup surge → steady draw with modulation
- Fridge: compressor on 20min → off 30min (regular cycling)
- Garage door: brief 15-second spike

We extract ON sessions, normalize their power curves, extract shape + temporal
features, cluster similar sessions, and characterize each cluster as a device.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
from scipy.signal import medfilt
from sklearn.cluster import HDBSCAN
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger("span_nilm.profiler.shape")

CURVE_LENGTH = 32  # Normalized curve resolution (32 points)
MIN_SESSION_DURATION_MIN = 2  # Minimum session length to analyze
MIN_SESSIONS_FOR_CLUSTERING = 5
ON_THRESHOLD_W = 15


@dataclass
class Session:
    """A continuous ON period on a circuit."""
    start_idx: int
    end_idx: int
    start_time: datetime
    end_time: datetime
    duration_min: float
    power_curve: np.ndarray  # Raw power readings during session
    timestamps: np.ndarray  # Timestamps for each reading


@dataclass
class DeviceTemplate:
    """A detected device characterized by its power curve shape."""
    cluster_id: int
    name: str
    template_curve: list[float]  # Normalized 32-point shape
    avg_power_w: float
    peak_power_w: float
    min_power_w: float
    avg_duration_min: float
    std_duration_min: float
    session_count: int
    sessions_per_day: float
    peak_hours: list[int]
    confidence: float
    # Shape descriptors
    num_phases: int  # Distinct power levels within typical session
    has_startup_surge: bool
    is_cycling: bool  # Regular on/off pattern
    duty_cycle: float  # Fraction of cycle that's ON
    ramp_up_rate: float  # W/min during startup
    energy_per_session_wh: float


class ShapeDetector:
    """Detects devices by clustering power curve shapes."""

    def __init__(
        self,
        curve_length: int = CURVE_LENGTH,
        min_session_min: float = MIN_SESSION_DURATION_MIN,
        on_threshold_w: float = ON_THRESHOLD_W,
    ):
        self.curve_length = curve_length
        self.min_session_min = min_session_min
        self.on_threshold_w = on_threshold_w

    def detect_devices(
        self, circuit_name: str, df: pd.DataFrame
    ) -> list[DeviceTemplate]:
        """Run full shape-based detection on one circuit's data.

        Args:
            circuit_name: Name of the circuit
            df: DataFrame with columns: timestamp, power_w

        Returns:
            List of detected device templates
        """
        sessions = self._extract_sessions(df)
        logger.info(
            "Circuit %s: %d sessions extracted (min duration %s min)",
            circuit_name, len(sessions), self.min_session_min,
        )

        if len(sessions) < MIN_SESSIONS_FOR_CLUSTERING:
            logger.info("Too few sessions for clustering on %s", circuit_name)
            return self._single_device_fallback(sessions, circuit_name)

        # Extract feature vectors
        features, valid_sessions = self._extract_features(sessions)
        if len(valid_sessions) < MIN_SESSIONS_FOR_CLUSTERING:
            return self._single_device_fallback(sessions, circuit_name)

        # Cluster
        labels = self._cluster_sessions(features)

        # Characterize
        devices = self._characterize_clusters(labels, valid_sessions, circuit_name)
        return devices

    def _extract_sessions(self, df: pd.DataFrame) -> list[Session]:
        """Extract continuous ON periods from power data."""
        power = df["power_w"].values.astype(float)
        timestamps = pd.to_datetime(df["timestamp"]).values

        sessions = []
        in_session = False
        start_idx = 0

        for i in range(len(power)):
            if power[i] > self.on_threshold_w and not in_session:
                in_session = True
                start_idx = i
            elif power[i] <= self.on_threshold_w and in_session:
                in_session = False
                duration_min = (
                    (timestamps[i - 1] - timestamps[start_idx])
                    / np.timedelta64(1, "m")
                )
                if duration_min >= self.min_session_min:
                    sessions.append(Session(
                        start_idx=start_idx,
                        end_idx=i,
                        start_time=pd.Timestamp(timestamps[start_idx]).to_pydatetime(),
                        end_time=pd.Timestamp(timestamps[i - 1]).to_pydatetime(),
                        duration_min=float(duration_min),
                        power_curve=power[start_idx:i].copy(),
                        timestamps=timestamps[start_idx:i].copy(),
                    ))

        # Handle session at end
        if in_session and start_idx < len(power) - 2:
            duration_min = (
                (timestamps[-1] - timestamps[start_idx])
                / np.timedelta64(1, "m")
            )
            if duration_min >= self.min_session_min:
                sessions.append(Session(
                    start_idx=start_idx,
                    end_idx=len(power),
                    start_time=pd.Timestamp(timestamps[start_idx]).to_pydatetime(),
                    end_time=pd.Timestamp(timestamps[-1]).to_pydatetime(),
                    duration_min=float(duration_min),
                    power_curve=power[start_idx:].copy(),
                    timestamps=timestamps[start_idx:].copy(),
                ))

        return sessions

    def _normalize_curve(self, power_curve: np.ndarray) -> np.ndarray | None:
        """Resample power curve to fixed length and normalize by peak.

        Returns None if curve is too short or uniform.
        """
        if len(power_curve) < 3:
            return None

        # Smooth first
        if len(power_curve) >= 5:
            smoothed = medfilt(power_curve, kernel_size=min(5, len(power_curve) | 1))
        else:
            smoothed = power_curve

        peak = np.max(smoothed)
        if peak < self.on_threshold_w:
            return None

        # Resample to fixed length
        x_orig = np.linspace(0, 1, len(smoothed))
        x_new = np.linspace(0, 1, self.curve_length)
        f = interp1d(x_orig, smoothed, kind="linear")
        resampled = f(x_new)

        # Normalize by peak (shape independent of absolute power)
        normalized = resampled / peak

        return normalized

    def _extract_features(
        self, sessions: list[Session]
    ) -> tuple[np.ndarray, list[Session]]:
        """Extract combined feature vectors for each session.

        Returns (feature_matrix, valid_sessions) — sessions with valid features.
        """
        features_list = []
        valid_sessions = []

        for session in sessions:
            curve = self._normalize_curve(session.power_curve)
            if curve is None:
                continue

            power = session.power_curve
            peak_w = float(np.max(power))
            mean_w = float(np.mean(power))
            min_w = float(np.min(power))
            std_w = float(np.std(power))

            # Shape features (normalized curve is the core shape descriptor)
            shape_features = curve  # 32 values

            # Amplitude features
            amplitude_features = np.array([
                np.log1p(peak_w),  # Log scale for power
                np.log1p(mean_w),
                std_w / max(mean_w, 1),  # Coefficient of variation
                min_w / max(peak_w, 1),  # Min/max ratio (how much it varies)
            ])

            # Temporal features
            start_hour = session.start_time.hour + session.start_time.minute / 60
            temporal_features = np.array([
                np.log1p(session.duration_min),  # Log duration
                np.sin(2 * np.pi * start_hour / 24),  # Circular encoding of time
                np.cos(2 * np.pi * start_hour / 24),
            ])

            # Pattern features
            # Number of distinct power phases (levels within session)
            if len(power) >= 5:
                rounded = np.round(power / max(50, peak_w * 0.1)) * max(50, peak_w * 0.1)
                num_phases = len(np.unique(rounded[rounded > self.on_threshold_w]))
            else:
                num_phases = 1

            # Startup surge: first 20% of session > 120% of session mean
            first_segment = power[: max(1, len(power) // 5)]
            has_surge = float(np.mean(first_segment) > mean_w * 1.2)

            # Ramp rates
            if len(power) >= 3:
                diffs = np.diff(power)
                ramp_up = float(np.max(diffs)) if len(diffs) > 0 else 0
                ramp_down = float(np.min(diffs)) if len(diffs) > 0 else 0
            else:
                ramp_up = ramp_down = 0

            pattern_features = np.array([
                np.log1p(num_phases),
                has_surge,
                np.sign(ramp_up) * np.log1p(abs(ramp_up)),
                np.sign(ramp_down) * np.log1p(abs(ramp_down)),
            ])

            # Combine all features
            feature_vec = np.concatenate([
                shape_features * 2.0,  # Weight shape features more heavily
                amplitude_features,
                temporal_features,
                pattern_features,
            ])

            features_list.append(feature_vec)
            valid_sessions.append(session)

        if not features_list:
            return np.array([]), []

        return np.array(features_list), valid_sessions

    def _cluster_sessions(self, features: np.ndarray) -> np.ndarray:
        """Cluster sessions using HDBSCAN on feature vectors."""
        # Standardize features
        scaler = StandardScaler()
        scaled = scaler.fit_transform(features)

        # HDBSCAN: discovers clusters automatically, handles noise
        clusterer = HDBSCAN(
            min_cluster_size=max(3, len(features) // 10),
            min_samples=2,
            metric="euclidean",
        )
        labels = clusterer.fit_predict(scaled)

        n_clusters = len(set(labels) - {-1})
        n_noise = (labels == -1).sum()
        logger.info(
            "Clustered %d sessions into %d device types (%d noise)",
            len(features), n_clusters, n_noise,
        )

        return labels

    def _characterize_clusters(
        self,
        labels: np.ndarray,
        sessions: list[Session],
        circuit_name: str,
    ) -> list[DeviceTemplate]:
        """Build device templates from session clusters."""
        devices = []
        unique_labels = sorted(set(labels))

        # Calculate total days for sessions_per_day
        if sessions:
            all_starts = [s.start_time for s in sessions]
            total_days = max(1, (max(all_starts) - min(all_starts)).days)
        else:
            total_days = 1

        for label in unique_labels:
            mask = labels == label
            cluster_sessions = [s for s, m in zip(sessions, mask) if m]

            if len(cluster_sessions) < 2:
                continue

            # Template: median normalized curve
            curves = []
            for s in cluster_sessions:
                c = self._normalize_curve(s.power_curve)
                if c is not None:
                    curves.append(c)

            if not curves:
                continue

            template = np.median(np.array(curves), axis=0)

            # Statistics
            powers = [np.mean(s.power_curve) for s in cluster_sessions]
            peak_powers = [np.max(s.power_curve) for s in cluster_sessions]
            min_powers = [np.min(s.power_curve) for s in cluster_sessions]
            durations = [s.duration_min for s in cluster_sessions]
            hours = [s.start_time.hour for s in cluster_sessions]
            energies = [np.mean(s.power_curve) * s.duration_min / 60 for s in cluster_sessions]

            avg_power = float(np.mean(powers))
            peak_power = float(np.mean(peak_powers))

            # Phase detection on template
            template_scaled = template * peak_power
            rounded = np.round(template_scaled / max(50, peak_power * 0.1)) * max(50, peak_power * 0.1)
            num_phases = len(np.unique(rounded[rounded > self.on_threshold_w]))

            # Startup surge
            first_20 = template[: max(1, len(template) // 5)]
            has_surge = float(np.mean(first_20)) > float(np.mean(template)) * 1.15

            # Cycling detection: are sessions regular?
            if len(cluster_sessions) >= 4:
                starts = sorted([s.start_time for s in cluster_sessions])
                intervals = [(starts[i + 1] - starts[i]).total_seconds() / 60
                             for i in range(len(starts) - 1)]
                intervals = [i for i in intervals if i < 1440]  # < 24h
                if intervals:
                    cv = np.std(intervals) / max(np.mean(intervals), 1)
                    is_cycling = cv < 0.5 and np.mean(intervals) < 120
                    duty_cycle = np.mean(durations) / max(np.mean(intervals), 1)
                else:
                    is_cycling = False
                    duty_cycle = 0
            else:
                is_cycling = False
                duty_cycle = 0

            # Ramp rate from template
            template_watts = template * peak_power
            ramp_up_rate = float(np.max(np.diff(template_watts))) if len(template_watts) > 1 else 0

            # Peak hours
            hour_counts = pd.Series(hours).value_counts()
            peak_hours = hour_counts.nlargest(3).index.tolist()

            # Name: use cluster label + power level for now
            # (Circuit profiler will add context-aware names)
            if label == -1:
                name = f"Noise/outlier ({avg_power:.0f}W)"
            else:
                name = self._infer_name(
                    avg_power, peak_power, float(np.mean(durations)),
                    num_phases, has_surge, is_cycling, circuit_name,
                )

            # Confidence based on cluster tightness
            if len(curves) >= 2:
                curve_arr = np.array(curves)
                intra_var = float(np.mean(np.std(curve_arr, axis=0)))
                confidence = max(0, min(1, 1 - intra_var * 2))
            else:
                confidence = 0.3

            # Boost confidence with more observations
            confidence = min(1.0, confidence + min(0.2, len(cluster_sessions) / 50))

            devices.append(DeviceTemplate(
                cluster_id=int(label),
                name=name,
                template_curve=template.tolist(),
                avg_power_w=round(avg_power, 1),
                peak_power_w=round(peak_power, 1),
                min_power_w=round(float(np.mean(min_powers)), 1),
                avg_duration_min=round(float(np.mean(durations)), 1),
                std_duration_min=round(float(np.std(durations)), 1),
                session_count=len(cluster_sessions),
                sessions_per_day=round(len(cluster_sessions) / total_days, 2),
                peak_hours=peak_hours,
                confidence=round(confidence, 2),
                num_phases=num_phases,
                has_startup_surge=has_surge,
                is_cycling=is_cycling,
                duty_cycle=round(duty_cycle, 3),
                ramp_up_rate=round(ramp_up_rate, 1),
                energy_per_session_wh=round(float(np.mean(energies)), 1),
            ))

        # Sort by energy contribution (sessions * energy_per_session)
        devices.sort(
            key=lambda d: d.session_count * d.energy_per_session_wh,
            reverse=True,
        )
        return devices

    def _infer_name(
        self,
        avg_power: float,
        peak_power: float,
        avg_duration: float,
        num_phases: int,
        has_surge: bool,
        is_cycling: bool,
        circuit_name: str,
    ) -> str:
        """Infer a descriptive device name from shape characteristics."""
        # Brief high-power events
        if avg_duration < 5 and peak_power > 200:
            return "Brief motor/actuator"

        # Cycling with moderate power = HVAC component or pump
        if is_cycling:
            if avg_power < 100:
                return "Cycling standby load"
            elif avg_power < 500:
                return "Cycling pump/fan"
            else:
                return "Cycling high-power load"

        # Multi-phase = complex appliance
        if num_phases >= 4:
            if avg_power > 1000:
                return "Multi-phase appliance (high power)"
            return "Multi-phase appliance"

        # Startup surge = motor load
        if has_surge:
            if avg_power < 500:
                return "Motor load (small)"
            elif avg_power < 2000:
                return "Motor load (medium)"
            else:
                return "Motor load (large)"

        # Sustained steady load
        if avg_duration > 60:
            if avg_power < 200:
                return "Sustained low load"
            elif avg_power < 1000:
                return "Sustained medium load"
            else:
                return "Sustained high load"

        # Generic by power level
        if avg_power < 100:
            return "Small load"
        elif avg_power < 500:
            return "Medium load"
        elif avg_power < 2000:
            return "Large load"
        else:
            return "Very large load"

    def _single_device_fallback(
        self, sessions: list[Session], circuit_name: str,
    ) -> list[DeviceTemplate]:
        """When too few sessions for clustering, treat all as one device."""
        if not sessions:
            return []

        all_powers = [np.mean(s.power_curve) for s in sessions]
        all_durations = [s.duration_min for s in sessions]
        all_peaks = [np.max(s.power_curve) for s in sessions]
        all_hours = [s.start_time.hour for s in sessions]

        # Build a composite template
        curves = []
        for s in sessions:
            c = self._normalize_curve(s.power_curve)
            if c is not None:
                curves.append(c)
        template = np.mean(np.array(curves), axis=0).tolist() if curves else [0.5] * self.curve_length

        return [DeviceTemplate(
            cluster_id=0,
            name=f"Primary load ({np.mean(all_powers):.0f}W avg)",
            template_curve=template,
            avg_power_w=round(float(np.mean(all_powers)), 1),
            peak_power_w=round(float(np.mean(all_peaks)), 1),
            min_power_w=round(float(min(np.min(s.power_curve) for s in sessions)), 1),
            avg_duration_min=round(float(np.mean(all_durations)), 1),
            std_duration_min=round(float(np.std(all_durations)), 1) if len(all_durations) > 1 else 0,
            session_count=len(sessions),
            sessions_per_day=0,
            peak_hours=pd.Series(all_hours).value_counts().nlargest(3).index.tolist() if all_hours else [],
            confidence=0.3,
            num_phases=1,
            has_startup_surge=False,
            is_cycling=False,
            duty_cycle=0,
            ramp_up_rate=0,
            energy_per_session_wh=round(float(np.mean(all_powers)) * float(np.mean(all_durations)) / 60, 1),
        )]
