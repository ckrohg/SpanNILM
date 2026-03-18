"""Dashboard endpoint — returns everything the frontend needs in one call."""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Query

from api.deps import get_tempiq_source
from api.models import (
    Anomaly,
    BillProjection,
    CircuitPower,
    CorrelationInfo,
    CostAttribution,
    DashboardResponse,
    DetectedDevice,
    TemporalInfo,
    TimelineBucket,
    TOUPeriod,
    TOUSchedule,
    UsageTrend,
)

logger = logging.getLogger("span_nilm.api.dashboard")
router = APIRouter(prefix="/api")

DEFAULT_ELECTRICITY_RATE = 0.14  # $/kWh
EASTERN_OFFSET = timedelta(hours=-4)

PERIOD_LABELS = {
    "today": "Today",
    "yesterday": "Yesterday",
    "7d": "Last 7 Days",
    "30d": "Last 30 Days",
    "month": "This Month",
    "year": "This Year",
    "365d": "Last 365 Days",
}


def _get_spannilm_db():
    return psycopg2.connect(os.environ["SPANNILM_DATABASE_URL"])


def _load_electricity_rate() -> float:
    try:
        conn = _get_spannilm_db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM settings WHERE key = 'electricity_rate'")
                row = cur.fetchone()
                if row:
                    return float(row[0])
        finally:
            conn.close()
    except Exception as e:
        logger.debug("Could not load electricity_rate setting: %s", e)
    return DEFAULT_ELECTRICITY_RATE


def _load_tou_schedule() -> TOUSchedule:
    """Load TOU schedule from settings table."""
    try:
        conn = _get_spannilm_db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM settings WHERE key = 'tou_schedule'")
                row = cur.fetchone()
                if row:
                    data = json.loads(row[0])
                    return TOUSchedule(**data)
        finally:
            conn.close()
    except Exception as e:
        logger.debug("Could not load tou_schedule setting: %s", e)
    return TOUSchedule(enabled=False)


def _get_tou_rate(hour: int, is_weekday: bool, tou: TOUSchedule, flat_rate: float) -> tuple[float, str]:
    """Return (rate, period_name) for a given hour and day type."""
    if not tou.enabled:
        return flat_rate, "flat"

    if tou.peak and hour >= tou.peak.start and hour < tou.peak.end:
        if not tou.peak.weekdays_only or is_weekday:
            return tou.peak.rate, "peak"

    if tou.off_peak:
        # Off-peak wraps around midnight (e.g., 21:00 - 09:00)
        if tou.off_peak.start > tou.off_peak.end:
            if hour >= tou.off_peak.start or hour < tou.off_peak.end:
                return tou.off_peak.rate, "off_peak"
        else:
            if hour >= tou.off_peak.start and hour < tou.off_peak.end:
                return tou.off_peak.rate, "off_peak"

    if tou.mid_peak and hour >= tou.mid_peak.start and hour < tou.mid_peak.end:
        return tou.mid_peak.rate, "mid_peak"

    return flat_rate, "flat"


def _compute_tou_cost(power_w: float, timestamp: datetime, bucket_minutes: float,
                      tou: TOUSchedule, flat_rate: float) -> float:
    """Compute cost for a single bucket using TOU rates."""
    if not tou.enabled:
        return power_w * (bucket_minutes / 60) / 1000 * flat_rate
    hour = timestamp.hour
    is_weekday = timestamp.weekday() < 5
    rate, _ = _get_tou_rate(hour, is_weekday, tou, flat_rate)
    return power_w * (bucket_minutes / 60) / 1000 * rate


def _compute_period_range(period: str, now_eastern: datetime, eastern) -> tuple[datetime, datetime, str]:
    """Compute start/end UTC datetimes for the given period. Returns (start, end, label)."""
    now_utc = now_eastern.astimezone(timezone.utc)
    label = PERIOD_LABELS.get(period, "Today")

    if period == "today":
        start = now_eastern.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        return start, now_utc, label
    elif period == "yesterday":
        today_start = now_eastern.replace(hour=0, minute=0, second=0, microsecond=0)
        start = (today_start - timedelta(days=1)).astimezone(timezone.utc)
        end = today_start.astimezone(timezone.utc)
        return start, end, label
    elif period == "7d":
        start = (now_utc - timedelta(days=7))
        return start, now_utc, label
    elif period == "30d":
        start = (now_utc - timedelta(days=30))
        return start, now_utc, label
    elif period == "month":
        start = now_eastern.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        return start, now_utc, label
    elif period == "year":
        start = now_eastern.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        return start, now_utc, label
    elif period == "365d":
        start = (now_utc - timedelta(days=365))
        return start, now_utc, label
    else:
        # Default to today
        start = now_eastern.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        return start, now_utc, "Today"


def _get_bucket_minutes(period: str) -> int:
    """Return bucket size in minutes for timeline aggregation."""
    if period in ("today", "yesterday"):
        return 10
    elif period == "7d":
        return 60
    elif period in ("30d", "month"):
        return 360  # 6 hours
    elif period in ("year", "365d"):
        return 1440  # daily
    return 10


def _load_circuit_configs() -> dict[str, dict]:
    conn = _get_spannilm_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM circuits")
            return {row["tempiq_equipment_id"]: dict(row) for row in cur.fetchall()}
    finally:
        conn.close()


def _aggregate_timeline(agg_data, bucket_minutes: int) -> list[TimelineBucket]:
    """Aggregate raw 10-min data into larger buckets for the timeline."""
    import pandas as pd

    if agg_data.empty:
        return []

    if bucket_minutes <= 10:
        # Use the raw 10-min data as-is
        buckets: dict[str, dict[str, float]] = defaultdict(dict)
        for _, row in agg_data.iterrows():
            ts_str = row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"])
            buckets[ts_str][row["circuit_name"]] = round(float(row["power_w"]), 1)

        timeline = []
        for ts_str in sorted(buckets.keys()):
            circuit_powers = buckets[ts_str]
            total = sum(circuit_powers.values())
            timeline.append(TimelineBucket(
                timestamp=ts_str,
                total_w=round(total, 1),
                circuits=circuit_powers,
            ))
        return timeline

    # For larger buckets, aggregate by flooring timestamps
    df = agg_data.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    freq = f"{bucket_minutes}min"
    df["bucket"] = df["timestamp"].dt.floor(freq)

    grouped = df.groupby(["bucket", "circuit_name"])["power_w"].mean().reset_index()

    buckets_map: dict[str, dict[str, float]] = defaultdict(dict)
    for _, row in grouped.iterrows():
        ts_str = row["bucket"].isoformat()
        buckets_map[ts_str][row["circuit_name"]] = round(float(row["power_w"]), 1)

    timeline = []
    for ts_str in sorted(buckets_map.keys()):
        circuit_powers = buckets_map[ts_str]
        total = sum(circuit_powers.values())
        timeline.append(TimelineBucket(
            timestamp=ts_str,
            total_w=round(total, 1),
            circuits=circuit_powers,
        ))
    return timeline


@router.post("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    electricity_rate: float | None = Query(default=None, ge=0),
    period: str = Query(default="today", description="today|yesterday|7d|30d|month|year|365d"),
):
    """Return comprehensive dashboard data using 10-min aggregated power data."""
    if electricity_rate is None:
        electricity_rate = _load_electricity_rate()

    tou = _load_tou_schedule()

    source = get_tempiq_source()
    now = datetime.now(timezone.utc)
    eastern = timezone(EASTERN_OFFSET)
    now_eastern = now.astimezone(eastern)

    # Compute the time range for the selected period
    range_start, range_end, period_label = _compute_period_range(period, now_eastern, eastern)
    bucket_minutes = _get_bucket_minutes(period)

    # We always need "today" and "month" for the secondary display + bill projection
    today_start = now_eastern.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    month_start = now_eastern.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    configs = _load_circuit_configs()

    import pandas as pd
    # Fetch data for the requested period
    agg_period = source.get_aggregated_power(range_start, range_end)

    # Also fetch today and month if they differ from the period
    agg_today = None
    agg_month = None
    if period != "today":
        agg_today = source.get_aggregated_power(today_start, now)
    else:
        agg_today = agg_period

    if period != "month":
        agg_month = source.get_aggregated_power(month_start, now)
    else:
        agg_month = agg_period

    # For current power, use last 24h data
    yesterday = now - timedelta(hours=24)
    if period == "today":
        # agg_period covers today; for current power we need recent data
        agg_recent = agg_period
    else:
        agg_recent = source.get_aggregated_power(yesterday, now)

    # 1. Current power: latest reading per circuit
    current_power_map: dict[str, dict] = {}
    circuit_names: dict[str, str] = {}
    if not agg_recent.empty:
        latest = agg_recent.sort_values("timestamp").groupby("circuit_id").last().reset_index()
        for _, row in latest.iterrows():
            cid = str(row["circuit_id"])
            current_power_map[cid] = {"power_w": round(float(row["power_w"]), 1)}
            circuit_names[cid] = row["circuit_name"]

    # 2. Energy totals for the selected period, today, and month
    energy_period_map: dict[str, float] = {}
    energy_today_map: dict[str, float] = {}
    energy_month_map: dict[str, float] = {}

    # Period energy (with TOU cost calculation)
    cost_period_map: dict[str, float] = {}
    if not agg_period.empty:
        for cid, group in agg_period.groupby("circuit_id"):
            energy_kwh = float(group["power_w"].sum()) * (10.0 / 60.0) / 1000.0
            energy_period_map[str(cid)] = energy_kwh
            if str(cid) not in circuit_names:
                circuit_names[str(cid)] = group["circuit_name"].iloc[0]

            # TOU cost calculation per bucket
            if tou.enabled:
                total_cost = 0.0
                for _, brow in group.iterrows():
                    ts = pd.to_datetime(brow["timestamp"], utc=True).to_pydatetime()
                    ts_eastern = ts.astimezone(eastern)
                    total_cost += _compute_tou_cost(float(brow["power_w"]), ts_eastern, 10.0, tou, electricity_rate)
                cost_period_map[str(cid)] = total_cost
            else:
                cost_period_map[str(cid)] = energy_kwh * electricity_rate

    # Today energy
    cost_today_map: dict[str, float] = {}
    if not agg_today.empty:
        for cid, group in agg_today.groupby("circuit_id"):
            energy_kwh = float(group["power_w"].sum()) * (10.0 / 60.0) / 1000.0
            energy_today_map[str(cid)] = energy_kwh
            if str(cid) not in circuit_names:
                circuit_names[str(cid)] = group["circuit_name"].iloc[0]

            if tou.enabled:
                total_cost = 0.0
                for _, brow in group.iterrows():
                    ts = pd.to_datetime(brow["timestamp"], utc=True).to_pydatetime()
                    ts_eastern = ts.astimezone(eastern)
                    total_cost += _compute_tou_cost(float(brow["power_w"]), ts_eastern, 10.0, tou, electricity_rate)
                cost_today_map[str(cid)] = total_cost
            else:
                cost_today_map[str(cid)] = energy_kwh * electricity_rate

    # Month energy
    cost_month_map: dict[str, float] = {}
    if not agg_month.empty:
        for cid, group in agg_month.groupby("circuit_id"):
            energy_kwh = float(group["power_w"].sum()) * (10.0 / 60.0) / 1000.0
            energy_month_map[str(cid)] = energy_kwh
            if str(cid) not in circuit_names:
                circuit_names[str(cid)] = group["circuit_name"].iloc[0]

            if tou.enabled:
                total_cost = 0.0
                for _, brow in group.iterrows():
                    ts = pd.to_datetime(brow["timestamp"], utc=True).to_pydatetime()
                    ts_eastern = ts.astimezone(eastern)
                    total_cost += _compute_tou_cost(float(brow["power_w"]), ts_eastern, 10.0, tou, electricity_rate)
                cost_month_map[str(cid)] = total_cost
            else:
                cost_month_map[str(cid)] = energy_kwh * electricity_rate

    # 3. Always-on: 10th percentile of power per circuit over 24h (always use recent data)
    always_on_map: dict[str, float] = {}
    if not agg_recent.empty:
        for cid, group in agg_recent.groupby("circuit_id"):
            p10 = float(np.percentile(group["power_w"].values, 10))
            always_on_map[str(cid)] = max(0, p10)

    # 4. Load circuit profiles for detected devices + temporal + correlations
    # Also load device labels to get user-confirmed names and suppressed devices
    device_labels: dict[str, dict] = {}  # key: "equip_id-cluster_id" -> {name, source}
    suppressed_ai_names: set[str] = set()  # AI-generated names that were suppressed on any circuit
    try:
        conn = _get_spannilm_db()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT equipment_id, cluster_id, name, source FROM device_labels")
                for r in cur.fetchall():
                    key = f"{r['equipment_id']}-{r['cluster_id']}"
                    device_labels[key] = {"name": r["name"], "source": r["source"]}

                    # Track AI-generated names that were suppressed
                    if "[SUPPRESSED]" in r["name"] or r["name"] == "Not a real device":
                        # Look up the original AI name from circuit_profiles
                        cur.execute(
                            "SELECT shape_devices FROM circuit_profiles WHERE equipment_id = %s",
                            (r["equipment_id"],),
                        )
                        prow = cur.fetchone()
                        if prow and prow.get("shape_devices"):
                            sd_list = prow["shape_devices"]
                            if isinstance(sd_list, str):
                                sd_list = json.loads(sd_list)
                            for sd in sd_list:
                                if sd.get("cluster_id") == r["cluster_id"]:
                                    orig_name = sd.get("name", "")
                                    if orig_name:
                                        suppressed_ai_names.add(orig_name)
                                    break
        finally:
            conn.close()
    except Exception:
        pass  # table may not exist yet

    profile_devices: dict[str, list[DetectedDevice]] = {}
    profile_temporal: dict[str, TemporalInfo] = {}
    profile_correlations: dict[str, list[CorrelationInfo]] = {}
    try:
        from span_nilm.profiler.circuit_profiler import CircuitProfiler
        profile_rows = CircuitProfiler.load_profiles()
        for row in profile_rows:
            eid = row["equipment_id"]
            is_ded = row.get("is_dedicated", False)

            if not is_ded:
                devices = []
                shape_devs = row.get("shape_devices") or []
                if shape_devs:
                    for idx, sd in enumerate(shape_devs):
                        cluster_id = sd.get("cluster_id", idx)
                        label_key = f"{eid}-{cluster_id}"
                        label = device_labels.get(label_key)

                        # Skip suppressed devices
                        if label and "[SUPPRESSED]" in label["name"]:
                            continue
                        # Skip "Not a real device" labels
                        if label and label["name"] == "Not a real device":
                            continue

                        # Use user-confirmed name if available
                        dev_name = label["name"] if label else sd["name"]
                        is_user_confirmed = label is not None and label["source"] in ("user", "ai_confirmed")

                        # Check if this AI-generated name was suppressed on another circuit
                        ai_name = sd["name"]
                        is_suppressed_elsewhere = (
                            ai_name in suppressed_ai_names
                            and not is_user_confirmed
                        )

                        spd = sd.get("sessions_per_day", 0)
                        avg_dur = sd.get("avg_duration_min", 0)
                        pct = spd * avg_dur / 1440 * 100
                        devices.append(DetectedDevice(
                            name=dev_name,
                            power_w=sd.get("avg_power_w", 0),
                            confidence=sd.get("confidence", 0),
                            pct_of_time=round(pct, 2),
                            template_curve=sd.get("template_curve"),
                            session_count=sd.get("session_count", 0),
                            avg_duration_min=sd.get("avg_duration_min", 0),
                            is_cycling=sd.get("is_cycling", False),
                            num_phases=sd.get("num_phases", 1),
                            energy_per_session_wh=sd.get("energy_per_session_wh", 0),
                            suppressed_on_other_circuit=is_suppressed_elsewhere,
                            user_confirmed=is_user_confirmed,
                        ))
                else:
                    for s in (row.get("states") or []):
                        if s.get("device_name"):
                            devices.append(DetectedDevice(
                                name=s["device_name"],
                                power_w=s["center_w"],
                                confidence=s.get("confidence", 0),
                                pct_of_time=s.get("pct_of_time", 0),
                            ))
                if devices:
                    profile_devices[eid] = devices

            t = row.get("temporal") or {}
            if t:
                cp = t.get("cycle_pattern", {})
                profile_temporal[eid] = TemporalInfo(
                    total_sessions=t.get("total_sessions", 0),
                    total_hours_on=t.get("total_hours_on", 0),
                    duty_cycle=t.get("duty_cycle_overall", 0),
                    has_cycling=t.get("has_cycling", False),
                    cycle_period_min=cp.get("median_period_min") if cp else None,
                    cycle_on_min=cp.get("median_on_min") if cp else None,
                    cycle_regularity=cp.get("regularity") if cp else None,
                    peak_hours=t.get("peak_hours", []),
                )

            corrs = row.get("correlations") or []
            if corrs:
                profile_correlations[eid] = [
                    CorrelationInfo(name=c["name"], score=c["score"])
                    for c in corrs[:3]
                ]
    except Exception as e:
        logger.debug("No circuit profiles available yet: %s", e)

    # 5. Build circuit list
    all_equipment_ids = set(circuit_names.keys())
    circuits: list[CircuitPower] = []

    for equip_id in sorted(all_equipment_ids):
        config = configs.get(equip_id, {})
        name = config.get("user_label") or circuit_names.get(equip_id, equip_id)
        is_dedicated = config.get("is_dedicated", False)
        device_type = config.get("dedicated_device_type")
        power_w = current_power_map.get(equip_id, {}).get("power_w", 0.0)
        e_today = energy_today_map.get(equip_id, 0.0)
        e_month = energy_month_map.get(equip_id, 0.0)
        ao_w = always_on_map.get(equip_id, 0.0)
        c_today = cost_today_map.get(equip_id, e_today * electricity_rate)
        c_month = cost_month_map.get(equip_id, e_month * electricity_rate)

        circuits.append(CircuitPower(
            equipment_id=equip_id,
            name=name,
            power_w=round(power_w, 1),
            is_dedicated=is_dedicated,
            device_type=device_type,
            energy_today_kwh=round(e_today, 2),
            energy_month_kwh=round(e_month, 2),
            cost_today=round(c_today, 2),
            cost_month=round(c_month, 2),
            always_on_w=round(ao_w, 1),
            detected_devices=profile_devices.get(equip_id, []),
            temporal=profile_temporal.get(equip_id),
            correlations=profile_correlations.get(equip_id, []),
        ))

    circuits.sort(key=lambda c: c.power_w, reverse=True)

    # 6. Timeline from period data, aggregated to appropriate bucket size
    timeline = _aggregate_timeline(agg_period, bucket_minutes)

    # 7. Totals
    total_power_w = sum(c.power_w for c in circuits)
    total_always_on_w = sum(c.always_on_w for c in circuits)
    total_energy_today = sum(c.energy_today_kwh for c in circuits)
    total_energy_month = sum(c.energy_month_kwh for c in circuits)
    total_cost_today = sum(cost_today_map.get(c.equipment_id, c.energy_today_kwh * electricity_rate) for c in circuits)
    total_cost_month = sum(cost_month_map.get(c.equipment_id, c.energy_month_kwh * electricity_rate) for c in circuits)

    # 8. Bill projection
    import calendar
    days_elapsed = now_eastern.day
    days_in_month = calendar.monthrange(now_eastern.year, now_eastern.month)[1]
    days_remaining = days_in_month - days_elapsed

    bill_projection = None
    if days_elapsed > 0 and total_energy_month > 0:
        daily_avg_kwh = total_energy_month / days_elapsed
        projected_kwh = daily_avg_kwh * days_in_month
        projected_cost = projected_kwh * electricity_rate
        if tou.enabled and total_energy_month > 0:
            # Scale TOU cost to projected full month
            avg_tou_rate = total_cost_month / total_energy_month if total_energy_month > 0 else electricity_rate
            projected_cost = projected_kwh * avg_tou_rate
        bill_projection = BillProjection(
            projected_monthly_kwh=round(projected_kwh, 1),
            projected_monthly_cost=round(projected_cost, 2),
            days_elapsed=days_elapsed,
            days_remaining=days_remaining,
            daily_avg_kwh=round(daily_avg_kwh, 1),
        )

    # 9. Top cost drivers (by monthly energy)
    top_cost_drivers: list[CostAttribution] = []
    if total_energy_month > 0:
        sorted_by_energy = sorted(circuits, key=lambda c: c.energy_month_kwh, reverse=True)
        for c in sorted_by_energy[:6]:
            if c.energy_month_kwh > 0:
                top_cost_drivers.append(CostAttribution(
                    name=c.name,
                    energy_kwh=round(c.energy_month_kwh, 2),
                    cost=round(c.cost_month, 2),
                    pct_of_total=round(c.energy_month_kwh / total_energy_month * 100, 1),
                ))

    # 10. Usage trends (last 7 days vs previous 7 days)
    trends: list[UsageTrend] = []
    try:
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)
        agg_current_week = source.get_aggregated_power(week_ago, now)
        agg_prev_week = source.get_aggregated_power(two_weeks_ago, week_ago)

        current_energy: dict[str, float] = {}
        prev_energy: dict[str, float] = {}

        if not agg_current_week.empty:
            for cid, group in agg_current_week.groupby("circuit_id"):
                current_energy[str(cid)] = float(group["power_w"].sum()) * (10.0 / 60.0) / 1000.0

        if not agg_prev_week.empty:
            for cid, group in agg_prev_week.groupby("circuit_id"):
                prev_energy[str(cid)] = float(group["power_w"].sum()) * (10.0 / 60.0) / 1000.0

        all_ids = set(current_energy.keys()) | set(prev_energy.keys())
        for cid in all_ids:
            curr = current_energy.get(cid, 0)
            prev = prev_energy.get(cid, 0)
            if prev > 0.1:
                change_pct = ((curr - prev) / prev) * 100
            elif curr > 0.1:
                change_pct = 100.0
            else:
                continue

            if abs(change_pct) < 15:
                direction = "stable"
            elif change_pct > 0:
                direction = "up"
            else:
                direction = "down"

            # Only include significant changes
            if direction != "stable":
                cname = circuit_names.get(cid, cid)
                trends.append(UsageTrend(
                    circuit_name=cname,
                    current_period_kwh=round(curr, 2),
                    previous_period_kwh=round(prev, 2),
                    change_pct=round(change_pct, 1),
                    direction=direction,
                ))

        trends.sort(key=lambda t: abs(t.change_pct), reverse=True)
    except Exception as e:
        logger.debug("Could not compute usage trends: %s", e)

    # Current TOU rate info
    current_tou_rate = None
    current_tou_period_name = None
    if tou.enabled:
        hour_now = now_eastern.hour
        is_weekday_now = now_eastern.weekday() < 5
        current_tou_rate, current_tou_period_name = _get_tou_rate(hour_now, is_weekday_now, tou, electricity_rate)

    # 11. Anomaly detection (cached for 5 minutes)
    dashboard_anomalies: list[Anomaly] = []
    try:
        from span_nilm.profiler.anomaly_detector import AnomalyDetector as _AnomalyDetector
        detector = _AnomalyDetector(electricity_rate=electricity_rate)
        raw_anomalies = detector.detect(source, days_history=30)
        dashboard_anomalies = [
            Anomaly(
                circuit_name=a.circuit_name,
                anomaly_type=a.anomaly_type,
                severity=a.severity,
                title=a.title,
                description=a.description,
                value=a.value,
                expected=a.expected,
                timestamp=a.timestamp,
            )
            for a in raw_anomalies
        ]
    except Exception as e:
        logger.debug("Anomaly detection failed (non-fatal): %s", e)

    return DashboardResponse(
        total_power_w=round(total_power_w, 1),
        always_on_w=round(total_always_on_w, 1),
        active_power_w=round(max(0, total_power_w - total_always_on_w), 1),
        circuits=circuits,
        timeline=timeline,
        total_energy_today_kwh=round(total_energy_today, 2),
        total_cost_today=round(total_cost_today, 2),
        total_energy_month_kwh=round(total_energy_month, 2),
        total_cost_month=round(total_cost_month, 2),
        electricity_rate=electricity_rate,
        bill_projection=bill_projection,
        top_cost_drivers=top_cost_drivers,
        trends=trends,
        period=period,
        period_label=period_label,
        tou_schedule=tou if tou.enabled else None,
        current_tou_rate=current_tou_rate,
        current_tou_period_name=current_tou_period_name,
        anomalies=dashboard_anomalies,
    )
