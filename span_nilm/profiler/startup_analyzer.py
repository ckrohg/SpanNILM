"""Startup transient analysis for device fingerprinting.

The first few readings when a device turns on are highly distinctive:
- Compressors have inrush current (surge then settle)
- Motors ramp up gradually
- Resistive loads reach full power instantly
- Some devices oscillate during startup (PID control settling)

This module extracts startup characteristics from device sessions and
classifies the startup type, which serves as an additional feature for
device identification.
"""

import logging

import numpy as np

logger = logging.getLogger("span_nilm.profiler.startup")

# Number of readings to consider as the startup transient
STARTUP_READINGS = 5

# Thresholds for startup classification
SURGE_OVERSHOOT_PCT = 120.0   # > 120% of steady state = surge
RAMP_RISE_TIME = 3            # >= 3 readings to reach 90% of steady state = ramp
OSCILLATION_COV = 0.30        # std/mean > 30% during first 5 readings = oscillating

# One-hot encoding order for startup types
STARTUP_TYPES = ("instant", "ramp", "surge", "oscillating")


class StartupAnalyzer:
    """Analyzes the startup transient of device sessions to create fingerprints."""

    def analyze_startup(self, sessions: list) -> dict:
        """Extract startup characteristics from sessions.

        Args:
            sessions: List of Session objects (from shape_detector) with
                      power_curve (numpy array) and timestamps.

        Returns:
            {
                "startup_type": "instant" | "ramp" | "surge" | "oscillating",
                "rise_time_readings": int,
                "overshoot_pct": float,
                "steady_state_reached_pct": float,
                "startup_curve": list[float],  # first 5 readings normalized
            }
        """
        if not sessions:
            return self._default_result()

        # Analyze each session's startup and aggregate
        all_overshoot = []
        all_rise_time = []
        all_startup_curves = []

        for session in sessions:
            power = session.power_curve
            if len(power) < 3:
                continue

            n_startup = min(STARTUP_READINGS, len(power))
            startup = power[:n_startup]

            # Steady state = median of readings after the startup transient
            if len(power) > STARTUP_READINGS:
                steady_state = float(np.median(power[STARTUP_READINGS:]))
            else:
                # Short session: use last reading as steady state estimate
                steady_state = float(power[-1])

            if steady_state < 1.0:
                # Avoid division by zero for near-zero steady state
                continue

            # Overshoot: max of startup vs steady state
            peak_startup = float(np.max(startup))
            overshoot_pct = (peak_startup / steady_state) * 100.0
            all_overshoot.append(overshoot_pct)

            # Rise time: how many readings to reach 90% of steady state
            target = steady_state * 0.9
            rise_time = 1  # minimum
            for ri in range(len(startup)):
                if startup[ri] >= target:
                    rise_time = ri + 1
                    break
            else:
                rise_time = len(startup)
            all_rise_time.append(rise_time)

            # Normalized startup curve (by steady state)
            normalized = startup / steady_state
            # Pad or truncate to exactly STARTUP_READINGS
            if len(normalized) < STARTUP_READINGS:
                padded = np.ones(STARTUP_READINGS)
                padded[:len(normalized)] = normalized
                normalized = padded
            all_startup_curves.append(normalized[:STARTUP_READINGS])

        if not all_overshoot:
            return self._default_result()

        # Aggregate across sessions
        median_overshoot = float(np.median(all_overshoot))
        median_rise_time = int(np.median(all_rise_time))
        mean_startup_curve = np.mean(all_startup_curves, axis=0).tolist()

        # Compute steady-state-reached percentage
        steady_reached = (mean_startup_curve[-1] / max(mean_startup_curve[0], 0.01)) * 100.0 if mean_startup_curve else 100.0

        # Classify startup type
        startup_type = self._classify_startup(
            median_overshoot, median_rise_time, all_startup_curves
        )

        return {
            "startup_type": startup_type,
            "rise_time_readings": median_rise_time,
            "overshoot_pct": round(median_overshoot, 1),
            "steady_state_reached_pct": round(steady_reached, 1),
            "startup_curve": [round(v, 3) for v in mean_startup_curve],
        }

    def get_feature_vector(self, startup_result: dict) -> np.ndarray:
        """Convert startup analysis to a feature vector for clustering.

        Returns:
            6-element numpy array:
              [one_hot_instant, one_hot_ramp, one_hot_surge, one_hot_oscillating,
               overshoot_pct_normalized, rise_time_normalized]
        """
        # One-hot encode startup type (4 values)
        one_hot = np.zeros(len(STARTUP_TYPES))
        stype = startup_result.get("startup_type", "instant")
        if stype in STARTUP_TYPES:
            one_hot[STARTUP_TYPES.index(stype)] = 1.0
        else:
            one_hot[0] = 1.0  # default to instant

        # Numeric features (normalized to ~0-1 range)
        overshoot_norm = min(startup_result.get("overshoot_pct", 100.0) / 200.0, 2.0)
        rise_time_norm = min(startup_result.get("rise_time_readings", 1) / float(STARTUP_READINGS), 1.0)

        return np.concatenate([
            one_hot,                                    # 4 values
            np.array([overshoot_norm, rise_time_norm]), # 2 values
        ])  # Total: 6

    def _classify_startup(
        self,
        overshoot_pct: float,
        rise_time: int,
        startup_curves: list[np.ndarray],
    ) -> str:
        """Classify the startup transient type.

        Priority: surge > oscillating > ramp > instant
        - surge: overshoot > 120% of steady state (compressor inrush)
        - oscillating: high variance in startup readings (PID settling)
        - ramp: >= 3 readings to reach 90% of steady state (motor spin-up)
        - instant: everything else (resistive loads)
        """
        # Check for surge (inrush current)
        if overshoot_pct > SURGE_OVERSHOOT_PCT:
            return "surge"

        # Check for oscillation in startup curves
        if startup_curves:
            startup_arr = np.array(startup_curves)
            mean_curve = np.mean(startup_arr, axis=0)
            mean_val = float(np.mean(mean_curve))
            std_val = float(np.std(mean_curve))
            if mean_val > 0 and (std_val / mean_val) > OSCILLATION_COV:
                return "oscillating"

        # Check for slow ramp
        if rise_time >= RAMP_RISE_TIME:
            return "ramp"

        return "instant"

    def _default_result(self) -> dict:
        """Return default startup analysis when no sessions are available."""
        return {
            "startup_type": "instant",
            "rise_time_readings": 1,
            "overshoot_pct": 100.0,
            "steady_state_reached_pct": 100.0,
            "startup_curve": [1.0] * STARTUP_READINGS,
        }
