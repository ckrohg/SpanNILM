"""Sub-panel step-change decomposition engine.

Decomposes a sub-panel circuit's aggregated power time series into individual
device contributions by detecting step changes and pairing ON/OFF events.

Sub-panels aggregate multiple devices on one circuit breaker. Unlike single-device
circuits where shape detection works well, sub-panels show overlapping power draws.
This decomposer identifies the individual step changes (device ON/OFF transitions)
and clusters them by power magnitude to discover distinct devices.

Algorithm:
1. Detect step changes (|delta| > threshold between consecutive readings)
2. Pair ON/OFF events (greedy matching by power magnitude + time proximity)
3. Extract component runs from matched pairs
4. Detect baseload (always-on component)
5. Cluster runs by power level to identify distinct devices
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger("span_nilm.profiler.subpanel")

# Minimum power change to register as a step event
STEP_THRESHOLD_W = 30

# Maximum time between ON and OFF for pairing (24 hours in seconds)
MAX_PAIR_GAP_S = 24 * 3600

# Power matching tolerance for ON/OFF pairing (25%)
POWER_MATCH_TOLERANCE = 0.25

# Power clustering tolerance (20%) for grouping runs into devices
POWER_CLUSTER_TOLERANCE = 0.20

# Baseload percentile
BASELOAD_PERCENTILE = 10


@dataclass
class StepEvent:
    """A detected step change in power."""
    timestamp: pd.Timestamp
    delta_w: float
    direction: str  # "on" or "off"
    power_before_w: float
    power_after_w: float

    @property
    def abs_delta(self) -> float:
        return abs(self.delta_w)


@dataclass
class ComponentRun:
    """A single device operation from a matched ON/OFF pair."""
    power_w: float
    start: pd.Timestamp
    end: pd.Timestamp | None
    duration_min: float | None
    energy_wh: float | None


@dataclass
class DecomposedDevice:
    """A distinct device identified by clustering component runs."""
    power_w: float          # Characteristic power of this device
    run_count: int
    avg_duration_min: float
    total_energy_wh: float
    peak_hours: list[int]
    is_baseload: bool
    sessions_per_day: float
    # For matching with shape detector
    power_std_w: float
    min_duration_min: float
    max_duration_min: float


class SubpanelDecomposer:
    """Decomposes a sub-panel circuit's power into individual device contributions.

    Takes 10-min aggregated power data and uses step-change detection to find
    individual device ON/OFF transitions within the combined signal.
    """

    def __init__(
        self,
        step_threshold_w: float = STEP_THRESHOLD_W,
        max_pair_gap_s: float = MAX_PAIR_GAP_S,
        power_match_tolerance: float = POWER_MATCH_TOLERANCE,
        power_cluster_tolerance: float = POWER_CLUSTER_TOLERANCE,
    ):
        self.step_threshold_w = step_threshold_w
        self.max_pair_gap_s = max_pair_gap_s
        self.power_match_tolerance = power_match_tolerance
        self.power_cluster_tolerance = power_cluster_tolerance

    def decompose(self, df: pd.DataFrame) -> list[DecomposedDevice]:
        """Decompose a circuit's power time series into individual devices.

        Args:
            df: DataFrame with columns: timestamp, power_w
                (single circuit, sorted by timestamp)

        Returns:
            List of DecomposedDevice, one per identified device (including baseload).
        """
        if len(df) < 3:
            logger.debug("Too few readings (%d) for decomposition", len(df))
            return []

        power = df["power_w"].values.astype(float)
        timestamps = pd.to_datetime(df["timestamp"])

        # Step 1: Detect step changes
        events = self._detect_steps(power, timestamps)
        logger.info("Detected %d step events", len(events))

        # Step 2: Pair ON/OFF events
        runs = self._pair_events(events)
        paired = sum(1 for r in runs if r.end is not None)
        logger.info("Paired %d/%d ON events into runs", paired, len(runs))

        # Step 3: Detect baseload
        baseload_w = float(np.percentile(power, BASELOAD_PERCENTILE))

        # Step 4: Cluster runs by power level
        devices = self._cluster_runs(runs, baseload_w, timestamps)

        logger.info(
            "Decomposed into %d devices (baseload=%.0fW, %d component runs)",
            len(devices), baseload_w, len(runs),
        )
        return devices

    def _detect_steps(
        self, power: np.ndarray, timestamps: pd.DatetimeIndex
    ) -> list[StepEvent]:
        """Detect step changes between consecutive readings.

        For each pair of consecutive readings, if |delta| > threshold,
        record a StepEvent.
        """
        events = []
        for i in range(1, len(power)):
            delta = power[i] - power[i - 1]
            if abs(delta) > self.step_threshold_w:
                direction = "on" if delta > 0 else "off"
                events.append(StepEvent(
                    timestamp=timestamps.iloc[i],
                    delta_w=float(delta),
                    direction=direction,
                    power_before_w=float(power[i - 1]),
                    power_after_w=float(power[i]),
                ))
        return events

    def _pair_events(self, events: list[StepEvent]) -> list[ComponentRun]:
        """Match ON events with corresponding OFF events.

        Uses greedy matching similar to EventDetector.pair_events():
        - OFF must come after ON, within max_pair_gap_s
        - OFF delta magnitude within power_match_tolerance of ON delta
        - Score = power_mismatch/max_power + time_gap/max_gap
        - Best score first (greedy)
        """
        on_events = [e for e in events if e.direction == "on"]
        off_events = [e for e in events if e.direction == "off"]
        used_off: set[int] = set()
        runs: list[ComponentRun] = []

        # Build candidate pairs with scores, then greedily assign
        candidates: list[tuple[float, int, int]] = []  # (score, on_idx, off_idx)

        for i, on_ev in enumerate(on_events):
            for j, off_ev in enumerate(off_events):
                if off_ev.timestamp <= on_ev.timestamp:
                    continue

                time_gap = (off_ev.timestamp - on_ev.timestamp).total_seconds()
                if time_gap > self.max_pair_gap_s:
                    continue

                # Power magnitude match
                power_diff = abs(on_ev.abs_delta - off_ev.abs_delta)
                relative_diff = power_diff / max(on_ev.abs_delta, 1.0)
                if relative_diff > self.power_match_tolerance:
                    continue

                # Score: lower is better
                score = (
                    relative_diff
                    + time_gap / self.max_pair_gap_s * 0.2
                )
                candidates.append((score, i, j))

        # Greedy matching: best score first
        candidates.sort(key=lambda c: c[0])
        used_on: set[int] = set()

        for score, on_idx, off_idx in candidates:
            if on_idx in used_on or off_idx in used_off:
                continue

            on_ev = on_events[on_idx]
            off_ev = off_events[off_idx]
            used_on.add(on_idx)
            used_off.add(off_idx)

            duration_s = (off_ev.timestamp - on_ev.timestamp).total_seconds()
            duration_min = duration_s / 60.0
            power_w = on_ev.abs_delta
            energy_wh = power_w * duration_s / 3600.0

            runs.append(ComponentRun(
                power_w=power_w,
                start=on_ev.timestamp,
                end=off_ev.timestamp,
                duration_min=duration_min,
                energy_wh=energy_wh,
            ))

        # Add unmatched ON events (device still running)
        for i, on_ev in enumerate(on_events):
            if i not in used_on:
                runs.append(ComponentRun(
                    power_w=on_ev.abs_delta,
                    start=on_ev.timestamp,
                    end=None,
                    duration_min=None,
                    energy_wh=None,
                ))

        return runs

    def _cluster_runs(
        self,
        runs: list[ComponentRun],
        baseload_w: float,
        timestamps: pd.DatetimeIndex,
    ) -> list[DecomposedDevice]:
        """Cluster component runs by power level to identify distinct devices.

        Groups runs whose power levels are within power_cluster_tolerance of each
        other. Each group becomes one DecomposedDevice. Also creates a baseload
        device if baseload is significant.
        """
        devices: list[DecomposedDevice] = []

        # Calculate total observation period in days
        if len(timestamps) >= 2:
            total_days = max(
                1.0,
                (timestamps.iloc[-1] - timestamps.iloc[0]).total_seconds() / 86400,
            )
        else:
            total_days = 1.0

        # Add baseload device
        if baseload_w > 5:
            # Baseload energy = baseload_w * total_hours
            total_hours = total_days * 24
            devices.append(DecomposedDevice(
                power_w=round(baseload_w, 1),
                run_count=1,
                avg_duration_min=round(total_hours * 60, 1),
                total_energy_wh=round(baseload_w * total_hours, 1),
                peak_hours=list(range(24)),  # Always on
                is_baseload=True,
                sessions_per_day=0.0,
                power_std_w=0.0,
                min_duration_min=round(total_hours * 60, 1),
                max_duration_min=round(total_hours * 60, 1),
            ))

        if not runs:
            return devices

        # Sort runs by power level for clustering
        completed_runs = [r for r in runs if r.duration_min is not None]
        if not completed_runs:
            # Only unmatched runs; create a single cluster from them
            unmatched = [r for r in runs if r.duration_min is None]
            if unmatched:
                powers = [r.power_w for r in unmatched]
                hours = [r.start.hour for r in unmatched]
                hour_counts = pd.Series(hours).value_counts()
                devices.append(DecomposedDevice(
                    power_w=round(float(np.median(powers)), 1),
                    run_count=len(unmatched),
                    avg_duration_min=0.0,
                    total_energy_wh=0.0,
                    peak_hours=hour_counts.nlargest(3).index.tolist(),
                    is_baseload=False,
                    sessions_per_day=round(len(unmatched) / total_days, 2),
                    power_std_w=round(float(np.std(powers)), 1) if len(powers) > 1 else 0.0,
                    min_duration_min=0.0,
                    max_duration_min=0.0,
                ))
            return devices

        # Cluster completed runs by power level
        sorted_runs = sorted(completed_runs, key=lambda r: r.power_w)
        clusters: list[list[ComponentRun]] = [[sorted_runs[0]]]

        for run in sorted_runs[1:]:
            cluster_center = float(np.median([r.power_w for r in clusters[-1]]))
            if abs(run.power_w - cluster_center) / max(cluster_center, 1.0) <= self.power_cluster_tolerance:
                clusters[-1].append(run)
            else:
                clusters.append([run])

        # Also assign unmatched runs to nearest cluster
        unmatched_runs = [r for r in runs if r.duration_min is None]
        for run in unmatched_runs:
            best_cluster = None
            best_dist = float("inf")
            for ci, cluster in enumerate(clusters):
                center = float(np.median([r.power_w for r in cluster]))
                dist = abs(run.power_w - center) / max(center, 1.0)
                if dist < best_dist:
                    best_dist = dist
                    best_cluster = ci
            if best_cluster is not None and best_dist <= self.power_cluster_tolerance:
                clusters[best_cluster].append(run)

        # Merge clusters that are likely the same physical device at different
        # operating levels (e.g., a mini-split modulating between 200W-1200W).
        # Two clusters merge if:
        # - Their power ranges overlap or are adjacent (gap < 50% of lower cluster center)
        # - They have similar temporal patterns (>50% of runs in the same hours)
        clusters = self._merge_modulating_device_clusters(clusters)
        logger.info("After merging modulating devices: %d clusters", len(clusters))

        # Limit to max ~6 devices per sub-panel (most sub-panels have 3-6 loads)
        # Keep the clusters with the most total energy
        if len(clusters) > 6:
            cluster_energies = []
            for cluster in clusters:
                total_e = sum(r.energy_wh or 0 for r in cluster)
                cluster_energies.append((total_e, cluster))
            cluster_energies.sort(key=lambda x: x[0], reverse=True)
            # Keep top 6 by energy, merge the rest into the closest cluster
            top_clusters = [c for _, c in cluster_energies[:6]]
            remaining = [c for _, c in cluster_energies[6:]]
            for rem_cluster in remaining:
                rem_center = float(np.median([r.power_w for r in rem_cluster]))
                best_idx = 0
                best_dist = float("inf")
                for i, tc in enumerate(top_clusters):
                    tc_center = float(np.median([r.power_w for r in tc]))
                    dist = abs(rem_center - tc_center)
                    if dist < best_dist:
                        best_dist = dist
                        best_idx = i
                top_clusters[best_idx].extend(rem_cluster)
            clusters = top_clusters

        # Convert clusters to DecomposedDevice
        for cluster in clusters:
            powers = [r.power_w for r in cluster]
            durations = [r.duration_min for r in cluster if r.duration_min is not None]
            energies = [r.energy_wh for r in cluster if r.energy_wh is not None]
            hours = [r.start.hour for r in cluster]

            hour_counts = pd.Series(hours).value_counts()

            avg_dur = float(np.mean(durations)) if durations else 0.0
            min_dur = float(np.min(durations)) if durations else 0.0
            max_dur = float(np.max(durations)) if durations else 0.0
            total_energy = float(np.sum(energies)) if energies else 0.0

            devices.append(DecomposedDevice(
                power_w=round(float(np.median(powers)), 1),
                run_count=len(cluster),
                avg_duration_min=round(avg_dur, 1),
                total_energy_wh=round(total_energy, 1),
                peak_hours=hour_counts.nlargest(3).index.tolist(),
                is_baseload=False,
                sessions_per_day=round(len(cluster) / total_days, 2),
                power_std_w=round(float(np.std(powers)), 1) if len(powers) > 1 else 0.0,
                min_duration_min=round(min_dur, 1),
                max_duration_min=round(max_dur, 1),
            ))

        # Sort by total energy contribution (descending)
        devices.sort(key=lambda d: d.total_energy_wh, reverse=True)

        return devices

    def _merge_modulating_device_clusters(
        self, clusters: list[list[ComponentRun]]
    ) -> list[list[ComponentRun]]:
        """Merge clusters that represent the same device at different power levels.

        A modulating device (mini-split, variable-speed motor) produces step changes
        at many power levels. The initial clustering creates separate groups for each
        level. This method merges clusters that form a continuous power range and
        share temporal patterns.

        Merge criteria:
        - Power gap between adjacent clusters is < 50% of lower cluster's median power
        - OR clusters have overlapping peak hours (>= 2 shared top-3 hours)
        """
        if len(clusters) <= 1:
            return clusters

        # Sort clusters by median power
        clusters_sorted = sorted(
            clusters, key=lambda c: float(np.median([r.power_w for r in c]))
        )

        merged: list[list[ComponentRun]] = [clusters_sorted[0]]

        for cluster in clusters_sorted[1:]:
            prev_cluster = merged[-1]
            prev_center = float(np.median([r.power_w for r in prev_cluster]))
            curr_center = float(np.median([r.power_w for r in cluster]))

            # Check power gap
            gap = curr_center - prev_center
            gap_ratio = gap / max(prev_center, 1)

            # Check temporal overlap
            prev_hours = set(r.start.hour for r in prev_cluster)
            curr_hours = set(r.start.hour for r in cluster)
            # Get top-5 hours for each
            from collections import Counter
            prev_top = set(h for h, _ in Counter(r.start.hour for r in prev_cluster).most_common(5))
            curr_top = set(h for h, _ in Counter(r.start.hour for r in cluster).most_common(5))
            shared_hours = len(prev_top & curr_top)

            # Merge if power levels are close OR temporal patterns overlap
            should_merge = (
                gap_ratio < 0.5  # Power levels within 50% of each other
                or shared_hours >= 2  # Share at least 2 peak hours
            )

            if should_merge:
                merged[-1].extend(cluster)
            else:
                merged.append(cluster)

        logger.debug(
            "Merged %d initial clusters into %d device groups",
            len(clusters_sorted), len(merged),
        )
        return merged
