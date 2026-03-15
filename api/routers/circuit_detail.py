"""Circuit detail endpoint — deep dive into a single circuit."""

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
    CircuitDetailResponse,
    DailyEnergy,
    DetectedDevice,
    PowerPoint,
)

logger = logging.getLogger("span_nilm.api.circuit_detail")
router = APIRouter(prefix="/api")

DEFAULT_ELECTRICITY_RATE = 0.14
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


def _load_circuit_config(equipment_id: str) -> dict:
    conn = _get_spannilm_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM circuits WHERE tempiq_equipment_id = %s",
                (equipment_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else {}
    finally:
        conn.close()


@router.get("/circuit/{equipment_id}/detail", response_model=CircuitDetailResponse)
def get_circuit_detail(
    equipment_id: str,
    days: int = Query(default=7, ge=1, le=90),
):
    """Return detailed data for a single circuit."""
    rate = _load_electricity_rate()
    source = get_tempiq_source()
    now = datetime.now(timezone.utc)
    eastern = timezone(EASTERN_OFFSET)
    now_eastern = now.astimezone(eastern)
    start = now_eastern.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    start_utc = start.astimezone(timezone.utc)

    config = _load_circuit_config(equipment_id)
    name = config.get("user_label") or equipment_id
    is_dedicated = config.get("is_dedicated", False)
    device_type = config.get("dedicated_device_type")

    # Fetch aggregated power data for this circuit
    agg = source.get_aggregated_power(start_utc, now)

    # Filter to this circuit
    if not agg.empty:
        circuit_data = agg[agg["circuit_id"] == equipment_id].copy()
        if not circuit_data.empty and name == equipment_id:
            name = circuit_data["circuit_name"].iloc[0]
    else:
        circuit_data = agg.iloc[0:0]  # empty DataFrame with same columns

    # Power time-series
    power_series: list[PowerPoint] = []
    if not circuit_data.empty:
        circuit_data = circuit_data.sort_values("timestamp")
        for _, row in circuit_data.iterrows():
            ts = row["timestamp"]
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            power_series.append(PowerPoint(timestamp=ts_str, power_w=round(float(row["power_w"]), 1)))

    # Stats
    if power_series:
        powers = [p.power_w for p in power_series]
        avg_power = float(np.mean(powers))
        peak_power = float(np.max(powers))
        min_power = float(np.min(powers))
        always_on = float(np.percentile(powers, 10))
    else:
        avg_power = peak_power = min_power = always_on = 0.0

    # Daily energy: group by date (Eastern time)
    daily_energy: list[DailyEnergy] = []
    daily_kwh_values: list[float] = []
    if not circuit_data.empty:
        import pandas as pd
        cd = circuit_data.copy()
        ts_series = pd.to_datetime(cd["timestamp"])
        if ts_series.dt.tz is None:
            ts_series = ts_series.dt.tz_localize("UTC")
        cd["date"] = ts_series.dt.tz_convert(eastern).dt.date
        for date, group in cd.groupby("date"):
            kwh = float(group["power_w"].sum()) * (10.0 / 60.0) / 1000.0
            daily_energy.append(DailyEnergy(
                date=str(date),
                energy_kwh=round(kwh, 3),
                cost=round(kwh * rate, 3),
            ))
            daily_kwh_values.append(kwh)
        daily_energy.sort(key=lambda d: d.date)

    # Total energy for the period
    energy_period_kwh = sum(d.energy_kwh for d in daily_energy)
    cost_period = round(energy_period_kwh * rate, 2)

    # Anomalies: days where usage > 2x median
    anomalies: list[Anomaly] = []
    if daily_kwh_values:
        median_kwh = float(np.median(daily_kwh_values))
        if median_kwh > 0.01:
            for de in daily_energy:
                if de.energy_kwh > 2 * median_kwh:
                    anomalies.append(Anomaly(
                        timestamp=de.date,
                        description=f"Usage {de.energy_kwh:.1f} kWh is {de.energy_kwh / median_kwh:.1f}x the median ({median_kwh:.1f} kWh)",
                        severity="warning" if de.energy_kwh > 3 * median_kwh else "info",
                        value=round(de.energy_kwh, 2),
                        expected=round(median_kwh, 2),
                    ))

    # Detected devices from circuit profiles
    devices: list[DetectedDevice] = []
    if not is_dedicated:
        try:
            from span_nilm.profiler.circuit_profiler import CircuitProfiler
            profiles = CircuitProfiler.load_profiles()
            for row in profiles:
                if row["equipment_id"] == equipment_id:
                    shape_devs = row.get("shape_devices") or []
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
                    break
        except Exception as e:
            logger.debug("Could not load device profiles: %s", e)

    return CircuitDetailResponse(
        equipment_id=equipment_id,
        name=name,
        is_dedicated=is_dedicated,
        device_type=device_type,
        power_series=power_series,
        daily_energy=daily_energy,
        devices=devices,
        avg_power_w=round(avg_power, 1),
        peak_power_w=round(peak_power, 1),
        min_power_w=round(min_power, 1),
        always_on_w=round(max(0, always_on), 1),
        energy_period_kwh=round(energy_period_kwh, 2),
        cost_period=cost_period,
        anomalies=anomalies,
    )
