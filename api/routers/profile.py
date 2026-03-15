"""Profile endpoint — runs circuit profiler and stores/retrieves results."""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Query

from api.deps import get_tempiq_source
from api.routers.device_naming import auto_name_all_devices
from span_nilm.profiler.circuit_profiler import CircuitProfiler

logger = logging.getLogger("span_nilm.api.profile")
router = APIRouter(prefix="/api")


@router.post("/profile")
def run_profile(
    equipment_id: Optional[str] = Query(default=None, description="Profile a single circuit"),
    days: int = Query(default=90, ge=7, le=180, description="Days of history to analyze"),
):
    """Run the circuit profiler on all circuits (or a specific one) and store results."""
    source = get_tempiq_source()
    profiler = CircuitProfiler(
        source=source,
        spannilm_db_url=os.environ["SPANNILM_DATABASE_URL"],
        data_days=days,
    )

    profiles = profiler.profile_all()

    # Filter to a single circuit if requested
    if equipment_id:
        profiles = [p for p in profiles if p.equipment_id == equipment_id]

    saved = profiler.save_profiles(profiles)
    logger.info("Saved %d circuit profiles", saved)

    # Auto-name unnamed devices after saving profiles
    try:
        auto_result = auto_name_all_devices()
        logger.info("Auto-named %d devices", auto_result.get("named", 0))
    except Exception as e:
        logger.warning("Auto-naming failed (non-fatal): %s", e)

    return {
        "status": "ok",
        "profiles_saved": saved,
        "profiles": [
            {
                "equipment_id": p.equipment_id,
                "circuit_name": p.circuit_name,
                "is_dedicated": p.is_dedicated,
                "dedicated_device_type": p.dedicated_device_type,
                "total_readings": p.total_readings,
                "active_pct": p.active_pct,
                "baseload_w": p.baseload_w,
                "states": [
                    {
                        "center_w": s.center_w,
                        "count": s.count,
                        "pct_of_time": s.pct_of_time,
                        "avg_duration_min": s.avg_duration_min,
                        "peak_hours": s.peak_hours,
                        "device_name": s.device_name,
                        "confidence": s.confidence,
                    }
                    for s in p.states
                ],
            }
            for p in profiles
        ],
    }


@router.get("/profile")
def get_profiles():
    """Retrieve stored circuit profiles with temporal data."""
    rows = CircuitProfiler.load_profiles()
    return {
        "status": "ok",
        "profiles": [
            {
                "equipment_id": r["equipment_id"],
                "circuit_name": r["circuit_name"],
                "is_dedicated": r["is_dedicated"],
                "dedicated_device_type": r["dedicated_device_type"],
                "total_readings": r["total_readings"],
                "active_pct": float(r["active_pct"]) if r["active_pct"] else 0,
                "baseload_w": float(r["baseload_w"]) if r["baseload_w"] else 0,
                "profiled_at": r["profiled_at"].isoformat() if r["profiled_at"] else None,
                "data_days": r["data_days"],
                "states": r["states"] or [],
                "temporal": r.get("temporal") or {},
                "correlations": r.get("correlations") or [],
            }
            for r in rows
        ],
    }


@router.get("/circuit/{equipment_id}/timeseries")
def get_circuit_timeseries(
    equipment_id: str,
    hours_back: int = Query(default=24, ge=1, le=168),
):
    """Get power time-series for a single circuit (for detail charts)."""
    from datetime import datetime, timedelta, timezone
    source = get_tempiq_source()
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours_back)

    df = source.get_power_timeseries(equipment_id, start, end)
    points = [
        {"timestamp": str(row["timestamp"]), "power_w": round(row["power_w"], 1)}
        for _, row in df.iterrows()
    ]

    # Also load this circuit's profile if available
    profiles = CircuitProfiler.load_profiles()
    profile = next((p for p in profiles if p["equipment_id"] == equipment_id), None)

    return {
        "circuit_id": equipment_id,
        "points": points,
        "profile": {
            "states": profile.get("states", []) if profile else [],
            "temporal": profile.get("temporal", {}) if profile else {},
            "correlations": profile.get("correlations", []) if profile else [],
            "active_pct": float(profile["active_pct"]) if profile and profile.get("active_pct") else 0,
        } if profile else None,
    }
