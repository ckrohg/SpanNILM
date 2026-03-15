"""TempIQ Supabase data source.

Reads SPAN circuit data from TempIQv2's Supabase database and derives
instantaneous power from cumulative energy counters.

The key challenge: instant_power_w is only 1-3% populated in TempIQ.
We derive power from imported_active_energy_wh (cumulative counter)
using the same buildMonotonicEnergy() logic from TempIQv2.
"""

import logging
import os
from datetime import datetime

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

from .base import DataSource

logger = logging.getLogger("span_nilm.sources.tempiq")

READINGS_QUERY = """
SELECT
    r.timestamp,
    r.equipment_id,
    r.imported_active_energy_wh::float AS wh,
    r.instant_power_w::float AS instant_power_w,
    r.relay_state,
    e.name AS circuit_name,
    e.external_id AS circuit_number
FROM span_circuit_readings r
JOIN equipment e ON r.equipment_id = e.id
WHERE r.property_id = %s
  AND r.timestamp >= %s
  AND r.timestamp < %s
ORDER BY r.equipment_id, r.timestamp
"""

CIRCUITS_QUERY = """
SELECT
    e.id AS equipment_id,
    e.name,
    e.external_id AS circuit_number,
    e.metadata
FROM equipment e
JOIN integrations i ON e.integration_id = i.id
WHERE e.property_id = %s
  AND e.type = 'circuit'
  AND i.type IN ('span', 'span_cloud')
  AND e.is_active = 1
ORDER BY e.external_id
"""


class TempIQSource(DataSource):
    """Reads SPAN circuit data from TempIQv2's Supabase."""

    def __init__(
        self,
        database_url: str | None = None,
        property_id: str | None = None,
    ):
        self.database_url = database_url or os.environ["TEMPIQ_DATABASE_URL"]
        self.property_id = property_id or os.environ["TEMPIQ_PROPERTY_ID"]

    def _query(self, sql: str, params: tuple) -> list[dict]:
        """Execute a query and return results, ensuring connection is closed."""
        conn = psycopg2.connect(self.database_url)
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def get_circuits(self) -> list[dict]:
        """Return list of available SPAN circuits from TempIQ's equipment table."""
        return self._query(CIRCUITS_QUERY, (self.property_id,))

    def get_readings(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Fetch circuit readings and derive power from energy counters.

        Returns DataFrame with columns: timestamp, circuit_id, circuit_name, power_w
        """
        rows = self._query(READINGS_QUERY, (self.property_id, start, end))

        if not rows:
            logger.warning("No readings found for %s to %s", start, end)
            return pd.DataFrame(columns=["timestamp", "circuit_id", "circuit_name", "power_w"])

        df = pd.DataFrame(rows)
        logger.info("Fetched %d raw readings from TempIQ", len(df))

        # Derive power per circuit from cumulative energy counters
        result_frames = []
        for equip_id, group in df.groupby("equipment_id"):
            group = group.sort_values("timestamp").reset_index(drop=True)
            power_df = self._derive_power(group, str(equip_id))
            if not power_df.empty:
                result_frames.append(power_df)

        if not result_frames:
            return pd.DataFrame(columns=["timestamp", "circuit_id", "circuit_name", "power_w"])

        result = pd.concat(result_frames, ignore_index=True)
        logger.info(
            "Derived %d power readings across %d circuits",
            len(result), result["circuit_id"].nunique(),
        )
        return result

    def get_power_timeseries(self, equipment_id: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Get power time-series for a single circuit (for timeline charts)."""
        query = """
        SELECT timestamp, imported_active_energy_wh::float AS wh
        FROM span_circuit_readings
        WHERE equipment_id = %s AND timestamp >= %s AND timestamp < %s
        ORDER BY timestamp
        """
        rows = self._query(query, (equipment_id, start, end))

        if len(rows) < 2:
            return pd.DataFrame(columns=["timestamp", "power_w"])

        df = pd.DataFrame(rows)
        return self._energy_to_power(df)

    def _derive_power(self, group: pd.DataFrame, equipment_id: str) -> pd.DataFrame:
        """Convert cumulative energy readings to instantaneous power for one circuit."""
        if len(group) < 2:
            return pd.DataFrame()

        circuit_name = group["circuit_name"].iloc[0]
        power_df = self._energy_to_power(group)

        if power_df.empty:
            return pd.DataFrame()

        power_df["circuit_id"] = equipment_id
        power_df["circuit_name"] = circuit_name
        return power_df[["timestamp", "circuit_id", "circuit_name", "power_w"]]

    def get_current_power(self) -> list[dict]:
        """Get the latest 3 readings per circuit and derive instantaneous power.

        Uses the actual latest timestamp in the data (not NOW()) to avoid
        timezone mismatches between Railway server and Supabase.
        """
        query = """
        WITH ranked AS (
            SELECT
                r.equipment_id,
                e.name AS circuit_name,
                r.timestamp,
                r.imported_active_energy_wh::float AS wh,
                ROW_NUMBER() OVER (PARTITION BY r.equipment_id ORDER BY r.timestamp DESC) AS rn
            FROM span_circuit_readings r
            JOIN equipment e ON r.equipment_id = e.id
            WHERE r.property_id = %s
              AND r.timestamp >= (
                  SELECT MAX(timestamp) - INTERVAL '30 minutes'
                  FROM span_circuit_readings WHERE property_id = %s
              )
            )
        SELECT * FROM ranked WHERE rn <= 3
        ORDER BY equipment_id, timestamp
        """
        rows = self._query(query, (self.property_id, self.property_id))
        if not rows:
            return []

        from collections import defaultdict
        by_equip: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_equip[row["equipment_id"]].append(row)

        results = []
        for equip_id, readings in by_equip.items():
            readings.sort(key=lambda r: r["timestamp"])
            if len(readings) < 2:
                results.append({
                    "equipment_id": equip_id,
                    "circuit_name": readings[0]["circuit_name"],
                    "power_w": 0.0,
                    "timestamp": readings[0]["timestamp"],
                })
                continue

            # Try the last pair; if it's a spike, try the pair before
            for i in range(len(readings) - 1, 0, -1):
                r0, r1 = readings[i - 1], readings[i]
                delta_wh = r1["wh"] - r0["wh"]
                delta_s = (r1["timestamp"] - r0["timestamp"]).total_seconds()
                if delta_s < 10 or delta_wh < 0:
                    power_w = 0.0
                else:
                    power_w = delta_wh / (delta_s / 3600.0)
                    if power_w > 15000:
                        power_w = 0.0
                        continue  # try earlier pair
                break

            results.append({
                "equipment_id": equip_id,
                "circuit_name": r1["circuit_name"],
                "power_w": round(power_w, 1),
                "timestamp": r1["timestamp"],
            })

        return results

    def get_power_timeline(self, start: datetime, end: datetime, bucket_minutes: int = 5) -> list[dict]:
        """Get bucketed average power per circuit for stacked timeline chart."""
        query = """
        WITH energy_readings AS (
            SELECT
                r.equipment_id,
                e.name AS circuit_name,
                r.timestamp,
                r.imported_active_energy_wh::float AS wh,
                LAG(r.imported_active_energy_wh::float) OVER (
                    PARTITION BY r.equipment_id ORDER BY r.timestamp
                ) AS prev_wh,
                LAG(r.timestamp) OVER (
                    PARTITION BY r.equipment_id ORDER BY r.timestamp
                ) AS prev_ts
            FROM span_circuit_readings r
            JOIN equipment e ON r.equipment_id = e.id
            WHERE r.property_id = %s
              AND r.timestamp >= %s
              AND r.timestamp < %s
        ),
        power_derived AS (
            SELECT
                equipment_id,
                circuit_name,
                timestamp,
                CASE
                    WHEN prev_wh IS NULL THEN 0
                    WHEN wh - prev_wh < 0 THEN 0
                    WHEN EXTRACT(EPOCH FROM (timestamp - prev_ts)) < 10 THEN 0
                    WHEN (wh - prev_wh) / (EXTRACT(EPOCH FROM (timestamp - prev_ts)) / 3600.0) > 15000 THEN 0
                    ELSE (wh - prev_wh) / (EXTRACT(EPOCH FROM (timestamp - prev_ts)) / 3600.0)
                END AS power_w
            FROM energy_readings
            WHERE prev_wh IS NOT NULL
        )
        SELECT
            date_trunc('hour', timestamp) + (EXTRACT(MINUTE FROM timestamp)::int / %s * %s) * INTERVAL '1 minute' AS bucket,
            circuit_name,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY power_w) AS avg_power_w
        FROM power_derived
        GROUP BY bucket, circuit_name
        ORDER BY bucket
        """
        rows = self._query(query, (self.property_id, start, end, bucket_minutes, bucket_minutes))
        return rows

    def get_energy_totals(self, start: datetime, end: datetime) -> list[dict]:
        """Get total energy per circuit using monotonic sum of positive deltas.

        Handles counter resets by summing only positive deltas between consecutive
        readings. When counter resets (delta < 0), use the raw value as the delta
        (same as TempIQv2's buildMonotonicEnergy pattern).
        """
        query = """
        WITH energy_readings AS (
            SELECT
                r.equipment_id,
                e.name AS circuit_name,
                r.imported_active_energy_wh::float AS wh,
                LAG(r.imported_active_energy_wh::float) OVER (
                    PARTITION BY r.equipment_id ORDER BY r.timestamp
                ) AS prev_wh
            FROM span_circuit_readings r
            JOIN equipment e ON r.equipment_id = e.id
            WHERE r.property_id = %s
              AND r.timestamp >= %s
              AND r.timestamp < %s
        ),
        deltas AS (
            SELECT
                equipment_id,
                circuit_name,
                CASE
                    WHEN prev_wh IS NULL THEN 0
                    WHEN wh - prev_wh < 0 THEN wh  -- counter reset: use raw value
                    ELSE wh - prev_wh
                END AS delta_wh
            FROM energy_readings
        )
        SELECT
            equipment_id,
            circuit_name,
            SUM(delta_wh) / 1000.0 AS energy_kwh
        FROM deltas
        GROUP BY equipment_id, circuit_name
        """
        rows = self._query(query, (self.property_id, start, end))
        return rows

    def get_always_on(self, start: datetime, end: datetime) -> list[dict]:
        """Get 10th percentile power per circuit as always-on baseline."""
        query = """
        WITH energy_readings AS (
            SELECT
                r.equipment_id,
                e.name AS circuit_name,
                r.timestamp,
                r.imported_active_energy_wh::float AS wh,
                LAG(r.imported_active_energy_wh::float) OVER (
                    PARTITION BY r.equipment_id ORDER BY r.timestamp
                ) AS prev_wh,
                LAG(r.timestamp) OVER (
                    PARTITION BY r.equipment_id ORDER BY r.timestamp
                ) AS prev_ts
            FROM span_circuit_readings r
            JOIN equipment e ON r.equipment_id = e.id
            WHERE r.property_id = %s
              AND r.timestamp >= %s
              AND r.timestamp < %s
        ),
        power_derived AS (
            SELECT
                equipment_id,
                circuit_name,
                CASE
                    WHEN prev_wh IS NULL THEN 0
                    WHEN wh - prev_wh < 0 THEN 0
                    WHEN EXTRACT(EPOCH FROM (timestamp - prev_ts)) < 10 THEN 0
                    WHEN (wh - prev_wh) / (EXTRACT(EPOCH FROM (timestamp - prev_ts)) / 3600.0) > 15000 THEN 0
                    ELSE (wh - prev_wh) / (EXTRACT(EPOCH FROM (timestamp - prev_ts)) / 3600.0)
                END AS power_w
            FROM energy_readings
            WHERE prev_wh IS NOT NULL
        )
        SELECT
            equipment_id,
            circuit_name,
            PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY power_w) AS always_on_w
        FROM power_derived
        GROUP BY equipment_id, circuit_name
        """
        rows = self._query(query, (self.property_id, start, end))
        return rows

    @staticmethod
    def _energy_to_power(df: pd.DataFrame) -> pd.DataFrame:
        """Convert cumulative Wh readings to instantaneous power.

        Ports TempIQv2's buildMonotonicEnergy() logic:
        - Handle counter resets (delta < 0 means reset, use raw value as delta)
        - Compute power = delta_wh / delta_hours
        - Filter outliers
        """
        timestamps = pd.to_datetime(df["timestamp"])
        wh = df["wh"].values.astype(float)

        result_ts = []
        result_power = []

        for i in range(1, len(wh)):
            # Handle counter resets
            delta_wh = wh[i] - wh[i - 1]
            if delta_wh < 0:
                # Counter reset — skip this reading entirely as the delta is unreliable
                result_ts.append(timestamps.iloc[i])
                result_power.append(0.0)
                continue

            delta_seconds = (timestamps.iloc[i] - timestamps.iloc[i - 1]).total_seconds()
            if delta_seconds < 10:  # Skip readings less than 10s apart
                continue

            delta_hours = delta_seconds / 3600.0
            power_w = delta_wh / delta_hours

            # Filter outliers — max 15kW per residential circuit (240V × 60A)
            if power_w > 15000 or power_w < 0:
                result_ts.append(timestamps.iloc[i])
                result_power.append(0.0)
                continue

            result_ts.append(timestamps.iloc[i])
            result_power.append(power_w)

        if not result_ts:
            return pd.DataFrame(columns=["timestamp", "power_w"])

        return pd.DataFrame({"timestamp": result_ts, "power_w": result_power})
