"""LLM-powered multi-level analysis for device identification.

Three analysis modes:
  A) Device adjudication  (Haiku)  — pick best ID from ML + signature candidates
  B) Circuit story         (Sonnet) — analyze full 24h profile for hidden devices
  C) Home reconciliation   (Sonnet) — catch duplicates, missing, misidentifications
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import anthropic
import numpy as np
import psycopg2
import psycopg2.extras

from span_nilm.collector.sources.tempiq_source import TempIQSource

logger = logging.getLogger("span_nilm.profiler.llm_analyzer")

HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"
RATE_LIMIT_SLEEP = 1.0  # seconds between Claude calls


def _sparkline(values: list[float], width: int = 40) -> str:
    """Render a list of floats as an ASCII sparkline."""
    if not values:
        return ""
    mn, mx = min(values), max(values)
    rng = mx - mn if mx > mn else 1.0
    chars = " _.,:-=!#"
    line = []
    # Downsample to width
    step = max(1, len(values) // width)
    for i in range(0, len(values), step):
        chunk = values[i : i + step]
        v = sum(chunk) / len(chunk)
        idx = int((v - mn) / rng * (len(chars) - 1))
        line.append(chars[min(idx, len(chars) - 1)])
    return "".join(line[:width])


def _safe_parse_json(text: str) -> dict | list | None:
    """Parse JSON from Claude response, stripping markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM JSON: %s", text[:200])
        return None


class LLMAnalyzer:
    """Three-mode LLM analysis for device identification."""

    def __init__(self):
        self.client = anthropic.Anthropic()

    # ------------------------------------------------------------------
    # Mode A — Device Adjudication (Haiku, per device)
    # ------------------------------------------------------------------

    def adjudicate_device(
        self,
        device_template: dict,
        signature_matches: list[dict],
        ml_predictions: list[tuple[str, float]],
        circuit_name: str,
    ) -> dict:
        """Use Claude to pick the best identification from multiple candidates.

        Args:
            device_template: shape_device dict with power stats + template_curve
            signature_matches: top-3 from SignatureMatcher [{device_name, confidence, reasoning}]
            ml_predictions: top-3 from DedicatedLearner [(device_type, probability)]
            circuit_name: name of the circuit

        Returns:
            {"name": str, "confidence": float, "reasoning": str}
        """
        avg_power = device_template.get("avg_power_w", 0)
        peak_power = device_template.get("peak_power_w", 0)
        duration = device_template.get("avg_duration_min", 0)
        sessions_per_day = device_template.get("sessions_per_day", 0)
        num_phases = device_template.get("num_phases", 1)
        has_surge = device_template.get("has_startup_surge", False)
        peak_hours = device_template.get("peak_hours", [])
        curve = device_template.get("template_curve", [])

        sparkline = _sparkline(curve) if curve else "N/A"

        sig_str = "None"
        if signature_matches:
            parts = []
            for sm in signature_matches[:3]:
                name = sm.get("device_name", "?")
                conf = sm.get("confidence", 0)
                parts.append(f"  - {name} ({conf:.0%})")
            sig_str = "\n".join(parts)

        ml_str = "None"
        if ml_predictions:
            parts = []
            for dt, prob in ml_predictions[:3]:
                parts.append(f"  - {dt} ({prob:.0%})")
            ml_str = "\n".join(parts)

        prompt = f"""Identify this device from its power consumption profile ONLY. Do NOT use the circuit name for identification.

POWER CONSUMPTION PROFILE:
- Average power: {avg_power:.0f}W, Peak: {peak_power:.0f}W
- Duration: {duration:.1f} min avg, Sessions/day: {sessions_per_day:.1f}
- Power stages: {num_phases}, Startup surge: {has_surge}
- Peak hours: {peak_hours}
- Power curve shape: |{sparkline}|

CANDIDATE IDENTIFICATIONS:
From signature matching: {sig_str}
From ML classifier: {ml_str}

RULES:
- Identify PURELY from the power profile above. What device draws {avg_power:.0f}W with this pattern?
- Do NOT use circuit name or location. A 45W cycling load is the same device regardless of where it is.
- Under 100W cycling = small compressor or electronics. NOT a pump or heater.
- 100-300W cycling = dehumidifier, freezer, or fan. NOT a heater unless >500W.

Pick the single best identification or suggest a better one.
Return ONLY a JSON object: {{"name": "...", "confidence": 0.0-1.0, "reasoning": "..."}}"""

        try:
            msg = self.client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            result = _safe_parse_json(msg.content[0].text)
            if result and isinstance(result, dict):
                return {
                    "name": result.get("name", "Unknown"),
                    "confidence": float(result.get("confidence", 0.5)),
                    "reasoning": result.get("reasoning", ""),
                }
        except anthropic.APIError as e:
            logger.warning("Claude adjudication failed: %s", e)

        return {
            "name": device_template.get("name", "Unknown"),
            "confidence": 0.3,
            "reasoning": "LLM adjudication failed; using original detection",
        }

    # ------------------------------------------------------------------
    # Mode B — Circuit Story (Sonnet, per sub-panel)
    # ------------------------------------------------------------------

    def analyze_circuit(
        self,
        circuit_name: str,
        power_series: list[float],
        timestamps: list[str],
        known_devices: list[str],
    ) -> list[dict]:
        """Analyze a full 24h power profile to find hidden devices.

        Args:
            circuit_name: name of the circuit / sub-panel
            power_series: 144 readings (10-min resolution, 24h)
            timestamps: matching timestamp strings
            known_devices: device names already identified on this circuit

        Returns:
            list of {"name", "power_w", "pattern", "confidence", "reasoning"}
        """
        # Downsample to ~144 points if longer
        if len(power_series) > 200:
            step = len(power_series) // 144
            power_series = [power_series[i] for i in range(0, len(power_series), step)][:144]
            timestamps = [timestamps[i] for i in range(0, len(timestamps), step)][:144]

        # Build compact power profile string
        profile_lines = []
        for i in range(0, len(power_series), 6):  # every hour (6 x 10min)
            chunk = power_series[i : i + 6]
            avg = sum(chunk) / len(chunk) if chunk else 0
            peak = max(chunk) if chunk else 0
            ts = timestamps[i] if i < len(timestamps) else "?"
            hour_str = ts[-8:-3] if len(ts) >= 8 else ts  # HH:MM
            profile_lines.append(f"  {hour_str}  avg={avg:6.0f}W  peak={peak:6.0f}W  |{_sparkline(chunk, 12)}|")

        profile_str = "\n".join(profile_lines)
        sparkline_full = _sparkline(power_series, 60)

        known_str = ", ".join(known_devices) if known_devices else "None identified yet"

        prompt = f"""Analyze this 24-hour power profile for circuit "{circuit_name}" in a New England home.

FULL 24H SPARKLINE:
|{sparkline_full}|

HOURLY BREAKDOWN:
{profile_str}

ALREADY IDENTIFIED DEVICES: {known_str}

Overall stats: min={min(power_series):.0f}W, max={max(power_series):.0f}W, mean={sum(power_series)/len(power_series):.0f}W

Questions:
1. How many distinct devices contribute to this signal?
2. For each device, describe: power level, usage pattern, and likely identity.
3. Are there devices hiding in the noise that the automated detectors missed?

Return ONLY a JSON array of objects, each with: "name", "power_w", "pattern", "confidence" (0-1), "reasoning".
Example: [{{"name": "Chest Freezer", "power_w": 120, "pattern": "cycling 30min on / 45min off", "confidence": 0.7, "reasoning": "Regular cycling pattern at 120W consistent with freezer compressor"}}]"""

        try:
            msg = self.client.messages.create(
                model=SONNET_MODEL,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            result = _safe_parse_json(msg.content[0].text)
            if result and isinstance(result, list):
                return [
                    {
                        "name": d.get("name", "Unknown"),
                        "power_w": float(d.get("power_w", 0)),
                        "pattern": d.get("pattern", ""),
                        "confidence": float(d.get("confidence", 0.5)),
                        "reasoning": d.get("reasoning", ""),
                    }
                    for d in result
                ]
        except anthropic.APIError as e:
            logger.warning("Claude circuit analysis failed for %s: %s", circuit_name, e)

        return []

    # ------------------------------------------------------------------
    # Mode C — Home Reconciliation (Sonnet, once per run)
    # ------------------------------------------------------------------

    def reconcile_home(
        self,
        all_devices: list[dict],
        dedicated_devices: list[dict],
    ) -> dict:
        """Reconcile all detected devices across the home.

        Args:
            all_devices: all detected devices from shared circuits
                [{name, power_w, circuit_name, confidence, ...}]
            dedicated_devices: known devices on dedicated circuits
                [{name, device_type, circuit_name, power_w}]

        Returns:
            {"corrections": [...], "missing_devices": [...], "duplicates": [...]}
        """
        ded_str = "\n".join(
            f"  - {d['circuit_name']}: {d.get('device_type', d.get('name', '?'))} ({d.get('power_w', '?')}W)"
            for d in dedicated_devices
        ) or "None"

        det_str = "\n".join(
            f"  - {d.get('circuit_name', '?')}: {d.get('name', '?')} ({d.get('power_w', '?')}W, confidence={d.get('confidence', '?')})"
            for d in all_devices
        ) or "None"

        prompt = f"""Review ALL devices detected in this New England home and check for problems.

DEDICATED CIRCUITS (known, high confidence):
{ded_str}

DETECTED DEVICES ON SHARED CIRCUITS:
{det_str}

Check for:
1. MISIDENTIFICATIONS: Is any detected device likely wrong? (e.g., "Heat Pump" on a sub-panel when there are already 5 heat pumps on dedicated circuits)
2. DUPLICATES: Are the same physical device detected on multiple circuits? (wiring error or detection artifact)
3. MISSING DEVICES: Common household devices NOT found anywhere. Consider: lighting, refrigerator, dishwasher, washing machine, computers, TV/entertainment, water heater, sump pump, dehumidifier.

Return ONLY a JSON object:
{{
  "corrections": [{{"circuit": "...", "current_name": "...", "suggested_name": "...", "reasoning": "..."}}],
  "missing_devices": [{{"name": "...", "expected_power_w": 0, "reasoning": "..."}}],
  "duplicates": [{{"device_name": "...", "circuits": ["..."], "reasoning": "..."}}]
}}"""

        try:
            msg = self.client.messages.create(
                model=SONNET_MODEL,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            result = _safe_parse_json(msg.content[0].text)
            if result and isinstance(result, dict):
                return {
                    "corrections": result.get("corrections", []),
                    "missing_devices": result.get("missing_devices", []),
                    "duplicates": result.get("duplicates", []),
                }
        except anthropic.APIError as e:
            logger.warning("Claude home reconciliation failed: %s", e)

        return {"corrections": [], "missing_devices": [], "duplicates": []}

    # ------------------------------------------------------------------
    # Batch runner — called from profiler
    # ------------------------------------------------------------------

    def run_all(
        self,
        profiles: list[dict],
        source: TempIQSource | None = None,
        signature_matches_map: dict | None = None,
        ml_predictions_map: dict | None = None,
    ) -> dict:
        """Run all three modes in sequence.

        Args:
            profiles: list of circuit profile dicts (from circuit_profiles table or CircuitProfile objects)
            source: TempIQSource for fetching 24h power data
            signature_matches_map: {equipment_id: [SignatureMatch dicts]} per circuit
            ml_predictions_map: {equipment_id: {cluster_id: [(device_type, prob)]}}

        Returns:
            {"adjudications": {...}, "circuit_stories": {...}, "reconciliation": {...}}
        """
        sig_map = signature_matches_map or {}
        ml_map = ml_predictions_map or {}

        adjudications: dict[str, list[dict]] = {}
        circuit_stories: dict[str, list[dict]] = {}

        # --- Mode A: Adjudicate each device ---
        for profile in profiles:
            eid = profile.get("equipment_id", "")
            circuit_name = profile.get("circuit_name", "")
            is_dedicated = profile.get("is_dedicated", False)
            if is_dedicated:
                continue

            shape_devices = profile.get("shape_devices") or []
            if isinstance(shape_devices, str):
                shape_devices = json.loads(shape_devices)

            device_adjudications = []
            for sd in shape_devices:
                cluster_id = sd.get("cluster_id", 0)
                sig_matches = sig_map.get(eid, [])
                ml_preds = ml_map.get(eid, {}).get(cluster_id, [])

                result = self.adjudicate_device(sd, sig_matches, ml_preds, circuit_name)
                result["cluster_id"] = cluster_id
                device_adjudications.append(result)

                time.sleep(RATE_LIMIT_SLEEP)

            if device_adjudications:
                adjudications[eid] = device_adjudications

        # --- Mode B: Circuit stories for sub-panels ---
        if source:
            now = datetime.now(timezone.utc)
            start_24h = now - timedelta(hours=24)

            for profile in profiles:
                eid = profile.get("equipment_id", "")
                circuit_name = profile.get("circuit_name", "")
                is_dedicated = profile.get("is_dedicated", False)
                if is_dedicated:
                    continue

                # Only run circuit story on sub-panels (most value there)
                is_subpanel = any(
                    kw in circuit_name.lower()
                    for kw in ("sub panel", "subpanel", "sub-panel")
                )
                if not is_subpanel:
                    continue

                try:
                    agg_df = source.get_aggregated_power(start_24h, now)
                    circuit_data = agg_df[agg_df["circuit_id"] == eid].sort_values("timestamp")
                    if circuit_data.empty:
                        continue

                    power_series = circuit_data["power_w"].tolist()
                    ts_series = [str(t) for t in circuit_data["timestamp"].tolist()]

                    # Known devices on this circuit
                    known = []
                    adj_list = adjudications.get(eid, [])
                    for a in adj_list:
                        known.append(a.get("name", "Unknown"))
                    shape_devices = profile.get("shape_devices") or []
                    if isinstance(shape_devices, str):
                        shape_devices = json.loads(shape_devices)
                    for sd in shape_devices:
                        n = sd.get("name", "")
                        if n and n not in known:
                            known.append(n)

                    story = self.analyze_circuit(circuit_name, power_series, ts_series, known)
                    if story:
                        circuit_stories[eid] = story

                    time.sleep(RATE_LIMIT_SLEEP)
                except Exception as e:
                    logger.warning("Circuit story failed for %s: %s", circuit_name, e)

        # --- Mode C: Home reconciliation ---
        all_detected = []
        dedicated_devices = []

        for profile in profiles:
            eid = profile.get("equipment_id", "")
            circuit_name = profile.get("circuit_name", "")
            is_dedicated = profile.get("is_dedicated", False)

            if is_dedicated:
                dedicated_devices.append({
                    "circuit_name": circuit_name,
                    "device_type": profile.get("dedicated_device_type", ""),
                    "name": profile.get("dedicated_device_type", ""),
                    "power_w": profile.get("baseload_w", 0),
                })
                continue

            shape_devices = profile.get("shape_devices") or []
            if isinstance(shape_devices, str):
                shape_devices = json.loads(shape_devices)

            for sd in shape_devices:
                # Use adjudicated name if available
                cluster_id = sd.get("cluster_id", 0)
                adj_list = adjudications.get(eid, [])
                adj_name = None
                for a in adj_list:
                    if a.get("cluster_id") == cluster_id:
                        adj_name = a.get("name")
                        break

                all_detected.append({
                    "circuit_name": circuit_name,
                    "name": adj_name or sd.get("name", "Unknown"),
                    "power_w": sd.get("avg_power_w", 0),
                    "confidence": sd.get("confidence", 0),
                })

        reconciliation = self.reconcile_home(all_detected, dedicated_devices)
        time.sleep(RATE_LIMIT_SLEEP)

        return {
            "adjudications": adjudications,
            "circuit_stories": circuit_stories,
            "reconciliation": reconciliation,
        }
