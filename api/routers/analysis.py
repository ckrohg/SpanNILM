"""Analysis, circuits, and power endpoints."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from api.deps import get_config, get_tempiq_source
from api.models import (
    AnalysisResponse,
    CircuitInfo,
    DeviceClusterOut,
    PowerEventOut,
    PowerPoint,
    PowerTimeseriesResponse,
    SignatureMatchOut,
)
from span_nilm.analysis.pipeline import AnalysisPipeline

logger = logging.getLogger("span_nilm.api")
router = APIRouter(prefix="/api")


@router.get("/circuits", response_model=list[CircuitInfo])
def list_circuits():
    """List all SPAN circuits from TempIQ."""
    source = get_tempiq_source()
    circuits = source.get_circuits()
    return [
        CircuitInfo(
            equipment_id=c["equipment_id"],
            name=c["name"],
            circuit_number=c.get("circuit_number"),
        )
        for c in circuits
    ]


@router.post("/analyze", response_model=AnalysisResponse)
def run_analysis(hours_back: int = Query(default=24, ge=1, le=168)):
    """Fetch recent data from TempIQ and run the detection pipeline."""
    source = get_tempiq_source()
    config = get_config()

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours_back)

    logger.info("Running analysis for last %d hours", hours_back)
    df = source.get_readings(start, end)

    if df.empty:
        return AnalysisResponse(
            total_readings=0, date_range=None, total_events=0,
            total_runs=0, devices=[], events=[], total_power_w=0,
        )

    pipeline = AnalysisPipeline(config)
    result = pipeline.analyze(df=df)

    # Build device list from clusters
    devices = []
    all_events = []

    # Get circuit names from events
    circuit_names = {}
    for cid, events in result.circuit_events.items():
        if events:
            circuit_names[cid] = events[0].circuit_name

    for circuit_id, identifications in result.identifications.items():
        circuit_name = circuit_names.get(circuit_id, circuit_id)
        for cluster, matches in identifications:
            # Check if device is currently on (unpaired ON event in last hour)
            is_on = False
            current_power = 0.0
            runs = result.device_runs.get(circuit_id, [])
            for run in runs:
                if run.off_event is None and run.on_event.circuit_id == circuit_id:
                    if abs(run.power_draw_w - cluster.mean_power_w) / max(cluster.mean_power_w, 1) < 0.5:
                        is_on = True
                        current_power = run.power_draw_w

            devices.append(DeviceClusterOut(
                cluster_id=cluster.cluster_id,
                circuit_id=circuit_id,
                circuit_name=circuit_name,
                label=cluster.label,
                mean_power_w=round(cluster.mean_power_w, 1),
                std_power_w=round(cluster.std_power_w, 1),
                mean_duration_s=round(cluster.mean_duration_s, 0) if cluster.mean_duration_s else None,
                observation_count=cluster.observation_count,
                matches=[
                    SignatureMatchOut(
                        device_name=m.device_name,
                        confidence=round(m.confidence, 3),
                        category=m.category,
                    )
                    for m in matches[:3]
                ],
                is_on=is_on,
                current_power_w=round(current_power, 1),
            ))

    # Flatten events for activity feed
    for circuit_id, events in result.circuit_events.items():
        for ev in events:
            all_events.append(PowerEventOut(
                timestamp=str(ev.timestamp),
                circuit_id=ev.circuit_id,
                circuit_name=ev.circuit_name,
                power_before_w=round(ev.power_before_w, 1),
                power_after_w=round(ev.power_after_w, 1),
                delta_w=round(ev.delta_w, 1),
                event_type=ev.event_type,
            ))

    # Sort events by timestamp descending (most recent first)
    all_events.sort(key=lambda e: e.timestamp, reverse=True)

    # Total current power (sum of "on" devices)
    total_power = sum(d.current_power_w for d in devices if d.is_on)

    total_events = sum(len(e) for e in result.circuit_events.values())
    total_runs = sum(len(r) for r in result.device_runs.values())

    return AnalysisResponse(
        total_readings=result.total_readings,
        date_range=list(result.date_range) if result.date_range else None,
        total_events=total_events,
        total_runs=total_runs,
        devices=devices,
        events=all_events[:100],  # Last 100 events
        total_power_w=round(total_power, 1),
    )


@router.get("/power/{equipment_id}", response_model=PowerTimeseriesResponse)
def get_power_timeseries(
    equipment_id: str,
    hours_back: int = Query(default=24, ge=1, le=168),
):
    """Get power time-series for a single circuit."""
    source = get_tempiq_source()
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours_back)

    df = source.get_power_timeseries(equipment_id, start, end)

    points = [
        PowerPoint(timestamp=str(row["timestamp"]), power_w=round(row["power_w"], 1))
        for _, row in df.iterrows()
    ]

    return PowerTimeseriesResponse(
        circuit_id=equipment_id,
        points=points,
    )
