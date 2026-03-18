"""Anomaly detection — finds unusual energy usage patterns across circuits.

Designed to be lightweight and cacheable. Results are cached for 5 minutes
to avoid recomputing on every dashboard refresh (every 30 seconds).
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from span_nilm.collector.sources.tempiq_source import TempIQSource

logger = logging.getLogger("span_nilm.profiler.anomaly_detector")


@dataclass
class Anomaly:
    circuit_name: str
    anomaly_type: str  # 'high_energy', 'extended_run', 'baseline_shift', 'missing_device', 'cost_spike'
    severity: str  # 'info', 'warning', 'alert'
    title: str
    description: str
    value: float
    expected: float
    timestamp: str  # ISO format


# Module-level cache
_cache: dict = {"anomalies": [], "timestamp": 0.0}
CACHE_TTL_SECONDS = 300  # 5 minutes


class AnomalyDetector:
    """Detects unusual energy usage patterns across circuits."""

    def __init__(self, electricity_rate: float = 0.14):
        self.electricity_rate = electricity_rate

    def detect(self, source: TempIQSource, days_history: int = 30) -> list[Anomaly]:
        """Run anomaly detection. Returns list of anomalies sorted by severity.

        Uses cached results if less than 5 minutes old.
        """
        global _cache
        now = time.time()
        if now - _cache["timestamp"] < CACHE_TTL_SECONDS and _cache["anomalies"]:
            logger.debug("Returning cached anomalies (%d items)", len(_cache["anomalies"]))
            return _cache["anomalies"]

        try:
            anomalies = self._detect_all(source, days_history)
        except Exception as e:
            logger.error("Anomaly detection failed: %s", e)
            anomalies = []

        # Sort by severity: alert > warning > info
        severity_order = {"alert": 0, "warning": 1, "info": 2}
        anomalies.sort(key=lambda a: (severity_order.get(a.severity, 3), a.circuit_name))

        _cache["anomalies"] = anomalies
        _cache["timestamp"] = now
        logger.info("Detected %d anomalies", len(anomalies))
        return anomalies

    def _detect_all(self, source: TempIQSource, days_history: int) -> list[Anomaly]:
        """Run all anomaly detection checks."""
        now = datetime.now(timezone.utc)
        history_start = now - timedelta(days=days_history)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        # Fetch the data we need — single query for full history
        agg_full = source.get_aggregated_power(history_start, now)
        if agg_full.empty:
            return []

        # Ensure timestamps are datetime
        agg_full["timestamp"] = pd.to_datetime(agg_full["timestamp"], utc=True)

        anomalies: list[Anomaly] = []

        # Split data for different checks
        agg_today = agg_full[agg_full["timestamp"] >= today_start]
        agg_this_week = agg_full[agg_full["timestamp"] >= week_ago]
        agg_last_week = agg_full[(agg_full["timestamp"] >= two_weeks_ago) & (agg_full["timestamp"] < week_ago)]

        # 1. Unusual daily energy
        anomalies.extend(self._check_high_energy(agg_full, agg_today, now))

        # 2. Extended run detection
        anomalies.extend(self._check_extended_runs(agg_full, now))

        # 3. Baseline shift
        anomalies.extend(self._check_baseline_shift(agg_this_week, agg_last_week, now))

        # 4. Missing expected device
        anomalies.extend(self._check_missing_devices(agg_full, now))

        # 5. Cost spike
        anomalies.extend(self._check_cost_spike(agg_full, agg_today, now, days_history))

        return anomalies

    def _check_high_energy(
        self, agg_full: pd.DataFrame, agg_today: pd.DataFrame, now: datetime
    ) -> list[Anomaly]:
        """Check if today's energy for any circuit is >2x the 30-day median for this day-of-week."""
        anomalies = []
        today_dow = now.weekday()
        ts_str = now.isoformat()

        # Compute daily energy per circuit from history, grouped by day-of-week
        agg_full = agg_full.copy()
        agg_full["date"] = agg_full["timestamp"].dt.date
        agg_full["dow"] = agg_full["timestamp"].dt.weekday

        # Daily energy per circuit (power_w * 10min / 60 / 1000 = kWh per bucket)
        daily_energy = (
            agg_full.groupby(["circuit_id", "circuit_name", "date", "dow"])["power_w"]
            .sum()
            .reset_index()
        )
        daily_energy["energy_kwh"] = daily_energy["power_w"] * (10.0 / 60.0) / 1000.0

        # Median energy on same day-of-week, per circuit
        same_dow = daily_energy[daily_energy["dow"] == today_dow]
        medians = same_dow.groupby("circuit_id")["energy_kwh"].median()

        # Today's energy per circuit
        if agg_today.empty:
            return anomalies

        today_energy = {}
        today_names = {}
        for cid, group in agg_today.groupby("circuit_id"):
            today_energy[cid] = float(group["power_w"].sum()) * (10.0 / 60.0) / 1000.0
            today_names[cid] = group["circuit_name"].iloc[0]

        for cid, energy_today in today_energy.items():
            median = medians.get(cid, 0)
            if median > 0.1 and energy_today > 2 * median:
                ratio = energy_today / median
                severity = "alert" if ratio > 4 else "warning" if ratio > 3 else "info"
                anomalies.append(Anomaly(
                    circuit_name=today_names.get(cid, str(cid)),
                    anomaly_type="high_energy",
                    severity=severity,
                    title=f"Unusually high energy usage",
                    description=(
                        f"{today_names.get(cid, str(cid))} has used {energy_today:.1f} kWh today, "
                        f"which is {ratio:.1f}x the typical {median:.1f} kWh for this day of the week."
                    ),
                    value=round(energy_today, 2),
                    expected=round(median, 2),
                    timestamp=ts_str,
                ))

        return anomalies

    def _check_extended_runs(self, agg_full: pd.DataFrame, now: datetime) -> list[Anomaly]:
        """Check if any circuit has been continuously ON for >3x its typical session duration."""
        anomalies = []
        ts_str = now.isoformat()

        for cid, group in agg_full.groupby("circuit_id"):
            group = group.sort_values("timestamp")
            circuit_name = group["circuit_name"].iloc[0]
            powers = group["power_w"].values
            timestamps = group["timestamp"].values

            # Determine the always-on baseline (10th percentile)
            baseline = float(np.percentile(powers, 10))
            active_threshold = max(baseline + 30, 20)  # at least 30W above baseline or 20W

            # Find ON sessions: consecutive readings above threshold
            is_on = powers > active_threshold
            session_durations_min = []
            current_start = None

            for i in range(len(is_on)):
                if is_on[i] and current_start is None:
                    current_start = i
                elif not is_on[i] and current_start is not None:
                    duration = (timestamps[i] - timestamps[current_start]) / np.timedelta64(1, "m")
                    session_durations_min.append(float(duration))
                    current_start = None

            if not session_durations_min or len(session_durations_min) < 3:
                continue

            typical_duration = float(np.median(session_durations_min))
            if typical_duration < 10:  # ignore very short sessions
                continue

            # Check if currently in an extended run
            if current_start is not None:
                current_duration = (timestamps[-1] - timestamps[current_start]) / np.timedelta64(1, "m")
                current_duration = float(current_duration)
                if current_duration > 3 * typical_duration and current_duration > 60:
                    ratio = current_duration / typical_duration
                    severity = "alert" if ratio > 6 else "warning"
                    anomalies.append(Anomaly(
                        circuit_name=circuit_name,
                        anomaly_type="extended_run",
                        severity=severity,
                        title=f"Extended run detected",
                        description=(
                            f"{circuit_name} has been running continuously for "
                            f"{current_duration:.0f} min, which is {ratio:.1f}x the typical "
                            f"{typical_duration:.0f} min session."
                        ),
                        value=round(current_duration, 1),
                        expected=round(typical_duration, 1),
                        timestamp=ts_str,
                    ))

        return anomalies

    def _check_baseline_shift(
        self, agg_this_week: pd.DataFrame, agg_last_week: pd.DataFrame, now: datetime
    ) -> list[Anomaly]:
        """Check if always-on power for any circuit increased by >50W compared to last week."""
        anomalies = []
        ts_str = now.isoformat()

        if agg_this_week.empty or agg_last_week.empty:
            return anomalies

        # 10th percentile per circuit for each week
        this_week_baselines = {}
        this_week_names = {}
        for cid, group in agg_this_week.groupby("circuit_id"):
            this_week_baselines[cid] = float(np.percentile(group["power_w"].values, 10))
            this_week_names[cid] = group["circuit_name"].iloc[0]

        last_week_baselines = {}
        for cid, group in agg_last_week.groupby("circuit_id"):
            last_week_baselines[cid] = float(np.percentile(group["power_w"].values, 10))

        for cid in this_week_baselines:
            current = this_week_baselines[cid]
            previous = last_week_baselines.get(cid, 0)
            increase = current - previous

            if increase > 50:
                severity = "alert" if increase > 200 else "warning" if increase > 100 else "info"
                anomalies.append(Anomaly(
                    circuit_name=this_week_names.get(cid, str(cid)),
                    anomaly_type="baseline_shift",
                    severity=severity,
                    title=f"Baseline power increased",
                    description=(
                        f"{this_week_names.get(cid, str(cid))} always-on power increased by "
                        f"{increase:.0f}W (from {previous:.0f}W to {current:.0f}W) compared to last week."
                    ),
                    value=round(current, 1),
                    expected=round(previous, 1),
                    timestamp=ts_str,
                ))

        return anomalies

    def _check_missing_devices(self, agg_full: pd.DataFrame, now: datetime) -> list[Anomaly]:
        """Check if a regularly-cycling device hasn't activated in >48 hours."""
        anomalies = []
        ts_str = now.isoformat()
        cutoff = now - timedelta(hours=48)

        for cid, group in agg_full.groupby("circuit_id"):
            group = group.sort_values("timestamp")
            circuit_name = group["circuit_name"].iloc[0]
            powers = group["power_w"].values
            timestamps = group["timestamp"].values

            baseline = float(np.percentile(powers, 10))
            active_threshold = max(baseline + 30, 20)

            # Find ON transitions
            is_on = powers > active_threshold
            on_times = []
            for i in range(1, len(is_on)):
                if is_on[i] and not is_on[i - 1]:
                    on_times.append(timestamps[i])

            if len(on_times) < 5:
                continue  # not a regularly cycling device

            # Check if this device cycles at least once per day on average
            total_span_days = (timestamps[-1] - timestamps[0]) / np.timedelta64(1, "D")
            if total_span_days < 1:
                continue
            cycles_per_day = len(on_times) / float(total_span_days)

            if cycles_per_day < 1:
                continue  # not daily cycling

            # Check last activation time
            last_on = pd.Timestamp(on_times[-1], tz="UTC")
            if last_on < cutoff:
                hours_since = (now - last_on).total_seconds() / 3600
                anomalies.append(Anomaly(
                    circuit_name=circuit_name,
                    anomaly_type="missing_device",
                    severity="warning",
                    title=f"Expected device inactive",
                    description=(
                        f"{circuit_name} normally cycles {cycles_per_day:.1f}x/day but "
                        f"hasn't activated in {hours_since:.0f} hours."
                    ),
                    value=round(hours_since, 1),
                    expected=round(24 / cycles_per_day, 1),
                    timestamp=ts_str,
                ))

        return anomalies

    def _check_cost_spike(
        self, agg_full: pd.DataFrame, agg_today: pd.DataFrame, now: datetime, days_history: int
    ) -> list[Anomaly]:
        """Check if today's projected cost exceeds the 30-day daily average by >50%."""
        anomalies = []
        ts_str = now.isoformat()

        if agg_today.empty:
            return anomalies

        # Total energy today across all circuits
        today_energy_kwh = float(agg_today["power_w"].sum()) * (10.0 / 60.0) / 1000.0
        hours_elapsed = max(now.hour + now.minute / 60, 1)
        projected_today = today_energy_kwh * (24 / hours_elapsed)
        projected_cost = projected_today * self.electricity_rate

        # Average daily energy from history
        agg_full = agg_full.copy()
        agg_full["date"] = agg_full["timestamp"].dt.date
        daily_totals = agg_full.groupby("date")["power_w"].sum() * (10.0 / 60.0) / 1000.0
        if len(daily_totals) < 3:
            return anomalies

        avg_daily_kwh = float(daily_totals.median())
        avg_daily_cost = avg_daily_kwh * self.electricity_rate

        if avg_daily_cost > 0 and projected_cost > avg_daily_cost * 1.5:
            ratio = projected_cost / avg_daily_cost
            severity = "alert" if ratio > 2.5 else "warning" if ratio > 2 else "info"
            anomalies.append(Anomaly(
                circuit_name="Whole Home",
                anomaly_type="cost_spike",
                severity=severity,
                title=f"Projected daily cost is elevated",
                description=(
                    f"Today's projected cost is ${projected_cost:.2f}, "
                    f"which is {ratio:.1f}x the typical ${avg_daily_cost:.2f}/day."
                ),
                value=round(projected_cost, 2),
                expected=round(avg_daily_cost, 2),
                timestamp=ts_str,
            ))

        return anomalies
