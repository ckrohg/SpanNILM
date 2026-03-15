"""Circuit profiler — identifies distinct power states and devices on each circuit.

Analyzes 90 days of historical power data to find histogram peaks (power states),
then matches those states against known device signatures and dedicated circuit
reference profiles.
"""

import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

from span_nilm.collector.sources.tempiq_source import TempIQSource
from span_nilm.models.signatures import SignatureLibrary
from span_nilm.profiler.shape_detector import ShapeDetector
from span_nilm.profiler.temporal_analyzer import TemporalAnalyzer, TemporalProfile

logger = logging.getLogger("span_nilm.profiler")

BUCKET_WIDTH_W = 25
PEAK_MERGE_DISTANCE_W = 75
MIN_PEAK_PCT = 0.01  # 1% of readings
STATE_TOLERANCE_W = 50  # ±50W from peak center for duration tracking


@dataclass
class PowerState:
    center_w: float
    count: int
    pct_of_time: float
    avg_duration_min: float
    peak_hours: list[int] = field(default_factory=list)
    device_name: Optional[str] = None
    confidence: float = 0.0


@dataclass
class CircuitProfile:
    equipment_id: str
    circuit_name: str
    is_dedicated: bool
    dedicated_device_type: Optional[str] = None
    states: list[PowerState] = field(default_factory=list)
    total_readings: int = 0
    active_pct: float = 0.0
    baseload_w: float = 0.0
    temporal: Optional[TemporalProfile] = None
    correlations: list[tuple[str, str, float]] = field(default_factory=list)  # (equip_id, name, score)
    shape_devices: list = field(default_factory=list)  # DeviceTemplate objects from shape detection


class CircuitProfiler:
    """Profiles circuits by finding distinct power states from historical data."""

    def __init__(
        self,
        source: TempIQSource | None = None,
        spannilm_db_url: str | None = None,
        signatures_file: str = "./device_signatures.yaml",
        data_days: int = 90,
    ):
        self.source = source or TempIQSource()
        self.db_url = spannilm_db_url or os.environ["SPANNILM_DATABASE_URL"]
        self.signatures = SignatureLibrary(signatures_file)
        self.data_days = data_days
        self.temporal = TemporalAnalyzer(min_power_w=15)

    def profile_all(self) -> list[CircuitProfile]:
        """Profile every circuit and return results."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=self.data_days)

        # Fetch both raw readings (for histogram/temporal) and aggregated (for shape detection)
        logger.info("Fetching %d days of readings (%s to %s)", self.data_days, start, now)
        df = self.source.get_readings(start, now)
        if df.empty:
            logger.warning("No readings returned")
            return []

        logger.info("Got %d raw readings across %d circuits", len(df), df["circuit_id"].nunique())

        # Fetch 10-min aggregated data for shape detection (much better resolution)
        agg_df = self.source.get_aggregated_power(start, now)
        logger.info("Got %d aggregated power readings", len(agg_df))

        # Load circuit configs from SpanNILM DB
        configs = self._load_circuit_configs()

        # Profile each circuit (power states + temporal)
        profiles: list[CircuitProfile] = []
        circuit_names_map: dict[str, str] = {}
        for circuit_id, group in df.groupby("circuit_id"):
            cid = str(circuit_id)
            config = configs.get(cid, {})
            circuit_name = config.get("user_label") or group["circuit_name"].iloc[0]
            is_dedicated = config.get("is_dedicated", False)
            device_type = config.get("dedicated_device_type")
            circuit_names_map[cid] = circuit_name

            group = group.sort_values("timestamp").reset_index(drop=True)

            profile = self._profile_circuit(
                cid, circuit_name, group, is_dedicated, device_type
            )

            # Add temporal analysis and shape detection for shared circuits
            if not is_dedicated:
                # Use aggregated data for shape detection (10-min resolution)
                agg_group = agg_df[agg_df["circuit_id"] == cid].sort_values("timestamp").reset_index(drop=True)
                shape_data = agg_group if not agg_group.empty else group

                profile.temporal = self.temporal.analyze_circuit(cid, circuit_name, shape_data)
                # Run shape-based device detection on aggregated data
                try:
                    shape_det = ShapeDetector()
                    profile.shape_devices = shape_det.detect_devices(circuit_name, shape_data)
                    if profile.shape_devices:
                        logger.info(
                            "Shape detector found %d devices on %s",
                            len(profile.shape_devices), circuit_name,
                        )
                except Exception as e:
                    logger.warning("Shape detection failed on %s: %s", circuit_name, e)

            profiles.append(profile)

        # Find cross-circuit correlations
        logger.info("Computing cross-circuit correlations...")
        shared_ids = [p.equipment_id for p in profiles if not p.is_dedicated]
        corr_map = self.temporal.find_correlations(df, shared_ids)
        for p in profiles:
            if p.equipment_id in corr_map:
                p.correlations = [
                    (cid, circuit_names_map.get(cid, cid), score)
                    for cid, score in corr_map[p.equipment_id][:5]
                ]

        logger.info("Profiled %d circuits, found %d total power states",
                     len(profiles), sum(len(p.states) for p in profiles))
        return profiles

    def _load_circuit_configs(self) -> dict[str, dict]:
        """Load circuit configs from SpanNILM DB."""
        conn = psycopg2.connect(self.db_url)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM circuits")
                return {row["tempiq_equipment_id"]: dict(row) for row in cur.fetchall()}
        finally:
            conn.close()

    def _build_dedicated_references(
        self, df: pd.DataFrame, configs: dict[str, dict]
    ) -> dict[str, float]:
        """Extract reference power levels from dedicated circuits.

        Returns a dict mapping device_type -> typical_power_w.
        """
        refs: dict[str, float] = {}
        for cid, config in configs.items():
            if not config.get("is_dedicated") or not config.get("dedicated_device_type"):
                continue
            circuit_data = df[df["circuit_id"] == cid]
            if circuit_data.empty:
                continue
            active = circuit_data[circuit_data["power_w"] > 5]["power_w"]
            if len(active) > 10:
                refs[config["dedicated_device_type"]] = float(active.median())
        return refs

    def _profile_circuit(
        self,
        circuit_id: str,
        circuit_name: str,
        group: pd.DataFrame,
        is_dedicated: bool,
        device_type: str | None,
    ) -> CircuitProfile:
        """Profile a single circuit's power data."""
        power = group["power_w"].values.astype(float)
        timestamps = pd.to_datetime(group["timestamp"])
        total_readings = len(power)

        # Active percentage
        active_mask = power > 5
        active_pct = float(active_mask.sum()) / total_readings * 100 if total_readings > 0 else 0.0

        # Baseload: 5th percentile of all readings
        baseload_w = float(np.percentile(power, 5)) if total_readings > 0 else 0.0

        # Filter to active readings for histogram analysis
        active_power = power[active_mask]
        active_timestamps = timestamps[active_mask]

        if len(active_power) < 10:
            return CircuitProfile(
                equipment_id=circuit_id,
                circuit_name=circuit_name,
                is_dedicated=is_dedicated,
                dedicated_device_type=device_type,
                states=[],
                total_readings=total_readings,
                active_pct=round(active_pct, 2),
                baseload_w=round(baseload_w, 2),
            )

        # Find histogram peaks
        states = self._find_power_states(
            active_power, active_timestamps, power, timestamps
        )

        # Match devices to states using circuit name as primary signal
        self._match_devices(states, circuit_name, is_dedicated, device_type)

        return CircuitProfile(
            equipment_id=circuit_id,
            circuit_name=circuit_name,
            is_dedicated=is_dedicated,
            dedicated_device_type=device_type,
            states=states,
            total_readings=total_readings,
            active_pct=round(active_pct, 2),
            baseload_w=round(baseload_w, 2),
        )

    def _find_power_states(
        self,
        active_power: np.ndarray,
        active_timestamps: pd.Series,
        all_power: np.ndarray,
        all_timestamps: pd.Series,
    ) -> list[PowerState]:
        """Find distinct power states via histogram peak detection."""
        # Bin into buckets
        max_power = float(active_power.max())
        n_bins = max(1, int(max_power / BUCKET_WIDTH_W) + 1)
        bin_edges = np.arange(0, (n_bins + 1) * BUCKET_WIDTH_W, BUCKET_WIDTH_W)
        counts, _ = np.histogram(active_power, bins=bin_edges)

        total_active = len(active_power)
        threshold = total_active * MIN_PEAK_PCT

        # Find bins above threshold
        raw_peaks: list[tuple[float, int]] = []
        for i, count in enumerate(counts):
            if count >= threshold:
                center = bin_edges[i] + BUCKET_WIDTH_W / 2
                raw_peaks.append((center, int(count)))

        # Merge nearby peaks
        merged_peaks = self._merge_peaks(raw_peaks)

        # For each peak, compute temporal statistics
        states: list[PowerState] = []
        for center_w, count in merged_peaks:
            pct = count / len(all_power) * 100  # pct of ALL readings (including zero)

            # Time-of-day distribution
            mask = np.abs(active_power - center_w) <= STATE_TOLERANCE_W
            peak_ts = active_timestamps[mask]
            if len(peak_ts) > 0:
                hours = peak_ts.dt.hour
                hour_counts = hours.value_counts()
                top_hours = hour_counts.nlargest(3).index.tolist()
            else:
                top_hours = []

            # Average duration of continuous blocks at this power level
            avg_dur = self._compute_avg_duration(
                all_power, all_timestamps, center_w
            )

            states.append(PowerState(
                center_w=round(center_w, 1),
                count=count,
                pct_of_time=round(pct, 2),
                avg_duration_min=round(avg_dur, 1),
                peak_hours=top_hours,
            ))

        # Sort by power level
        states.sort(key=lambda s: s.center_w)
        return states

    def _merge_peaks(
        self, peaks: list[tuple[float, int]]
    ) -> list[tuple[float, int]]:
        """Merge peaks within PEAK_MERGE_DISTANCE_W of each other."""
        if not peaks:
            return []

        peaks = sorted(peaks, key=lambda p: p[0])
        merged: list[tuple[float, int]] = [peaks[0]]

        for center, count in peaks[1:]:
            prev_center, prev_count = merged[-1]
            if center - prev_center <= PEAK_MERGE_DISTANCE_W:
                # Weighted average center, sum counts
                total = prev_count + count
                new_center = (prev_center * prev_count + center * count) / total
                merged[-1] = (new_center, total)
            else:
                merged.append((center, count))

        return merged

    def _compute_avg_duration(
        self,
        all_power: np.ndarray,
        all_timestamps: pd.Series,
        center_w: float,
    ) -> float:
        """Compute average duration of continuous blocks near center_w (in minutes)."""
        in_state = np.abs(all_power - center_w) <= STATE_TOLERANCE_W
        durations: list[float] = []
        block_start = None

        ts_values = all_timestamps.values  # numpy datetime64 array for speed

        for i in range(len(in_state)):
            if in_state[i]:
                if block_start is None:
                    block_start = i
            else:
                if block_start is not None:
                    # End of block
                    dt = (ts_values[i - 1] - ts_values[block_start])
                    dur_min = dt / np.timedelta64(1, "m")
                    if dur_min > 0:
                        durations.append(dur_min)
                    block_start = None

        # Handle block at end
        if block_start is not None and block_start < len(ts_values) - 1:
            dt = (ts_values[-1] - ts_values[block_start])
            dur_min = dt / np.timedelta64(1, "m")
            if dur_min > 0:
                durations.append(dur_min)

        return float(np.mean(durations)) if durations else 0.0

    @staticmethod
    def _parse_circuit_context(circuit_name: str) -> tuple[str | None, dict]:
        """Parse circuit name for keywords to determine circuit purpose.

        Returns (context_type, metadata) where context_type is one of:
        'hydronic', 'garage_door', 'lights_outlets', 'sub_panel',
        'ev_charger', 'well_pump', 'hvac', 'water_heater', 'range',
        'dryer', 'washer', 'dishwasher', 'refrigerator', 'sump_pump',
        'pool_pump', or None if no clear context.
        """
        name_lower = circuit_name.lower()
        metadata: dict = {}

        # Hydronic / zone pumps / boiler
        if any(kw in name_lower for kw in ("hydronic", "zone pump", "boiler", "circulator")):
            return "hydronic", metadata

        # Garage door
        if "garage" in name_lower and ("door" in name_lower or "opener" in name_lower):
            return "garage_door", metadata

        # Lighting / outlets
        if any(kw in name_lower for kw in ("light", "outlet", "lamp", "sconce")):
            return "lights_outlets", metadata

        # Sub panel
        if "sub panel" in name_lower or "subpanel" in name_lower:
            # Extract location if present
            for loc in ("barn", "basement", "2nd floor", "second floor", "upstairs",
                        "garage", "workshop", "shed"):
                if loc in name_lower:
                    metadata["location"] = loc
                    break
            return "sub_panel", metadata

        # Specific dedicated-style circuits identified by name
        if "ev" in name_lower and ("charger" in name_lower or "charge" in name_lower):
            return "ev_charger", metadata
        if "well" in name_lower and "pump" in name_lower:
            return "well_pump", metadata
        if any(kw in name_lower for kw in ("hvac", "compressor", "air condition", "heat pump",
                                            "mini split", "furnace", "air handler")):
            return "hvac", metadata
        if "water heater" in name_lower or "hot water" in name_lower:
            return "water_heater", metadata
        if "range" in name_lower or "oven" in name_lower or "stove" in name_lower:
            return "range", metadata
        if "dryer" in name_lower:
            return "dryer", metadata
        if "washer" in name_lower and "dish" not in name_lower:
            return "washer", metadata
        if "dishwasher" in name_lower:
            return "dishwasher", metadata
        if "refrigerator" in name_lower or "fridge" in name_lower:
            return "refrigerator", metadata
        if "sump" in name_lower:
            return "sump_pump", metadata
        if "pool" in name_lower and "pump" in name_lower:
            return "pool_pump", metadata
        if "pump" in name_lower:
            return "pump", metadata

        return None, metadata

    @staticmethod
    def _format_power_label(power_w: float) -> str:
        """Format a power level as a human-readable label like '~300W load'."""
        if power_w >= 1000:
            return f"~{power_w / 1000:.1f}kW load"
        return f"~{power_w:.0f}W load"

    def _match_devices(
        self,
        states: list[PowerState],
        circuit_name: str,
        is_dedicated: bool,
        device_type: str | None,
    ):
        """Match each power state using circuit name as primary signal.

        Strategy:
        1. If dedicated circuit, label all states with the known device type.
        2. Parse circuit name for keywords that identify purpose.
        3. If circuit purpose is clear, label states contextually.
        4. Only fall back to signature library when name gives no context.
        5. If still no match, label with power level description.
        """
        # Dedicated circuits: label everything with the known device
        if is_dedicated and device_type:
            for state in states:
                state.device_name = device_type
                state.confidence = 1.0
            return

        context_type, metadata = self._parse_circuit_context(circuit_name)

        if context_type == "hydronic":
            self._label_hydronic_states(states)
            return
        elif context_type == "garage_door":
            self._label_garage_door_states(states)
            return
        elif context_type == "lights_outlets":
            self._label_lights_outlets_states(states)
            return
        elif context_type == "sub_panel":
            location = metadata.get("location", "")
            self._label_sub_panel_states(states, location)
            return
        elif context_type in ("ev_charger", "well_pump", "hvac", "water_heater",
                              "range", "dryer", "washer", "dishwasher",
                              "refrigerator", "sump_pump", "pool_pump", "pump"):
            # Circuit name clearly identifies the device — label all states
            label_map = {
                "ev_charger": "EV Charger",
                "well_pump": "Well Pump",
                "hvac": "HVAC",
                "water_heater": "Water Heater",
                "range": "Oven / Range",
                "dryer": "Dryer",
                "washer": "Washer",
                "dishwasher": "Dishwasher",
                "refrigerator": "Refrigerator",
                "sump_pump": "Sump Pump",
                "pool_pump": "Pool Pump",
                "pump": "Pump",
            }
            label = label_map[context_type]
            for state in states:
                state.device_name = label
                state.confidence = 0.85
            return

        # No clear context from circuit name — try signature library
        for state in states:
            matches = self.signatures.match(
                power_w=state.center_w,
                duration_s=state.avg_duration_min * 60 if state.avg_duration_min > 0 else None,
            )
            # Only accept high-confidence signature matches (>= 0.5)
            if matches and matches[0].confidence >= 0.5:
                state.device_name = matches[0].device_name
                state.confidence = round(matches[0].confidence, 2)
            else:
                # Fall back to power-level description
                state.device_name = self._format_power_label(state.center_w)
                state.confidence = 0.0

    def _label_hydronic_states(self, states: list[PowerState]):
        """Label states on a hydronic zone pump circuit.

        States are typically multiples of a base pump power (~250-350W),
        representing 1, 2, 3, etc. pumps running simultaneously.
        Small states (<100W) are control/standby power.
        """
        if not states:
            return

        # Separate small standby/control states from pump states
        pump_states = [s for s in states if s.center_w >= 100]
        standby_states = [s for s in states if s.center_w < 100]

        # Label standby states
        for state in standby_states:
            state.device_name = "Hydronic control/standby"
            state.confidence = 0.8

        if not pump_states:
            return

        # Find the base pump power (smallest pump state)
        base_power = pump_states[0].center_w

        for state in pump_states:
            if base_power > 0:
                n_pumps = max(1, round(state.center_w / base_power))
                if n_pumps == 1:
                    state.device_name = "Zone pump (1 pump)"
                else:
                    state.device_name = f"Zone pumps ({n_pumps} pumps)"
                state.confidence = 0.9
            else:
                state.device_name = self._format_power_label(state.center_w)
                state.confidence = 0.0

    def _label_garage_door_states(self, states: list[PowerState]):
        """Label states on a garage door opener circuit.

        Brief high-power states = motor (door opening/closing).
        Sustained low-power states = standby/light.
        """
        for state in states:
            if state.avg_duration_min < 2 and state.center_w > 200:
                state.device_name = "Garage door motor"
                state.confidence = 0.9
            elif state.center_w < 100:
                state.device_name = "Garage door standby"
                state.confidence = 0.8
            elif state.center_w >= 100 and state.center_w < 300:
                state.device_name = "Garage door light"
                state.confidence = 0.7
            else:
                state.device_name = "Garage door motor"
                state.confidence = 0.7

    def _label_lights_outlets_states(self, states: list[PowerState]):
        """Label states on a lights/outlets circuit."""
        for state in states:
            if state.center_w < 200:
                state.device_name = "Lighting"
                state.confidence = 0.7
            elif state.center_w < 500:
                state.device_name = "Lighting / small appliance"
                state.confidence = 0.6
            else:
                state.device_name = f"Outlet load ({self._format_power_label(state.center_w)})"
                state.confidence = 0.5

    def _label_sub_panel_states(self, states: list[PowerState], location: str):
        """Label states on a sub-panel circuit."""
        loc_prefix = f"{location.title()} " if location else ""
        for state in states:
            state.device_name = f"{loc_prefix}sub-panel load ({self._format_power_label(state.center_w)})"
            state.confidence = 0.3

    def save_profiles(self, profiles: list[CircuitProfile]) -> int:
        """Save profiles to SpanNILM database. Returns number saved."""
        import json
        from dataclasses import asdict as _asdict
        conn = psycopg2.connect(self.db_url)
        try:
            with conn.cursor() as cur:
                # Ensure shape_devices column exists
                cur.execute(
                    "ALTER TABLE circuit_profiles ADD COLUMN IF NOT EXISTS shape_devices JSONB DEFAULT '[]'"
                )
                conn.commit()

                for p in profiles:
                    states_json = [
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
                    ]

                    temporal_json = {}
                    if p.temporal:
                        t = p.temporal
                        temporal_json = {
                            "total_sessions": t.total_sessions,
                            "total_hours_on": t.total_hours_on,
                            "duty_cycle_overall": t.duty_cycle_overall,
                            "median_session_min": t.median_session_min,
                            "avg_session_min": t.avg_session_min,
                            "short_sessions": t.short_sessions,
                            "medium_sessions": t.medium_sessions,
                            "long_sessions": t.long_sessions,
                            "has_cycling": t.has_cycling,
                            "hourly_activity": t.hourly_activity,
                            "peak_hours": t.peak_hours,
                            "weekday_vs_weekend": t.weekday_vs_weekend,
                        }
                        if t.cycle_pattern:
                            cp = t.cycle_pattern
                            temporal_json["cycle_pattern"] = {
                                "median_on_min": cp.median_on_min,
                                "median_off_min": cp.median_off_min,
                                "median_period_min": cp.median_period_min,
                                "duty_cycle": cp.duty_cycle,
                                "regularity": cp.regularity,
                                "count": cp.count,
                                "median_power_w": cp.median_power_w,
                                "power_std_w": cp.power_std_w,
                                "peak_hours": cp.peak_hours,
                            }

                    corr_json = [
                        {"equipment_id": cid, "name": name, "score": score}
                        for cid, name, score in p.correlations
                    ]

                    # Serialize shape devices (cast numpy types for JSON)
                    shape_devices_json = []
                    for sd in (p.shape_devices or []):
                        shape_devices_json.append({
                            "cluster_id": int(sd.cluster_id),
                            "name": str(sd.name),
                            "template_curve": [float(v) for v in sd.template_curve],
                            "avg_power_w": float(sd.avg_power_w),
                            "peak_power_w": float(sd.peak_power_w),
                            "avg_duration_min": float(sd.avg_duration_min),
                            "session_count": int(sd.session_count),
                            "sessions_per_day": float(sd.sessions_per_day),
                            "peak_hours": [int(h) for h in sd.peak_hours],
                            "confidence": float(sd.confidence),
                            "num_phases": int(sd.num_phases),
                            "has_startup_surge": bool(sd.has_startup_surge),
                            "is_cycling": bool(sd.is_cycling),
                            "duty_cycle": float(sd.duty_cycle),
                            "energy_per_session_wh": float(sd.energy_per_session_wh),
                        })

                    cur.execute(
                        """
                        INSERT INTO circuit_profiles
                            (equipment_id, circuit_name, is_dedicated, dedicated_device_type,
                             states, total_readings, active_pct, baseload_w, data_days,
                             temporal, correlations, shape_devices)
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                        ON CONFLICT (equipment_id)
                        DO UPDATE SET
                            circuit_name = EXCLUDED.circuit_name,
                            is_dedicated = EXCLUDED.is_dedicated,
                            dedicated_device_type = EXCLUDED.dedicated_device_type,
                            states = EXCLUDED.states,
                            total_readings = EXCLUDED.total_readings,
                            active_pct = EXCLUDED.active_pct,
                            baseload_w = EXCLUDED.baseload_w,
                            profiled_at = now(),
                            data_days = EXCLUDED.data_days,
                            temporal = EXCLUDED.temporal,
                            correlations = EXCLUDED.correlations,
                            shape_devices = EXCLUDED.shape_devices
                        """,
                        (
                            p.equipment_id,
                            p.circuit_name,
                            p.is_dedicated,
                            p.dedicated_device_type,
                            json.dumps(states_json),
                            p.total_readings,
                            p.active_pct,
                            p.baseload_w,
                            self.data_days,
                            json.dumps(temporal_json),
                            json.dumps(corr_json),
                            json.dumps(shape_devices_json),
                        ),
                    )
                conn.commit()
            return len(profiles)
        finally:
            conn.close()

    @staticmethod
    def load_profiles(db_url: str | None = None) -> list[dict]:
        """Load saved profiles from DB."""
        url = db_url or os.environ["SPANNILM_DATABASE_URL"]
        conn = psycopg2.connect(url)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM circuit_profiles ORDER BY circuit_name")
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
