"""Circuit profiler — identifies distinct power states and devices on each circuit.

Analyzes 30+ days of historical power data to find histogram peaks (power states),
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


class CircuitProfiler:
    """Profiles circuits by finding distinct power states from historical data."""

    def __init__(
        self,
        source: TempIQSource | None = None,
        spannilm_db_url: str | None = None,
        signatures_file: str = "./device_signatures.yaml",
        data_days: int = 30,
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

        logger.info("Fetching %d days of readings (%s to %s)", self.data_days, start, now)
        df = self.source.get_readings(start, now)
        if df.empty:
            logger.warning("No readings returned")
            return []

        logger.info("Got %d readings across %d circuits", len(df), df["circuit_id"].nunique())

        # Load circuit configs from SpanNILM DB
        configs = self._load_circuit_configs()

        # Build dedicated circuit reference profiles for cross-matching
        dedicated_refs = self._build_dedicated_references(df, configs)

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
                cid, circuit_name, group, is_dedicated, device_type, dedicated_refs
            )

            # Add temporal analysis
            if not is_dedicated:
                profile.temporal = self.temporal.analyze_circuit(cid, circuit_name, group)

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
        dedicated_refs: dict[str, float],
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

        # Match devices to states
        self._match_devices(states, dedicated_refs, is_dedicated, device_type)

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

    def _match_devices(
        self,
        states: list[PowerState],
        dedicated_refs: dict[str, float],
        is_dedicated: bool,
        device_type: str | None,
    ):
        """Match each power state against signatures and dedicated references."""
        for state in states:
            # If this is a dedicated circuit, label with the known device
            if is_dedicated and device_type:
                state.device_name = device_type
                state.confidence = 1.0
                continue

            best_name = None
            best_conf = 0.0

            # 1. Check against dedicated circuit reference profiles
            for dev_type, ref_power in dedicated_refs.items():
                if abs(state.center_w - ref_power) / max(ref_power, 1) < 0.15:
                    conf = 0.7  # good match to a known device
                    if conf > best_conf:
                        best_conf = conf
                        best_name = dev_type

            # 2. Check against signature library
            matches = self.signatures.match(
                power_w=state.center_w,
                duration_s=state.avg_duration_min * 60 if state.avg_duration_min > 0 else None,
            )
            if matches and matches[0].confidence > best_conf:
                best_conf = matches[0].confidence
                best_name = matches[0].device_name

            if best_name and best_conf >= 0.3:
                state.device_name = best_name
                state.confidence = round(best_conf, 2)

    def save_profiles(self, profiles: list[CircuitProfile]) -> int:
        """Save profiles to SpanNILM database. Returns number saved."""
        import json
        conn = psycopg2.connect(self.db_url)
        try:
            with conn.cursor() as cur:
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

                    cur.execute(
                        """
                        INSERT INTO circuit_profiles
                            (equipment_id, circuit_name, is_dedicated, dedicated_device_type,
                             states, total_readings, active_pct, baseload_w, data_days,
                             temporal, correlations)
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
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
                            correlations = EXCLUDED.correlations
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
