"""Circuit detail endpoint — deep dive into a single circuit."""

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
    CircuitDetailResponse,
    DailyEnergy,
    DetectedDevice,
    DeviceDetailResponse,
    DeviceSession,
    PowerPoint,
)

logger = logging.getLogger("span_nilm.api.circuit_detail")
router = APIRouter(prefix="/api")

DEFAULT_ELECTRICITY_RATE = 0.14
# Import shared Eastern offset
from api.routers.dashboard import EASTERN_OFFSET


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
            ts_raw = ts.isoformat() if hasattr(ts, "isoformat") else str(ts); ts_str = ts_raw if ts_raw.endswith("Z") or "+" in ts_raw else ts_raw + "Z"
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


@router.get("/devices/{equipment_id}/{cluster_id}/detail", response_model=DeviceDetailResponse)
def get_device_detail(
    equipment_id: str,
    cluster_id: int,
    days: int = Query(default=30, ge=1, le=90),
):
    """Return detailed usage data for a single detected device on a circuit."""
    # Load device template from circuit_profiles
    conn = _get_spannilm_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT circuit_name, shape_devices FROM circuit_profiles WHERE equipment_id = %s",
                (equipment_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        from fastapi import HTTPException
        raise HTTPException(404, f"No profile found for {equipment_id}")

    circuit_name = row["circuit_name"]
    shape_devices = row.get("shape_devices") or []
    if isinstance(shape_devices, str):
        shape_devices = json.loads(shape_devices)

    # Find the matching device template
    device_template = None
    for sd in shape_devices:
        if sd.get("cluster_id") == cluster_id:
            device_template = sd
            break
    if device_template is None and 0 <= cluster_id < len(shape_devices):
        device_template = shape_devices[cluster_id]

    if not device_template:
        from fastapi import HTTPException
        raise HTTPException(404, f"No device found for cluster {cluster_id}")

    # Check for user-assigned name in device_labels
    device_name = device_template.get("name", f"Device {cluster_id}")
    try:
        conn = _get_spannilm_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT name FROM device_labels WHERE equipment_id = %s AND cluster_id = %s",
                    (equipment_id, cluster_id),
                )
                label_row = cur.fetchone()
                if label_row:
                    device_name = label_row[0]
        finally:
            conn.close()
    except Exception:
        pass  # table may not exist yet

    template_curve = device_template.get("template_curve", [])
    avg_power_w = device_template.get("avg_power_w", 0)
    peak_power_w = device_template.get("peak_power_w", 0)
    peak_hours = [int(h) for h in device_template.get("peak_hours", [])]

    # Fetch aggregated power data for session extraction
    source = get_tempiq_source()
    now = datetime.now(timezone.utc)
    eastern = timezone(EASTERN_OFFSET)
    now_eastern = now.astimezone(eastern)
    start = now_eastern.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    start_utc = start.astimezone(timezone.utc)

    agg = source.get_aggregated_power(start_utc, now)

    sessions: list[DeviceSession] = []
    total_energy_wh = 0.0

    if not agg.empty:
        circuit_data = agg[agg["circuit_id"] == equipment_id].copy()
        if not circuit_data.empty:
            circuit_data = circuit_data.sort_values("timestamp").reset_index(drop=True)

            # Extract sessions and match to this device's template via cosine similarity
            import pandas as pd
            from scipy.interpolate import interp1d

            power = circuit_data["power_w"].values.astype(float)
            timestamps = pd.to_datetime(circuit_data["timestamp"])

            ON_THRESHOLD = 15.0
            CURVE_LENGTH = 32
            MIN_SIMILARITY = 0.7

            # Extract ON sessions
            in_session = False
            session_start = 0
            raw_sessions = []

            for i in range(len(power)):
                if power[i] > ON_THRESHOLD and not in_session:
                    in_session = True
                    session_start = i
                elif power[i] <= ON_THRESHOLD and in_session:
                    in_session = False
                    if i - session_start >= 2:
                        raw_sessions.append((session_start, i))

            if in_session and len(power) - session_start >= 2:
                raw_sessions.append((session_start, len(power)))

            # For each session, normalize curve and compare to template
            template_arr = np.array(template_curve) if template_curve else None

            for s_start, s_end in raw_sessions:
                session_power = power[s_start:s_end]
                session_ts = timestamps.iloc[s_start:s_end]

                if len(session_power) < 2:
                    continue

                # Normalize the session curve
                peak = np.max(session_power)
                if peak < ON_THRESHOLD:
                    continue

                # Resample to CURVE_LENGTH points
                x_orig = np.linspace(0, 1, len(session_power))
                x_new = np.linspace(0, 1, CURVE_LENGTH)
                try:
                    f = interp1d(x_orig, session_power, kind="linear")
                    resampled = f(x_new)
                except Exception:
                    continue

                normalized = resampled / peak

                # Cosine similarity with template
                if template_arr is not None and len(template_arr) == CURVE_LENGTH:
                    dot = np.dot(normalized, template_arr)
                    norm_a = np.linalg.norm(normalized)
                    norm_b = np.linalg.norm(template_arr)
                    if norm_a > 0 and norm_b > 0:
                        similarity = dot / (norm_a * norm_b)
                    else:
                        similarity = 0
                else:
                    # No template to compare, check power range match
                    session_avg = float(np.mean(session_power))
                    if avg_power_w > 0:
                        power_ratio = session_avg / avg_power_w
                        similarity = 1.0 if 0.5 < power_ratio < 2.0 else 0.0
                    else:
                        similarity = 0.5

                if similarity < MIN_SIMILARITY:
                    continue

                # This session matches the device
                ts_start = session_ts.iloc[0]
                ts_end = session_ts.iloc[-1]
                if hasattr(ts_start, "to_pydatetime"):
                    ts_start = ts_start.to_pydatetime()
                    ts_end = ts_end.to_pydatetime()

                duration_min = (ts_end - ts_start).total_seconds() / 60
                session_avg_power = float(np.mean(session_power))
                session_energy_wh = session_avg_power * duration_min / 60

                sessions.append(DeviceSession(
                    start=(ts_start.isoformat() + "Z") if hasattr(ts_start, "isoformat") and not ts_start.isoformat().endswith("Z") else str(ts_start),
                    end=(ts_end.isoformat() + "Z") if hasattr(ts_end, "isoformat") and not ts_end.isoformat().endswith("Z") else str(ts_end),
                    duration_min=round(duration_min, 1),
                    avg_power_w=round(session_avg_power, 1),
                    energy_wh=round(session_energy_wh, 1),
                ))
                total_energy_wh += session_energy_wh

    total_sessions = len(sessions)
    avg_sessions_per_day = round(total_sessions / max(1, days), 2)

    return DeviceDetailResponse(
        equipment_id=equipment_id,
        cluster_id=cluster_id,
        name=device_name,
        circuit_name=circuit_name,
        template_curve=template_curve,
        avg_power_w=round(avg_power_w, 1),
        peak_power_w=round(peak_power_w, 1),
        sessions=sessions,
        total_energy_kwh=round(total_energy_wh / 1000, 3),
        total_sessions=total_sessions,
        avg_sessions_per_day=avg_sessions_per_day,
        peak_hours=peak_hours,
    )
