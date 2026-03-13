"""Event detection engine for NILM-style device identification.

Detects power state transitions (step changes) in circuit time-series data,
which correspond to devices turning on/off. This is analogous to what Sense does
at 1MHz but adapted for SPAN's ~1Hz circuit-level data.

Core concepts from NILM literature:
- Edge detection: Find sudden changes in power draw
- State estimation: Determine stable power states between transitions
- Event pairing: Match ON events with corresponding OFF events
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from span_nilm.utils.config import DetectionConfig

logger = logging.getLogger("span_nilm.detection")


@dataclass
class PowerEvent:
    """A detected power transition event."""
    timestamp: pd.Timestamp
    circuit_id: str
    circuit_name: str
    power_before_w: float
    power_after_w: float
    delta_w: float
    event_type: str  # "on" or "off"

    @property
    def abs_delta(self) -> float:
        return abs(self.delta_w)


@dataclass
class DeviceRun:
    """A paired on/off event representing a single device operation."""
    circuit_id: str
    circuit_name: str
    on_event: PowerEvent
    off_event: PowerEvent | None
    power_draw_w: float  # Average power during the run
    duration_s: float | None  # Duration in seconds

    @property
    def energy_wh(self) -> float | None:
        """Estimated energy consumed during this run."""
        if self.duration_s is None:
            return None
        return self.power_draw_w * self.duration_s / 3600.0


class EventDetector:
    """Detects device on/off events from circuit power time-series.

    Uses a steady-state segmentation approach: identifies stable power levels
    and treats transitions between them as device events. This is based on
    Hart's original NILM edge detection but adapted for per-circuit data.
    """

    def __init__(self, config: DetectionConfig):
        self.min_delta = config.min_power_delta_w
        self.smoothing_window = config.smoothing_window
        self.min_state_duration = config.min_state_duration_s
        self.max_pair_gap = config.max_event_pair_gap_s

    def smooth(self, series: pd.Series) -> pd.Series:
        """Apply median filter to reduce noise while preserving edges."""
        if len(series) < self.smoothing_window:
            return series
        return series.rolling(window=self.smoothing_window, center=True, min_periods=1).median()

    def detect_edges(self, df: pd.DataFrame, circuit_id: str) -> list[PowerEvent]:
        """Detect power transition events for a single circuit.

        Uses a steady-state approach: find periods of stable power and report
        the transitions between them. This handles gradual ramps and multi-sample
        transitions better than simple differencing.
        """
        if len(df) < 3:
            return []

        circuit_name = df["circuit_name"].iloc[0] if "circuit_name" in df.columns else circuit_id
        power = self.smooth(df["power_w"].astype(float)).values
        timestamps = pd.to_datetime(df["timestamp"])

        events = []

        # Segment into stable states, then report transitions between them
        state_start = 0
        state_mean = power[0]
        state_samples = [power[0]]

        for i in range(1, len(power)):
            state_samples.append(power[i])
            running_mean = np.mean(state_samples)

            # Check if current sample deviates significantly from state mean
            if abs(power[i] - state_mean) > self.min_delta:
                # Potential transition - look ahead to confirm new stable state
                lookahead_end = min(i + self.min_state_duration, len(power))
                if lookahead_end > i + 1:
                    future = power[i:lookahead_end]
                    future_mean = np.mean(future)
                    future_std = np.std(future)

                    # New state is stable if std is low relative to the change
                    change_magnitude = abs(future_mean - state_mean)
                    if change_magnitude > self.min_delta and future_std < change_magnitude * 0.4:
                        # Confirmed transition
                        delta = future_mean - state_mean
                        event_type = "on" if delta > 0 else "off"

                        events.append(PowerEvent(
                            timestamp=timestamps.iloc[i],
                            circuit_id=circuit_id,
                            circuit_name=circuit_name,
                            power_before_w=float(state_mean),
                            power_after_w=float(future_mean),
                            delta_w=float(delta),
                            event_type=event_type,
                        ))

                        # Start new state from here
                        state_start = i
                        state_mean = future_mean
                        state_samples = [power[i]]
                        continue

            # Update running state mean (exponential moving average for efficiency)
            if len(state_samples) > self.smoothing_window * 2:
                state_samples = state_samples[-self.smoothing_window:]
            state_mean = np.mean(state_samples)

        logger.debug("Detected %d events on circuit %s", len(events), circuit_id)
        return events

    def pair_events(self, events: list[PowerEvent]) -> list[DeviceRun]:
        """Match ON events with corresponding OFF events to form device runs.

        Uses a greedy matching approach: for each ON event, find the nearest
        subsequent OFF event with a similar power magnitude on the same circuit.
        """
        on_events = [e for e in events if e.event_type == "on"]
        off_events = [e for e in events if e.event_type == "off"]
        used_off = set()
        runs = []

        for on_ev in on_events:
            best_off = None
            best_score = float("inf")

            for j, off_ev in enumerate(off_events):
                if j in used_off:
                    continue
                if off_ev.circuit_id != on_ev.circuit_id:
                    continue
                if off_ev.timestamp <= on_ev.timestamp:
                    continue

                time_gap = (off_ev.timestamp - on_ev.timestamp).total_seconds()
                if time_gap > self.max_pair_gap:
                    continue

                # Score based on power magnitude match (lower = better)
                power_diff = abs(on_ev.abs_delta - off_ev.abs_delta)
                relative_diff = power_diff / max(on_ev.abs_delta, 1.0)

                # Penalize large time gaps slightly
                time_penalty = time_gap / self.max_pair_gap * 0.2
                score = relative_diff + time_penalty

                if score < best_score and relative_diff < 0.5:
                    best_score = score
                    best_off = (j, off_ev)

            if best_off:
                j, off_ev = best_off
                used_off.add(j)
                duration = (off_ev.timestamp - on_ev.timestamp).total_seconds()
                runs.append(DeviceRun(
                    circuit_id=on_ev.circuit_id,
                    circuit_name=on_ev.circuit_name,
                    on_event=on_ev,
                    off_event=off_ev,
                    power_draw_w=on_ev.abs_delta,
                    duration_s=duration,
                ))
            else:
                # Unpaired ON event (device might still be running)
                runs.append(DeviceRun(
                    circuit_id=on_ev.circuit_id,
                    circuit_name=on_ev.circuit_name,
                    on_event=on_ev,
                    off_event=None,
                    power_draw_w=on_ev.abs_delta,
                    duration_s=None,
                ))

        logger.info(
            "Paired %d/%d ON events into device runs",
            sum(1 for r in runs if r.off_event is not None),
            len(on_events),
        )
        return runs

    def detect_all_circuits(self, df: pd.DataFrame) -> dict[str, list[PowerEvent]]:
        """Run event detection across all circuits in the dataset."""
        all_events = {}
        for circuit_id, group in df.groupby("circuit_id"):
            group = group.sort_values("timestamp").reset_index(drop=True)
            events = self.detect_edges(group, str(circuit_id))
            if events:
                all_events[str(circuit_id)] = events
        return all_events
