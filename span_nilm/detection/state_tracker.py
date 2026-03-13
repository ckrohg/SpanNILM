"""Power state tracker for modeling device operating states.

Inspired by the Finite State Machine approach from NILM literature:
devices like dishwashers, HVAC, etc. have predictable operational phases
(e.g., wash -> heat -> rinse -> dry). By tracking power states over time,
we can build operational profiles for devices on each circuit.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger("span_nilm.detection.state")


@dataclass
class PowerState:
    """A stable power consumption state for a circuit."""
    circuit_id: str
    mean_power_w: float
    std_power_w: float
    duration_s: float
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    sample_count: int


@dataclass
class CircuitProfile:
    """Aggregated profile of a circuit's typical power states."""
    circuit_id: str
    circuit_name: str
    states: list[PowerState] = field(default_factory=list)
    # Cluster centroids of common power levels
    power_levels: list[float] = field(default_factory=list)
    # Typical transition patterns (from_level -> to_level)
    transitions: list[tuple[float, float]] = field(default_factory=list)


class StateTracker:
    """Segments circuit power data into stable states and transitions.

    Uses a changepoint detection approach to identify when the power
    consumption on a circuit shifts to a new stable level, then clusters
    these levels to identify distinct device operating modes.
    """

    def __init__(self, min_state_duration_s: int = 3, min_power_delta_w: float = 15.0):
        self.min_duration = min_state_duration_s
        self.min_delta = min_power_delta_w

    def segment_states(self, df: pd.DataFrame, circuit_id: str) -> list[PowerState]:
        """Segment a circuit's time-series into stable power states.

        Uses a simple changepoint approach: a new state begins when the
        power level shifts by more than min_delta and stays there.
        """
        if len(df) < 2:
            return []

        timestamps = pd.to_datetime(df["timestamp"])
        power = df["power_w"].astype(float).values

        states = []
        state_start_idx = 0
        current_mean = power[0]

        for i in range(1, len(power)):
            if abs(power[i] - current_mean) > self.min_delta:
                # Potential state change - check if it persists
                duration = (timestamps.iloc[i] - timestamps.iloc[state_start_idx]).total_seconds()
                if duration >= self.min_duration:
                    state_power = power[state_start_idx:i]
                    states.append(PowerState(
                        circuit_id=circuit_id,
                        mean_power_w=float(np.mean(state_power)),
                        std_power_w=float(np.std(state_power)),
                        duration_s=duration,
                        start_time=timestamps.iloc[state_start_idx],
                        end_time=timestamps.iloc[i - 1],
                        sample_count=len(state_power),
                    ))
                state_start_idx = i
                current_mean = power[i]
            else:
                # Update running mean
                state_power = power[state_start_idx:i + 1]
                current_mean = float(np.mean(state_power))

        # Final state
        if state_start_idx < len(power) - 1:
            duration = (timestamps.iloc[-1] - timestamps.iloc[state_start_idx]).total_seconds()
            if duration >= self.min_duration:
                state_power = power[state_start_idx:]
                states.append(PowerState(
                    circuit_id=circuit_id,
                    mean_power_w=float(np.mean(state_power)),
                    std_power_w=float(np.std(state_power)),
                    duration_s=duration,
                    start_time=timestamps.iloc[state_start_idx],
                    end_time=timestamps.iloc[-1],
                    sample_count=len(state_power),
                ))

        return states

    def cluster_power_levels(self, states: list[PowerState], n_clusters: int | None = None) -> list[float]:
        """Identify distinct power levels from observed states.

        Uses a simple 1D clustering approach: sort power levels and merge
        those within min_delta of each other.
        """
        if not states:
            return []

        powers = sorted(s.mean_power_w for s in states)
        clusters = [[powers[0]]]

        for p in powers[1:]:
            if abs(p - np.mean(clusters[-1])) < self.min_delta:
                clusters[-1].append(p)
            else:
                clusters.append([p])

        return [float(np.mean(c)) for c in clusters]

    def build_profile(self, df: pd.DataFrame, circuit_id: str) -> CircuitProfile:
        """Build a complete operational profile for a circuit."""
        circuit_name = df["circuit_name"].iloc[0] if "circuit_name" in df.columns else circuit_id

        states = self.segment_states(df, circuit_id)
        power_levels = self.cluster_power_levels(states)

        # Extract transition patterns
        transitions = []
        for i in range(len(states) - 1):
            transitions.append((
                round(states[i].mean_power_w, 1),
                round(states[i + 1].mean_power_w, 1),
            ))

        profile = CircuitProfile(
            circuit_id=circuit_id,
            circuit_name=circuit_name,
            states=states,
            power_levels=power_levels,
            transitions=transitions,
        )

        logger.info(
            "Circuit %s (%s): %d states, %d power levels, %d transitions",
            circuit_id, circuit_name, len(states), len(power_levels), len(transitions),
        )
        return profile
