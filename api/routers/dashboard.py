"""Dashboard endpoint — returns everything the frontend needs in one call."""

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Query

from api.deps import get_tempiq_source
from api.models import CircuitPower, CorrelationInfo, DashboardResponse, DetectedDevice, TemporalInfo, TimelineBucket

logger = logging.getLogger("span_nilm.api.dashboard")
router = APIRouter(prefix="/api")

DEFAULT_ELECTRICITY_RATE = 0.14  # $/kWh
# Eastern time offset (UTC-5 EST, UTC-4 EDT). Using -4 for EDT (March = DST).
EASTERN_OFFSET = timedelta(hours=-4)


def _get_spannilm_db():
    return psycopg2.connect(os.environ["SPANNILM_DATABASE_URL"])


def _load_electricity_rate() -> float:
    """Load electricity rate from settings table, falling back to default."""
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


def _load_circuit_configs() -> dict[str, dict]:
    """Load circuit configs from SpanNILM DB, keyed by tempiq_equipment_id."""
    conn = _get_spannilm_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM circuits")
            return {row["tempiq_equipment_id"]: dict(row) for row in cur.fetchall()}
    finally:
        conn.close()


@router.post("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    electricity_rate: float | None = Query(default=None, ge=0),
):
    """Return comprehensive dashboard data in one call."""
    # Use saved setting if no explicit rate provided
    if electricity_rate is None:
        electricity_rate = _load_electricity_rate()
    source = get_tempiq_source()
    now = datetime.now(timezone.utc)
    # Use Eastern time for "today" and "this month" boundaries
    eastern = timezone(EASTERN_OFFSET)
    now_eastern = now.astimezone(eastern)
    today_start = now_eastern.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    month_start = now_eastern.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    yesterday = now - timedelta(hours=24)

    # Load circuit configs from SpanNILM DB
    configs = _load_circuit_configs()

    # 1. Current power per circuit
    current_power_list = source.get_current_power()
    current_power_map: dict[str, dict] = {}
    for cp in current_power_list:
        current_power_map[cp["equipment_id"]] = cp

    # 2. Energy totals — today and this month
    energy_today_rows = source.get_energy_totals(today_start, now)
    energy_month_rows = source.get_energy_totals(month_start, now)

    energy_today_map: dict[str, float] = {}
    circuit_names: dict[str, str] = {}
    for row in energy_today_rows:
        energy_today_map[row["equipment_id"]] = row["energy_kwh"]
        circuit_names[row["equipment_id"]] = row["circuit_name"]

    energy_month_map: dict[str, float] = {}
    for row in energy_month_rows:
        energy_month_map[row["equipment_id"]] = row["energy_kwh"]
        if row["equipment_id"] not in circuit_names:
            circuit_names[row["equipment_id"]] = row["circuit_name"]

    # 3. Always-on detection (10th percentile over 24h)
    always_on_rows = source.get_always_on(yesterday, now)
    always_on_map: dict[str, float] = {}
    for row in always_on_rows:
        always_on_map[row["equipment_id"]] = max(0, row["always_on_w"] or 0)
        if row["equipment_id"] not in circuit_names:
            circuit_names[row["equipment_id"]] = row["circuit_name"]

    # Also add circuit names from current power
    for cp in current_power_list:
        if cp["equipment_id"] not in circuit_names:
            circuit_names[cp["equipment_id"]] = cp["circuit_name"]

    # 4. Load circuit profiles for detected devices + temporal + correlations
    profile_devices: dict[str, list[DetectedDevice]] = {}
    profile_temporal: dict[str, TemporalInfo] = {}
    profile_correlations: dict[str, list[CorrelationInfo]] = {}
    try:
        from span_nilm.profiler.circuit_profiler import CircuitProfiler
        profile_rows = CircuitProfiler.load_profiles()
        for row in profile_rows:
            eid = row["equipment_id"]
            # Skip device detection for dedicated circuits — we already know what they are
            is_ded = row.get("is_dedicated", False)

            if not is_ded:
                devices = []
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

            # Temporal info
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

            # Correlations
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

        circuits.append(CircuitPower(
            equipment_id=equip_id,
            name=name,
            power_w=round(power_w, 1),
            is_dedicated=is_dedicated,
            device_type=device_type,
            energy_today_kwh=round(e_today, 3),
            energy_month_kwh=round(e_month, 3),
            cost_today=round(e_today * electricity_rate, 2),
            cost_month=round(e_month * electricity_rate, 2),
            always_on_w=round(ao_w, 1),
            detected_devices=profile_devices.get(equip_id, []),
            temporal=profile_temporal.get(equip_id),
            correlations=profile_correlations.get(equip_id, []),
        ))

    # Sort by current power descending
    circuits.sort(key=lambda c: c.power_w, reverse=True)

    # 5. Stacked power timeline (24h, 5-min buckets)
    timeline_rows = source.get_power_timeline(yesterday, now, bucket_minutes=60)

    # Group by bucket timestamp
    buckets: dict[str, dict[str, float]] = defaultdict(dict)
    for row in timeline_rows:
        ts_str = row["bucket"].isoformat() if hasattr(row["bucket"], "isoformat") else str(row["bucket"])
        buckets[ts_str][row["circuit_name"]] = round(row["avg_power_w"] or 0, 1)

    timeline: list[TimelineBucket] = []
    for ts_str in sorted(buckets.keys()):
        circuit_powers = buckets[ts_str]
        total = sum(circuit_powers.values())
        timeline.append(TimelineBucket(
            timestamp=ts_str,
            total_w=round(total, 1),
            circuits=circuit_powers,
        ))

    # 6. Aggregate totals
    total_power_w = sum(c.power_w for c in circuits)
    total_always_on_w = sum(c.always_on_w for c in circuits)
    total_energy_today = sum(c.energy_today_kwh for c in circuits)
    total_energy_month = sum(c.energy_month_kwh for c in circuits)

    return DashboardResponse(
        total_power_w=round(total_power_w, 1),
        always_on_w=round(total_always_on_w, 1),
        active_power_w=round(max(0, total_power_w - total_always_on_w), 1),
        circuits=circuits,
        timeline=timeline,
        total_energy_today_kwh=round(total_energy_today, 3),
        total_cost_today=round(total_energy_today * electricity_rate, 2),
        total_energy_month_kwh=round(total_energy_month, 3),
        total_cost_month=round(total_energy_month * electricity_rate, 2),
        electricity_rate=electricity_rate,
    )
