"""Temporal pattern analyzer for circuit power data.

Analyzes time-series behavior to identify devices:
- Cycling detection (period, duty cycle, regularity)
- Usage duration patterns (short bursts vs sustained runs)
- Time-of-day scheduling (when does the circuit activate?)
- Cross-circuit correlation (circuits that activate together)
- Multi-level state machine (transitions between power levels)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger("span_nilm.profiler.temporal")

# Minimum power to consider "on"
ON_THRESHOLD_W = 20


@dataclass
class CyclePattern:
    """A detected cycling pattern on a circuit."""
    median_on_min: float
    median_off_min: float
    median_period_min: float
    duty_cycle: float  # fraction of time ON within a cycle
    regularity: float  # 0-1, how regular the cycling is
    count: int  # number of observed cycles
    median_power_w: float
    power_std_w: float
    peak_hours: list[int] = field(default_factory=list)


@dataclass
class UsageSession:
    """A continuous period where the circuit was actively used."""
    start: datetime
    end: datetime
    duration_min: float
    avg_power_w: float
    max_power_w: float
    energy_wh: float
    power_levels: list[float] = field(default_factory=list)  # distinct power states during session


@dataclass
class TemporalProfile:
    """Complete temporal analysis of a circuit."""
    equipment_id: str
    circuit_name: str
    total_sessions: int
    total_hours_on: float
    duty_cycle_overall: float  # fraction of total time the circuit is active

    # Session statistics
    median_session_min: float
    avg_session_min: float
    short_sessions: int  # < 5 min (brief pulses)
    medium_sessions: int  # 5-60 min (normal operation)
    long_sessions: int  # > 60 min (sustained runs)

    # Cycling
    has_cycling: bool
    cycle_pattern: CyclePattern | None

    # Schedule
    hourly_activity: list[float]  # 24 values: fraction of time active per hour
    peak_hours: list[int]  # top 3 most active hours
    weekday_vs_weekend: float  # ratio of weekday to weekend activity

    # Cross-circuit correlations (filled in later)
    correlated_circuits: list[tuple[str, float]] = field(default_factory=list)


class TemporalAnalyzer:
    """Analyzes temporal patterns in circuit power data."""

    def __init__(self, min_power_w: float = ON_THRESHOLD_W):
        self.min_power_w = min_power_w

    def analyze_circuit(
        self, equipment_id: str, circuit_name: str, df: pd.DataFrame
    ) -> TemporalProfile:
        """Analyze temporal patterns for a single circuit's power data."""
        power = df["power_w"].values.astype(float)
        timestamps = pd.to_datetime(df["timestamp"])

        # Extract sessions (continuous ON periods)
        sessions = self._extract_sessions(power, timestamps)

        # Session duration statistics
        durations = [s.duration_min for s in sessions]
        if not durations:
            return self._empty_profile(equipment_id, circuit_name)

        dur_arr = np.array(durations)
        total_on_hours = sum(s.duration_min for s in sessions) / 60
        total_hours = (timestamps.iloc[-1] - timestamps.iloc[0]).total_seconds() / 3600

        # Cycling detection
        cycle_pattern = self._detect_cycling(sessions, timestamps)

        # Hourly activity pattern
        hourly_activity = self._compute_hourly_activity(power, timestamps)
        peak_hours = sorted(range(24), key=lambda h: hourly_activity[h], reverse=True)[:3]

        # Weekday vs weekend
        weekday_vs_weekend = self._weekday_weekend_ratio(sessions)

        return TemporalProfile(
            equipment_id=equipment_id,
            circuit_name=circuit_name,
            total_sessions=len(sessions),
            total_hours_on=round(total_on_hours, 1),
            duty_cycle_overall=round(total_on_hours / max(total_hours, 1), 3),
            median_session_min=round(float(np.median(dur_arr)), 1),
            avg_session_min=round(float(np.mean(dur_arr)), 1),
            short_sessions=int(np.sum(dur_arr < 5)),
            medium_sessions=int(np.sum((dur_arr >= 5) & (dur_arr <= 60))),
            long_sessions=int(np.sum(dur_arr > 60)),
            has_cycling=cycle_pattern is not None,
            cycle_pattern=cycle_pattern,
            hourly_activity=hourly_activity,
            peak_hours=peak_hours,
            weekday_vs_weekend=round(weekday_vs_weekend, 2),
        )

    def find_correlations(
        self, df: pd.DataFrame, circuit_ids: list[str]
    ) -> dict[str, list[tuple[str, float]]]:
        """Find circuits whose ON/OFF patterns are correlated.

        Returns a dict mapping circuit_id -> [(correlated_circuit_id, correlation_score)].
        """
        # Resample each circuit to 5-min binary ON/OFF series
        binary_series = {}
        for cid in circuit_ids:
            cdf = df[df["circuit_id"] == cid].set_index("timestamp")
            if len(cdf) < 10:
                continue
            # Resample to 5-min bins: is the circuit ON in this bin?
            resampled = cdf["power_w"].resample("5min").mean()
            binary_series[cid] = (resampled > self.min_power_w).astype(float)

        # Compute pairwise correlation
        correlations: dict[str, list[tuple[str, float]]] = {}
        cids = list(binary_series.keys())

        for i, cid_a in enumerate(cids):
            corrs = []
            for j, cid_b in enumerate(cids):
                if i == j:
                    continue
                # Align on common timestamps
                aligned = pd.concat(
                    [binary_series[cid_a], binary_series[cid_b]],
                    axis=1, keys=["a", "b"]
                ).dropna()
                if len(aligned) < 20:
                    continue
                corr = float(aligned["a"].corr(aligned["b"]))
                if corr > 0.3:  # meaningful correlation
                    corrs.append((cid_b, round(corr, 2)))

            if corrs:
                correlations[cid_a] = sorted(corrs, key=lambda x: x[1], reverse=True)

        return correlations

    def _extract_sessions(
        self, power: np.ndarray, timestamps: pd.Series
    ) -> list[UsageSession]:
        """Extract continuous ON sessions from the power time-series."""
        is_on = power > self.min_power_w
        sessions = []

        in_session = False
        session_start_idx = 0

        for i in range(len(is_on)):
            if is_on[i] and not in_session:
                in_session = True
                session_start_idx = i
            elif not is_on[i] and in_session:
                in_session = False
                # Session ended
                session_power = power[session_start_idx:i]
                duration_min = (
                    timestamps.iloc[i - 1] - timestamps.iloc[session_start_idx]
                ).total_seconds() / 60

                if duration_min < 0.5:  # skip sub-30-second blips
                    continue

                # Find distinct power levels within this session
                levels = self._find_session_levels(session_power)

                sessions.append(UsageSession(
                    start=timestamps.iloc[session_start_idx].to_pydatetime(),
                    end=timestamps.iloc[i - 1].to_pydatetime(),
                    duration_min=round(duration_min, 1),
                    avg_power_w=round(float(np.mean(session_power)), 1),
                    max_power_w=round(float(np.max(session_power)), 1),
                    energy_wh=round(float(np.mean(session_power)) * duration_min / 60, 1),
                    power_levels=levels,
                ))

        # Handle session at end of data
        if in_session and session_start_idx < len(power) - 1:
            session_power = power[session_start_idx:]
            duration_min = (
                timestamps.iloc[-1] - timestamps.iloc[session_start_idx]
            ).total_seconds() / 60
            if duration_min >= 0.5:
                levels = self._find_session_levels(session_power)
                sessions.append(UsageSession(
                    start=timestamps.iloc[session_start_idx].to_pydatetime(),
                    end=timestamps.iloc[-1].to_pydatetime(),
                    duration_min=round(duration_min, 1),
                    avg_power_w=round(float(np.mean(session_power)), 1),
                    max_power_w=round(float(np.max(session_power)), 1),
                    energy_wh=round(float(np.mean(session_power)) * duration_min / 60, 1),
                    power_levels=levels,
                ))

        return sessions

    def _find_session_levels(self, power: np.ndarray) -> list[float]:
        """Find distinct power levels within a single session using 1D clustering.

        Groups consecutive readings at similar power levels into phases,
        then returns the distinct mean power of each phase.
        """
        if len(power) < 3:
            return [round(float(np.mean(power)), 0)]

        # 1D clustering: walk through readings, group consecutive similar values
        # A new phase starts when power changes by more than threshold
        threshold = max(30, np.mean(power) * 0.15)  # 15% of mean or 30W minimum
        phases: list[list[float]] = [[float(power[0])]]

        for i in range(1, len(power)):
            current_phase_mean = np.mean(phases[-1])
            if abs(float(power[i]) - current_phase_mean) > threshold:
                # Start a new phase (only if current phase has enough readings)
                if len(phases[-1]) >= 2:
                    phases.append([float(power[i])])
                else:
                    # Single-reading phase, extend it
                    phases[-1].append(float(power[i]))
            else:
                phases[-1].append(float(power[i]))

        # Compute mean of each phase, deduplicate similar levels
        phase_means = [round(float(np.mean(p)), 0) for p in phases if len(p) >= 2]
        if not phase_means:
            phase_means = [round(float(np.mean(power)), 0)]

        # Merge phases that are within threshold of each other
        unique_levels = []
        for level in phase_means:
            if level <= 0:
                continue
            merged = False
            for j, existing in enumerate(unique_levels):
                if abs(level - existing) < threshold:
                    # Weighted merge
                    unique_levels[j] = round((existing + level) / 2, 0)
                    merged = True
                    break
            if not merged:
                unique_levels.append(level)

        return sorted(unique_levels) if unique_levels else [round(float(np.mean(power)), 0)]

    def _detect_cycling(
        self, sessions: list[UsageSession], timestamps: pd.Series
    ) -> CyclePattern | None:
        """Detect regular cycling patterns from sessions."""
        if len(sessions) < 5:
            return None

        # Compute intervals between session starts
        starts = [s.start for s in sessions]
        intervals_min = []
        for i in range(1, len(starts)):
            gap = (starts[i] - starts[i - 1]).total_seconds() / 60
            if gap < 1440:  # ignore gaps > 24 hours
                intervals_min.append(gap)

        if len(intervals_min) < 4:
            return None

        intervals = np.array(intervals_min)
        median_period = float(np.median(intervals))

        if median_period < 2:  # too fast to be real cycling
            return None

        # Regularity: coefficient of variation (lower = more regular)
        cv = float(np.std(intervals)) / max(median_period, 1)
        regularity = max(0, 1.0 - cv)

        # ON durations and OFF gaps
        on_durations = np.array([s.duration_min for s in sessions])
        off_gaps = []
        for i in range(len(sessions) - 1):
            gap = (sessions[i + 1].start - sessions[i].end).total_seconds() / 60
            if 0 < gap < 1440:
                off_gaps.append(gap)

        median_on = float(np.median(on_durations))
        median_off = float(np.median(off_gaps)) if off_gaps else 0.0
        duty_cycle = median_on / max(median_on + median_off, 1)

        powers = np.array([s.avg_power_w for s in sessions])

        # Peak hours
        hours = [s.start.hour for s in sessions]
        hour_counts = pd.Series(hours).value_counts()
        peak_hours = hour_counts.nlargest(3).index.tolist()

        return CyclePattern(
            median_on_min=round(median_on, 1),
            median_off_min=round(median_off, 1),
            median_period_min=round(median_period, 1),
            duty_cycle=round(duty_cycle, 3),
            regularity=round(regularity, 2),
            count=len(sessions),
            median_power_w=round(float(np.median(powers)), 1),
            power_std_w=round(float(np.std(powers)), 1),
            peak_hours=peak_hours,
        )

    def _compute_hourly_activity(
        self, power: np.ndarray, timestamps: pd.Series
    ) -> list[float]:
        """Compute fraction of time active per hour of day."""
        hours = timestamps.dt.hour
        activity = []
        for h in range(24):
            mask = hours == h
            if mask.sum() == 0:
                activity.append(0.0)
            else:
                pct_on = float((power[mask] > self.min_power_w).mean())
                activity.append(round(pct_on, 3))
        return activity

    def _weekday_weekend_ratio(self, sessions: list[UsageSession]) -> float:
        """Ratio of weekday to weekend session count (normalized by days)."""
        weekday_count = sum(1 for s in sessions if s.start.weekday() < 5)
        weekend_count = sum(1 for s in sessions if s.start.weekday() >= 5)
        # Normalize: 5 weekdays vs 2 weekend days
        weekday_rate = weekday_count / 5
        weekend_rate = weekend_count / 2
        return weekday_rate / max(weekend_rate, 0.1)

    def _empty_profile(self, equipment_id: str, circuit_name: str) -> TemporalProfile:
        return TemporalProfile(
            equipment_id=equipment_id,
            circuit_name=circuit_name,
            total_sessions=0,
            total_hours_on=0,
            duty_cycle_overall=0,
            median_session_min=0,
            avg_session_min=0,
            short_sessions=0,
            medium_sessions=0,
            long_sessions=0,
            has_cycling=False,
            cycle_pattern=None,
            hourly_activity=[0.0] * 24,
            peak_hours=[],
            weekday_vs_weekend=1.0,
        )
