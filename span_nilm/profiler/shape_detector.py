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
ON_THRESHOLD_W = 8


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

    def detect_devices_subpanel(
        self, circuit_name: str, df: pd.DataFrame
    ) -> list[DeviceTemplate]:
        """Run sub-panel decomposition, then wrap results as DeviceTemplates.

        Uses SubpanelDecomposer to find step-change-based device components,
        then converts each DecomposedDevice into a DeviceTemplate for
        compatibility with the rest of the pipeline. Falls back to regular
        detect_devices() if decomposition finds < 2 devices.

        Args:
            circuit_name: Name of the circuit
            df: DataFrame with columns: timestamp, power_w

        Returns:
            List of DeviceTemplate objects
        """
        from span_nilm.profiler.subpanel_decomposer import SubpanelDecomposer

        decomposer = SubpanelDecomposer()
        decomposed = decomposer.decompose(df)

        if len(decomposed) < 2:
            logger.info(
                "Sub-panel decomposition found < 2 devices on %s, falling back to regular detection",
                circuit_name,
            )
            return self.detect_devices(circuit_name, df)

        logger.info(
            "Sub-panel decomposition found %d devices on %s",
            len(decomposed), circuit_name,
        )

        # Calculate total days for sessions_per_day context
        timestamps = pd.to_datetime(df["timestamp"])
        if len(timestamps) >= 2:
            total_days = max(1, (timestamps.iloc[-1] - timestamps.iloc[0]).days)
        else:
            total_days = 1

        devices: list[DeviceTemplate] = []
        for i, dd in enumerate(decomposed):
            # Infer a name from power level and circuit context
            if dd.is_baseload:
                name = f"Always-on baseload ({dd.power_w:.0f}W)"
            else:
                name = self._infer_name(
                    avg_power=dd.power_w,
                    peak_power=dd.power_w * 1.1,  # Approximate peak
                    avg_duration=dd.avg_duration_min,
                    num_phases=1,
                    has_surge=False,
                    is_cycling=dd.sessions_per_day > 4,
                    circuit_name=circuit_name,
                )

            # Build a flat template curve (step-change devices are ~constant power)
            template_curve = [0.8] * self.curve_length

            confidence = 0.5
            # Higher confidence with more observations
            confidence = min(0.9, confidence + min(0.3, dd.run_count / 30))

            devices.append(DeviceTemplate(
                cluster_id=i,
                name=name,
                template_curve=template_curve,
                avg_power_w=round(dd.power_w, 1),
                peak_power_w=round(dd.power_w * 1.1, 1),
                min_power_w=round(dd.power_w * 0.9, 1),
                avg_duration_min=round(dd.avg_duration_min, 1),
                std_duration_min=round(
                    (dd.max_duration_min - dd.min_duration_min) / 2, 1
                ) if dd.max_duration_min > dd.min_duration_min else 0.0,
                session_count=dd.run_count,
                sessions_per_day=dd.sessions_per_day,
                peak_hours=dd.peak_hours,
                confidence=round(confidence, 2),
                num_phases=1,
                has_startup_surge=False,
                is_cycling=dd.sessions_per_day > 4,
                duty_cycle=0.0,
                ramp_up_rate=0.0,
                energy_per_session_wh=round(
                    dd.total_energy_wh / max(dd.run_count, 1), 1
                ),
            ))

        # Sort by energy contribution
        devices.sort(
            key=lambda d: d.session_count * d.energy_per_session_wh,
            reverse=True,
        )
        return devices

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

        Features include:
        - 32-point normalized power curve (shape)
        - Amplitude: log peak/mean power, coefficient of variation, min/max ratio
        - Temporal: log duration, circular hour encoding
        - Pattern: phase count, startup surge, ramp rates
        - Transition: startup shape (first 3 curve points), shutdown shape (last 3),
          max derivative (distinguishes compressors, motors, resistive heaters)
        - Energy: log energy per session (separates short vs long runs at same power)
        - Time-of-use: 24-bin hour histogram, weekend/weekday ratio
          (built from ALL sessions, appended per-session as context features)
        - Fourier: top-3 FFT magnitudes + dominant frequency index (4 values)
        - Startup: one-hot startup type (4) + overshoot + rise time (6 values)

        Returns (feature_matrix, valid_sessions) — sessions with valid features.
        """
        from span_nilm.profiler.startup_analyzer import StartupAnalyzer

        features_list = []
        valid_sessions = []

        # --- Pre-compute startup analysis across all sessions ---
        startup_analyzer = StartupAnalyzer()
        startup_result = startup_analyzer.analyze_startup(sessions)
        startup_features_shared = startup_analyzer.get_feature_vector(startup_result)

        # --- Pre-compute time-of-use distributions across all sessions (#2) ---
        hour_histogram = np.zeros(24)
        weekday_count = 0
        weekend_count = 0
        for session in sessions:
            h = session.start_time.hour
            hour_histogram[h] += 1
            if session.start_time.weekday() < 5:
                weekday_count += 1
            else:
                weekend_count += 1
        # Normalize histogram to fractions
        total_sessions = hour_histogram.sum()
        if total_sessions > 0:
            hour_histogram = hour_histogram / total_sessions
        # Weekend vs weekday ratio (normalized by number of days: 5 weekdays, 2 weekend)
        weekday_rate = weekday_count / 5.0
        weekend_rate = weekend_count / 2.0
        weekend_weekday_ratio = weekend_rate / max(weekday_rate, 0.1)

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
            # Use 1D clustering: group consecutive readings at similar levels
            if len(power) >= 5:
                phase_threshold = max(30, mean_w * 0.15)
                phases_list: list[list[float]] = [[float(power[0])]]
                for pi in range(1, len(power)):
                    cur_mean = np.mean(phases_list[-1])
                    if abs(float(power[pi]) - cur_mean) > phase_threshold:
                        if len(phases_list[-1]) >= 2:
                            phases_list.append([float(power[pi])])
                        else:
                            phases_list[-1].append(float(power[pi]))
                    else:
                        phases_list[-1].append(float(power[pi]))
                phase_means = [np.mean(p) for p in phases_list if len(p) >= 2 and np.mean(p) > self.on_threshold_w]
                # Deduplicate similar levels
                unique_phases: list[float] = []
                for pm in phase_means:
                    if not any(abs(pm - up) < phase_threshold for up in unique_phases):
                        unique_phases.append(pm)
                num_phases = max(1, len(unique_phases))
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

            # --- Transition pattern features (#3) ---
            # Startup shape: first 3 points of normalized curve
            startup_shape = curve[:3]  # 3 values
            # Shutdown shape: last 3 points of normalized curve
            shutdown_shape = curve[-3:]  # 3 values
            # Max derivative: maximum rate of change in the normalized curve
            curve_diffs = np.diff(curve)
            max_derivative = float(np.max(np.abs(curve_diffs))) if len(curve_diffs) > 0 else 0.0
            transition_features = np.concatenate([
                startup_shape,
                shutdown_shape,
                np.array([max_derivative]),
            ])  # 7 values

            # --- Energy signature (#4) ---
            energy_wh = mean_w * session.duration_min / 60.0
            energy_features = np.array([
                np.log1p(energy_wh),  # Log energy per session
            ])  # 1 value

            # --- Time-of-use context features (#2) ---
            # The 24-bin histogram and weekend ratio are the same for all sessions
            # on this circuit, providing context about what kind of device schedule
            # this circuit exhibits (overnight = EV, mealtimes = kitchen, etc.)
            tou_features = np.concatenate([
                hour_histogram,  # 24 values
                np.array([weekend_weekday_ratio]),  # 1 value
            ])  # 25 values

            # --- Fourier / frequency domain features ---
            # FFT of the normalized curve reveals cycling and multi-phase patterns
            fft_vals = np.abs(np.fft.rfft(curve))
            # Exclude DC component (index 0), take magnitudes of remaining
            fft_no_dc = fft_vals[1:]
            if len(fft_no_dc) >= 3:
                # Top-3 frequency magnitudes (sorted descending)
                top3_indices = np.argsort(fft_no_dc)[-3:][::-1]
                top3_magnitudes = fft_no_dc[top3_indices]
                # Dominant frequency index (1-based, which harmonic is strongest)
                dominant_freq_idx = float(top3_indices[0] + 1)
            else:
                top3_magnitudes = np.zeros(3)
                dominant_freq_idx = 0.0
            fourier_features = np.concatenate([
                top3_magnitudes,                    # 3 values
                np.array([dominant_freq_idx]),       # 1 value
            ])  # 4 values total

            # --- Startup transient features ---
            # Shared across all sessions on this circuit (startup type is a
            # circuit-level characteristic, not per-session)
            # 6 values: 4 one-hot startup type + overshoot + rise_time

            # Combine all features
            feature_vec = np.concatenate([
                shape_features * 2.0,       # 32 values, weighted 2x
                amplitude_features,          # 4 values
                temporal_features,           # 3 values
                pattern_features,            # 4 values
                transition_features * 1.5,   # 7 values, weighted 1.5x (distinctive)
                energy_features * 1.5,       # 1 value, weighted 1.5x
                tou_features * 0.5,          # 25 values, weighted 0.5x (context, not per-session)
                fourier_features * 1.0,      # 4 values, weighted 1.0x
                startup_features_shared * 1.0,  # 6 values, weighted 1.0x
            ])

            features_list.append(feature_vec)
            valid_sessions.append(session)

        if not features_list:
            return np.array([]), []

        return np.array(features_list), valid_sessions

    def _cluster_sessions(self, features: np.ndarray) -> np.ndarray:
        """Cluster sessions using HDBSCAN on feature vectors.

        HDBSCAN parameters scale with data volume:
        - <20 sessions: min_cluster_size=3, min_samples=2 (loose — few data points)
        - 20-50: min_cluster_size=4, min_samples=2
        - 50-200: min_cluster_size=5, min_samples=3 (tighter clusters)
        - >200: min_cluster_size=8, min_samples=4 (very tight)
        """
        # Standardize features
        scaler = StandardScaler()
        scaled = scaler.fit_transform(features)

        n = len(features)
        if n < 20:
            min_cluster_size, min_samples = 3, 2
        elif n < 50:
            min_cluster_size, min_samples = 4, 2
        elif n <= 200:
            min_cluster_size, min_samples = 5, 3
        else:
            min_cluster_size, min_samples = 8, 4

        # HDBSCAN: discovers clusters automatically, handles noise
        clusterer = HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            metric="euclidean",
        )
        labels = clusterer.fit_predict(scaled)

        n_clusters = len(set(labels) - {-1})
        n_noise = (labels == -1).sum()
        logger.info(
            "Clustered %d sessions into %d device types (%d noise) "
            "[min_cluster_size=%d, min_samples=%d]",
            len(features), n_clusters, n_noise, min_cluster_size, min_samples,
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

            # Check for high phase variance (multiple overlapping devices)
            std_power = float(np.std(powers))
            high_phase_variance = (std_power / max(avg_power, 1)) > 0.4

            # Name: use cluster label + power level for now
            # (Circuit profiler will add context-aware names)
            if label == -1:
                name = f"Noise/outlier ({avg_power:.0f}W)"
            elif high_phase_variance:
                name = self._infer_name(
                    avg_power, peak_power, float(np.mean(durations)),
                    max(num_phases, 3), has_surge, is_cycling, circuit_name,
                )
                # Boost num_phases to reflect detected variance
                num_phases = max(num_phases, 3)
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
        """Infer a descriptive device name PURELY from energy consumption profile.

        Circuit name is NEVER used for identification. The name comes entirely
        from: power level, cycling pattern, duration, startup behavior, and
        number of power stages.
        """
        # --- NAME ENTIRELY BY ENERGY PROFILE ---

        # Brief events (< 5 min average)
        if avg_duration < 5:
            if avg_power > 1000:
                return "Brief high-power load"
            elif avg_power > 200:
                return "Motor/actuator"
            return f"Brief load ({avg_power:.0f}W)"

        # Cycling devices — the pattern is the key identifier
        if is_cycling:
            if avg_power < 50:
                return "Cycling electronics"
            elif avg_power < 150:
                return "Small compressor (fridge/freezer)"
            elif avg_power < 400:
                return "Compressor (dehumidifier/freezer)"
            elif avg_power < 1000:
                return "Large compressor or pump"
            elif avg_power < 1500:
                return "Cycling compressor"
            return "Cycling heavy load"

        # Multi-stage = complex appliance with distinct power levels
        if num_phases >= 4:
            if avg_power > 2000:
                return "Multi-stage heavy appliance"
            elif avg_power > 500:
                return "Multi-stage appliance"
            return "Variable-speed electronics"

        # Startup surge = motor load
        if has_surge:
            if avg_power < 300:
                return "Small motor"
            elif avg_power < 1500:
                return "Motor load"
            return "Large motor"

        # Sustained loads — named by power level + duration pattern
        if avg_duration > 120:  # > 2 hours
            if avg_power < 30:
                return "Standby power"
            elif avg_power < 100:
                return "Always-on electronics"
            elif avg_power < 300:
                return "Continuous appliance ({:.0f}W)".format(avg_power)
            elif avg_power < 800:
                return "Sustained load ({:.0f}W)".format(avg_power)
            elif avg_power < 1500:
                return "Heater or sustained motor ({:.0f}W)".format(avg_power)
            return "Heavy sustained load ({:.0f}W)".format(avg_power)

        if avg_duration > 20:  # 20 min - 2 hours
            if avg_power < 100:
                return "Intermittent electronics"
            elif avg_power < 300:
                return "Medium appliance ({:.0f}W)".format(avg_power)
            elif avg_power < 1000:
                return "Appliance ({:.0f}W)".format(avg_power)
            return "High-power appliance ({:.0f}W)".format(avg_power)

        # Short sessions (5-20 min)
        if avg_power < 200:
            return "Brief low-power load"
        elif avg_power < 1000:
            return "Short-run appliance ({:.0f}W)".format(avg_power)
        return "Short high-power load ({:.0f}W)".format(avg_power)

    @staticmethod
    def find_cross_circuit_matches(
        all_profiles: list[tuple[str, str, list["DeviceTemplate"]]],
    ) -> list[dict]:
        """Compare device templates across circuits to find similar devices.

        Args:
            all_profiles: list of (equipment_id, circuit_name, devices) tuples

        Returns:
            List of match dicts: {
                "device_a": (equip_id, cluster_id, name),
                "device_b": (equip_id, cluster_id, name),
                "cosine_similarity": float,
                "power_ratio": float,
            }
        """
        from numpy.linalg import norm

        matches = []
        # Build flat list of (equip_id, circuit_name, device) tuples
        flat: list[tuple[str, str, "DeviceTemplate"]] = []
        for equip_id, cname, devs in all_profiles:
            for d in devs:
                flat.append((equip_id, cname, d))

        for i in range(len(flat)):
            eid_a, _, dev_a = flat[i]
            curve_a = np.array(dev_a.template_curve)
            norm_a = norm(curve_a)
            if norm_a < 1e-9:
                continue

            for j in range(i + 1, len(flat)):
                eid_b, _, dev_b = flat[j]
                # Only compare across different circuits
                if eid_a == eid_b:
                    continue

                curve_b = np.array(dev_b.template_curve)
                norm_b = norm(curve_b)
                if norm_b < 1e-9:
                    continue

                cosine = float(np.dot(curve_a, curve_b) / (norm_a * norm_b))
                if cosine < 0.9:
                    continue

                # Check power similarity (within 20%)
                max_p = max(dev_a.avg_power_w, dev_b.avg_power_w, 1)
                min_p = min(dev_a.avg_power_w, dev_b.avg_power_w)
                power_ratio = min_p / max_p
                if power_ratio < 0.8:
                    continue

                matches.append({
                    "device_a": (eid_a, dev_a.cluster_id, dev_a.name),
                    "device_b": (eid_b, dev_b.cluster_id, dev_b.name),
                    "cosine_similarity": round(cosine, 3),
                    "power_ratio": round(power_ratio, 3),
                })
                logger.info(
                    "Cross-circuit match: %s (cluster %d) <-> %s (cluster %d) "
                    "cosine=%.3f power_ratio=%.3f",
                    dev_a.name, dev_a.cluster_id,
                    dev_b.name, dev_b.cluster_id,
                    cosine, power_ratio,
                )

        return matches

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
