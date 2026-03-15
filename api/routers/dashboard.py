"""Dashboard endpoint — returns everything the frontend needs in one call."""

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Query

from api.deps import get_tempiq_source
from api.models import CircuitPower, CorrelationInfo, DashboardResponse, DetectedDevice, TemporalInfo, TimelineBucket

logger = logging.getLogger("span_nilm.api.dashboard")
router = APIRouter(prefix="/api")

DEFAULT_ELECTRICITY_RATE = 0.14  # $/kWh
EASTERN_OFFSET = timedelta(hours=-4)


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


def _load_circuit_configs() -> dict[str, dict]:
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
    """Return comprehensive dashboard data using 10-min aggregated power data."""
    if electricity_rate is None:
        electricity_rate = _load_electricity_rate()

    source = get_tempiq_source()
    now = datetime.now(timezone.utc)
    eastern = timezone(EASTERN_OFFSET)
    now_eastern = now.astimezone(eastern)
    today_start = now_eastern.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    month_start = now_eastern.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    yesterday = now - timedelta(hours=24)

    configs = _load_circuit_configs()

    # === Use aggregated power data (10-min resolution) for everything ===
    import pandas as pd
    agg_24h = source.get_aggregated_power(yesterday, now)
    agg_today = source.get_aggregated_power(today_start, now)
    agg_month = source.get_aggregated_power(month_start, now)

    # 1. Current power: latest reading per circuit from aggregated data
    current_power_map: dict[str, dict] = {}
    circuit_names: dict[str, str] = {}
    if not agg_24h.empty:
        latest = agg_24h.sort_values("timestamp").groupby("circuit_id").last().reset_index()
        for _, row in latest.iterrows():
            cid = str(row["circuit_id"])
            current_power_map[cid] = {"power_w": round(float(row["power_w"]), 1)}
            circuit_names[cid] = row["circuit_name"]

    # 2. Energy totals from aggregated data (sum of energy_wh in each bucket)
    # The aggregated table has energy_wh per 10-min bucket - we need to query it
    energy_today_map: dict[str, float] = {}
    energy_month_map: dict[str, float] = {}

    # Use avg_power_w * 10min/60 = energy in kWh per bucket
    if not agg_today.empty:
        for cid, group in agg_today.groupby("circuit_id"):
            energy_kwh = float(group["power_w"].sum()) * (10.0 / 60.0) / 1000.0
            energy_today_map[str(cid)] = energy_kwh
            if str(cid) not in circuit_names:
                circuit_names[str(cid)] = group["circuit_name"].iloc[0]

    if not agg_month.empty:
        for cid, group in agg_month.groupby("circuit_id"):
            energy_kwh = float(group["power_w"].sum()) * (10.0 / 60.0) / 1000.0
            energy_month_map[str(cid)] = energy_kwh
            if str(cid) not in circuit_names:
                circuit_names[str(cid)] = group["circuit_name"].iloc[0]

    # 3. Always-on: 10th percentile of power per circuit over 24h
    always_on_map: dict[str, float] = {}
    if not agg_24h.empty:
        for cid, group in agg_24h.groupby("circuit_id"):
            p10 = float(np.percentile(group["power_w"].values, 10))
            always_on_map[str(cid)] = max(0, p10)

    # 4. Load circuit profiles for detected devices + temporal + correlations
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
                    for sd in shape_devs:
                        spd = sd.get("sessions_per_day", 0)
                        avg_dur = sd.get("avg_duration_min", 0)
                        pct = spd * avg_dur / 1440 * 100
                        devices.append(DetectedDevice(
                            name=sd["name"],
                            power_w=sd.get("avg_power_w", 0),
                            confidence=sd.get("confidence", 0),
                            pct_of_time=round(pct, 2),
                            template_curve=sd.get("template_curve"),
                            session_count=sd.get("session_count", 0),
                            avg_duration_min=sd.get("avg_duration_min", 0),
                            is_cycling=sd.get("is_cycling", False),
                            num_phases=sd.get("num_phases", 1),
                            energy_per_session_wh=sd.get("energy_per_session_wh", 0),
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

        circuits.append(CircuitPower(
            equipment_id=equip_id,
            name=name,
            power_w=round(power_w, 1),
            is_dedicated=is_dedicated,
            device_type=device_type,
            energy_today_kwh=round(e_today, 2),
            energy_month_kwh=round(e_month, 2),
            cost_today=round(e_today * electricity_rate, 2),
            cost_month=round(e_month * electricity_rate, 2),
            always_on_w=round(ao_w, 1),
            detected_devices=profile_devices.get(equip_id, []),
            temporal=profile_temporal.get(equip_id),
            correlations=profile_correlations.get(equip_id, []),
        ))

    circuits.sort(key=lambda c: c.power_w, reverse=True)

    # 6. Stacked timeline from aggregated data (already at 10-min resolution)
    timeline: list[TimelineBucket] = []
    if not agg_24h.empty:
        buckets: dict[str, dict[str, float]] = defaultdict(dict)
        for _, row in agg_24h.iterrows():
            ts_str = row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"])
            buckets[ts_str][row["circuit_name"]] = round(float(row["power_w"]), 1)

        for ts_str in sorted(buckets.keys()):
            circuit_powers = buckets[ts_str]
            total = sum(circuit_powers.values())
            timeline.append(TimelineBucket(
                timestamp=ts_str,
                total_w=round(total, 1),
                circuits=circuit_powers,
            ))

    # 7. Totals
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
        total_energy_today_kwh=round(total_energy_today, 2),
        total_cost_today=round(total_energy_today * electricity_rate, 2),
        total_energy_month_kwh=round(total_energy_month, 2),
        total_cost_month=round(total_energy_month * electricity_rate, 2),
        electricity_rate=electricity_rate,
    )
