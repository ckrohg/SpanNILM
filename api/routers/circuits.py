"""Circuit configuration endpoints.

Syncs circuits from TempIQ and stores user config (dedicated/shared, device labels)
in SpanNILM's own Supabase.
"""

import logging
import os

import psycopg2
import psycopg2.extras

from fastapi import APIRouter

from api.deps import get_tempiq_source
from api.models import CircuitConfig, CircuitConfigUpdate

logger = logging.getLogger("span_nilm.api.circuits")
router = APIRouter(prefix="/api/circuits")


def _get_db():
    conn = psycopg2.connect(os.environ["SPANNILM_DATABASE_URL"])
    return conn


@router.get("/config", response_model=list[CircuitConfig])
def get_circuit_configs():
    """Get all circuits with their config (merged from TempIQ + SpanNILM DB)."""
    source = get_tempiq_source()
    tempiq_circuits = source.get_circuits()

    # Load saved configs from SpanNILM DB
    conn = _get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM circuits")
            saved = {row["tempiq_equipment_id"]: dict(row) for row in cur.fetchall()}
    finally:
        conn.close()

    result = []
    for tc in tempiq_circuits:
        equip_id = tc["equipment_id"]
        saved_config = saved.get(equip_id, {})

        result.append(CircuitConfig(
            equipment_id=equip_id,
            name=tc["name"],
            circuit_number=tc.get("circuit_number"),
            user_label=saved_config.get("user_label"),
            is_dedicated=saved_config.get("is_dedicated", False),
            dedicated_device_type=saved_config.get("dedicated_device_type"),
        ))

    return result


@router.put("/{equipment_id}", response_model=CircuitConfig)
def update_circuit_config(equipment_id: str, update: CircuitConfigUpdate):
    """Update circuit configuration (dedicated/shared, device type, label)."""
    source = get_tempiq_source()

    # Verify the circuit exists in TempIQ
    circuits = source.get_circuits()
    circuit = next((c for c in circuits if c["equipment_id"] == equipment_id), None)
    if not circuit:
        from fastapi import HTTPException
        raise HTTPException(404, "Circuit not found")

    conn = _get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO circuits (tempiq_equipment_id, name, circuit_number, user_label, is_dedicated, dedicated_device_type)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tempiq_equipment_id) DO UPDATE SET
                    user_label = EXCLUDED.user_label,
                    is_dedicated = EXCLUDED.is_dedicated,
                    dedicated_device_type = EXCLUDED.dedicated_device_type,
                    updated_at = now()
                RETURNING *
            """, (
                equipment_id,
                circuit["name"],
                circuit.get("circuit_number"),
                update.user_label,
                update.is_dedicated,
                update.dedicated_device_type,
            ))
            row = dict(cur.fetchone())
            conn.commit()
    finally:
        conn.close()

    return CircuitConfig(
        equipment_id=equipment_id,
        name=circuit["name"],
        circuit_number=circuit.get("circuit_number"),
        user_label=row.get("user_label"),
        is_dedicated=row.get("is_dedicated", False),
        dedicated_device_type=row.get("dedicated_device_type"),
    )
