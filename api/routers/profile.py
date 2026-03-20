"""Profile endpoint — runs circuit profiler and stores/retrieves results."""

import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Query

from api.background import get_task, run_in_background
from api.deps import get_tempiq_source
from api.routers.device_naming import auto_name_all_devices
from span_nilm.profiler.circuit_profiler import CircuitProfiler

logger = logging.getLogger("span_nilm.api.profile")
router = APIRouter(prefix="/api")


def _do_profile(days: int, equipment_id: str | None = None) -> dict:
    """Run the full profiler pipeline. Called from background thread."""
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
    auto_named = 0
    try:
        auto_result = auto_name_all_devices()
        auto_named = auto_result.get("named", 0)
        logger.info("Auto-named %d devices", auto_named)
    except Exception as e:
        logger.warning("Auto-naming failed (non-fatal): %s", e)

    return {
        "profiles_saved": saved,
        "devices_named": auto_named,
        "profile_count": len(profiles),
    }


def _do_profile_cron() -> dict:
    """Run the cron profiler pipeline. Called from background thread."""
    errors: list[str] = []
    profiles_saved = 0
    named_count = 0

    # Step 1: Run profiler with 30 days of data
    try:
        source = get_tempiq_source()
        profiler = CircuitProfiler(
            source=source,
            spannilm_db_url=os.environ["SPANNILM_DATABASE_URL"],
            data_days=30,
        )
        profiles = profiler.profile_all()
        profiles_saved = profiler.save_profiles(profiles)
        logger.info("Cron: saved %d circuit profiles", profiles_saved)
    except Exception as e:
        logger.error("Cron: profiler failed: %s", e)
        errors.append(f"profiler: {e}")

    # Step 2: Auto-name unnamed devices
    try:
        auto_result = auto_name_all_devices()
        named_count = auto_result.get("named", 0)
        auto_errors = auto_result.get("errors", [])
        if auto_errors:
            errors.extend(auto_errors)
        logger.info("Cron: auto-named %d devices", named_count)
    except Exception as e:
        logger.error("Cron: auto-naming failed: %s", e)
        errors.append(f"auto-naming: {e}")

    return {
        "status": "ok" if not errors else "partial",
        "profiles_saved": profiles_saved,
        "devices_named": named_count,
        "errors": errors[:20],
    }


@router.post("/profile")
def run_profile(
    equipment_id: Optional[str] = Query(default=None, description="Profile a single circuit"),
    days: int = Query(default=90, ge=7, le=180, description="Days of history to analyze"),
):
    """Run the circuit profiler in background. Returns task_id for polling."""
    task_id = f"profile-{int(time.time())}"
    run_in_background(task_id, _do_profile, days, equipment_id)
    return {"status": "started", "task_id": task_id}


@router.post("/profile/cron")
def run_profile_cron():
    """Cron endpoint for weekly profiler + auto-naming. Runs in background."""
    task_id = f"profile-cron-{int(time.time())}"
    run_in_background(task_id, _do_profile_cron)
    return {"status": "started", "task_id": task_id}


@router.get("/profile/status/{task_id}")
def get_profile_status(task_id: str):
    """Poll for background task status."""
    task = get_task(task_id)
    if not task:
        return {"status": "not_found"}
    return {
        "status": task.status,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "result": task.result if task.status == "completed" else None,
        "error": task.error,
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
                "llm_analysis": r.get("llm_analysis") or {},
                "signature_matches": r.get("signature_matches") or [],
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
