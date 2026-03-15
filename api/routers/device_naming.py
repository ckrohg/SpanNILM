"""Device naming endpoints — Claude-powered suggestions + user confirmation."""

import json
import logging
import os
import time

import anthropic
import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("span_nilm.api.device_naming")
router = APIRouter(prefix="/api")


def _get_spannilm_db():
    return psycopg2.connect(os.environ["SPANNILM_DATABASE_URL"])


def _ensure_device_labels_table():
    """Create device_labels table if it doesn't exist."""
    conn = _get_spannilm_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS device_labels (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    equipment_id VARCHAR NOT NULL,
                    cluster_id INTEGER NOT NULL,
                    name VARCHAR NOT NULL,
                    source VARCHAR DEFAULT 'user',
                    created_at TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(equipment_id, cluster_id)
                )
            """)
            conn.commit()
    finally:
        conn.close()


def _load_device_template(equipment_id: str, cluster_id: int) -> dict | None:
    """Load a specific device template from circuit_profiles.shape_devices."""
    conn = _get_spannilm_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT circuit_name, shape_devices, correlations FROM circuit_profiles WHERE equipment_id = %s",
                (equipment_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            shape_devices = row.get("shape_devices") or []
            if isinstance(shape_devices, str):
                shape_devices = json.loads(shape_devices)

            for sd in shape_devices:
                if sd.get("cluster_id", sd.get("name", "")) == cluster_id:
                    sd["circuit_name"] = row["circuit_name"]
                    sd["correlations"] = row.get("correlations") or []
                    if isinstance(sd["correlations"], str):
                        sd["correlations"] = json.loads(sd["correlations"])
                    return sd

            # Try matching by index position if cluster_id is an integer index
            for i, sd in enumerate(shape_devices):
                if i == cluster_id:
                    sd["cluster_id"] = cluster_id
                    sd["circuit_name"] = row["circuit_name"]
                    sd["correlations"] = row.get("correlations") or []
                    if isinstance(sd["correlations"], str):
                        sd["correlations"] = json.loads(sd["correlations"])
                    return sd

            return None
    finally:
        conn.close()


class DeviceSuggestion(BaseModel):
    name: str
    reasoning: str


class DeviceSuggestResponse(BaseModel):
    suggestions: list[DeviceSuggestion]


class DeviceNameUpdate(BaseModel):
    name: str


def _build_suggest_prompt(template: dict) -> str:
    """Build the Claude prompt for device name suggestion from a device template."""
    circuit_name = template.get("circuit_name", "Unknown")
    avg_power = template.get("avg_power_w", 0)
    peak_power = template.get("peak_power_w", 0)
    num_phases = template.get("num_phases", 1)
    has_surge = template.get("has_startup_surge", False)
    avg_duration = template.get("avg_duration_min", 0)
    sessions_per_day = template.get("sessions_per_day", 0)
    peak_hours = template.get("peak_hours", [])
    is_cycling = template.get("is_cycling", False)
    duty_cycle = template.get("duty_cycle", 0)
    energy_per_session = template.get("energy_per_session_wh", 0)
    template_curve = template.get("template_curve", [])
    correlations = template.get("correlations", [])

    corr_str = "None"
    if correlations:
        corr_parts = []
        for c in correlations[:3]:
            name = c.get("name", "Unknown")
            score = c.get("score", 0)
            corr_parts.append(f"{name} ({score:.0%} correlation)")
        corr_str = ", ".join(corr_parts)

    curve_str = ", ".join(f"{v:.3f}" for v in template_curve) if template_curve else "N/A"

    return f"""You are analyzing power consumption data from a residential electrical circuit to identify what device is producing this pattern.

Circuit: {circuit_name}
Average power: {avg_power}W
Peak power: {peak_power}W
Number of phases: {num_phases} (distinct power levels within a session)
Has startup surge: {has_surge}
Average session duration: {avg_duration:.1f} minutes
Sessions per day: {sessions_per_day}
Peak usage hours: {peak_hours}
Is cycling: {is_cycling}
Duty cycle: {duty_cycle:.1%}
Energy per session: {energy_per_session}Wh
Correlated circuits: {corr_str}

Power curve shape (normalized 0-1, 32 samples across session duration):
[{curve_str}]

Based on this data, suggest 2-3 specific device names that could produce this pattern. Consider:
- The circuit name gives context about location/purpose
- Power level and phases indicate device type
- Duration and cycling indicate operating pattern
- Peak hours indicate usage schedule
- Correlated circuits suggest linked systems

Return ONLY a JSON array of objects with "name" and "reasoning" fields. Be specific (e.g., "Mitsubishi Mini-Split Compressor" not just "HVAC"). Example:
[{{"name": "Electric Baseboard Heater", "reasoning": "Steady 1.3kW draw with long sessions matches resistive heating element"}}]"""


def _parse_claude_suggestions(response_text: str) -> list[dict]:
    """Parse Claude's response text into a list of suggestion dicts."""
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


@router.post(
    "/devices/{equipment_id}/{cluster_id}/suggest",
    response_model=DeviceSuggestResponse,
)
def suggest_device_names(equipment_id: str, cluster_id: int):
    """Use Claude to suggest device names based on power characteristics."""
    template = _load_device_template(equipment_id, cluster_id)
    if not template:
        raise HTTPException(404, f"No device template found for {equipment_id} cluster {cluster_id}")

    prompt = _build_suggest_prompt(template)

    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        suggestions_raw = _parse_claude_suggestions(message.content[0].text)
        suggestions = [
            DeviceSuggestion(name=s["name"], reasoning=s["reasoning"])
            for s in suggestions_raw
        ]
        return DeviceSuggestResponse(suggestions=suggestions)

    except anthropic.APIError as e:
        logger.error("Claude API error: %s", e)
        raise HTTPException(502, f"Claude API error: {e}")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error("Failed to parse Claude response: %s", e)
        raise HTTPException(502, f"Failed to parse AI response: {e}")


@router.put("/devices/{equipment_id}/{cluster_id}/name")
def set_device_name(equipment_id: str, cluster_id: int, body: DeviceNameUpdate):
    """Save a user-confirmed device name."""
    _ensure_device_labels_table()

    conn = _get_spannilm_db()
    try:
        with conn.cursor() as cur:
            # 1. Update the name in circuit_profiles.shape_devices JSONB
            cur.execute(
                "SELECT shape_devices FROM circuit_profiles WHERE equipment_id = %s",
                (equipment_id,),
            )
            row = cur.fetchone()
            if row:
                shape_devices = row[0] or []
                if isinstance(shape_devices, str):
                    shape_devices = json.loads(shape_devices)

                updated = False
                for sd in shape_devices:
                    cid = sd.get("cluster_id", None)
                    if cid == cluster_id:
                        sd["name"] = body.name
                        updated = True
                        break

                # Try by index if cluster_id field not found
                if not updated and 0 <= cluster_id < len(shape_devices):
                    shape_devices[cluster_id]["name"] = body.name
                    updated = True

                if updated:
                    cur.execute(
                        "UPDATE circuit_profiles SET shape_devices = %s::jsonb WHERE equipment_id = %s",
                        (json.dumps(shape_devices), equipment_id),
                    )

            # 2. Upsert into device_labels table
            cur.execute(
                """
                INSERT INTO device_labels (equipment_id, cluster_id, name, source)
                VALUES (%s, %s, %s, 'user')
                ON CONFLICT (equipment_id, cluster_id)
                DO UPDATE SET name = EXCLUDED.name, source = 'user', created_at = now()
                """,
                (equipment_id, cluster_id, body.name),
            )
            conn.commit()

        return {"status": "ok", "name": body.name}
    finally:
        conn.close()


@router.post("/devices/auto-name")
def auto_name_all_devices():
    """Batch AI naming: call Claude Haiku for every unnamed device and save results.

    Skips devices that already have a user-confirmed name in device_labels.
    Uses 1-second sleep between Claude calls to avoid rate limiting.
    """
    _ensure_device_labels_table()

    conn = _get_spannilm_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Load all circuit profiles with shape_devices
            cur.execute(
                "SELECT equipment_id, circuit_name, shape_devices, correlations FROM circuit_profiles"
            )
            profiles = cur.fetchall()

            # Load existing user-confirmed labels (source='user') to skip
            cur.execute(
                "SELECT equipment_id, cluster_id FROM device_labels WHERE source = 'user'"
            )
            user_labels = {(row["equipment_id"], row["cluster_id"]) for row in cur.fetchall()}

        # Build list of devices that need naming
        devices_to_name: list[tuple[str, int, dict]] = []  # (equipment_id, cluster_id, template)
        for profile in profiles:
            shape_devices = profile.get("shape_devices") or []
            if isinstance(shape_devices, str):
                shape_devices = json.loads(shape_devices)

            correlations = profile.get("correlations") or []
            if isinstance(correlations, str):
                correlations = json.loads(correlations)

            for sd in shape_devices:
                cluster_id = sd.get("cluster_id", 0)
                equipment_id = profile["equipment_id"]

                # Skip if user already confirmed a name
                if (equipment_id, cluster_id) in user_labels:
                    continue

                # Build template dict for prompt
                template = dict(sd)
                template["circuit_name"] = profile["circuit_name"]
                template["correlations"] = correlations
                devices_to_name.append((equipment_id, cluster_id, template))

        if not devices_to_name:
            return {"status": "ok", "named": 0, "message": "All devices already named"}

        # Call Claude for each device
        client = anthropic.Anthropic()
        named_count = 0
        errors = []

        for equipment_id, cluster_id, template in devices_to_name:
            prompt = _build_suggest_prompt(template)
            try:
                message = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )
                suggestions = _parse_claude_suggestions(message.content[0].text)
                if not suggestions:
                    continue

                # Take the top suggestion
                best_name = suggestions[0]["name"]
                logger.info(
                    "Auto-naming %s cluster %d: %s",
                    equipment_id, cluster_id, best_name,
                )

                with conn.cursor() as cur:
                    # Update shape_devices JSONB in circuit_profiles
                    cur.execute(
                        "SELECT shape_devices FROM circuit_profiles WHERE equipment_id = %s",
                        (equipment_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        sd_list = row[0] or []
                        if isinstance(sd_list, str):
                            sd_list = json.loads(sd_list)

                        updated = False
                        for sd in sd_list:
                            if sd.get("cluster_id") == cluster_id:
                                sd["name"] = best_name
                                updated = True
                                break
                        if not updated and 0 <= cluster_id < len(sd_list):
                            sd_list[cluster_id]["name"] = best_name
                            updated = True

                        if updated:
                            cur.execute(
                                "UPDATE circuit_profiles SET shape_devices = %s::jsonb WHERE equipment_id = %s",
                                (json.dumps(sd_list), equipment_id),
                            )

                    # Upsert into device_labels with source='ai_auto'
                    cur.execute(
                        """
                        INSERT INTO device_labels (equipment_id, cluster_id, name, source)
                        VALUES (%s, %s, %s, 'ai_auto')
                        ON CONFLICT (equipment_id, cluster_id)
                        DO UPDATE SET name = EXCLUDED.name, source = 'ai_auto', created_at = now()
                        WHERE device_labels.source != 'user'
                        """,
                        (equipment_id, cluster_id, best_name),
                    )
                    conn.commit()

                named_count += 1

            except (anthropic.APIError, json.JSONDecodeError, KeyError, IndexError) as e:
                logger.warning("Auto-name failed for %s cluster %d: %s", equipment_id, cluster_id, e)
                errors.append(f"{equipment_id}:{cluster_id}: {e}")

            # Rate limit: 1 second between calls
            time.sleep(1)

        return {
            "status": "ok",
            "named": named_count,
            "total_candidates": len(devices_to_name),
            "errors": errors[:10] if errors else [],
        }

    finally:
        conn.close()
