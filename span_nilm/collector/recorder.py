"""Data recorder - persists SPAN snapshots to time-series storage.

Stores circuit power readings as Parquet or CSV files, partitioned by date,
enabling efficient historical analysis for device detection.
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from span_nilm.collector.span_client import SpanClient
from span_nilm.utils.config import Config

logger = logging.getLogger("span_nilm.recorder")


class DataRecorder:
    """Records SPAN circuit snapshots to disk."""

    def __init__(self, config: Config):
        self.config = config
        self.client = SpanClient(config.span)
        self.data_dir = Path(config.storage.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.format = config.storage.format

    def _snapshot_to_rows(self, snapshot: dict) -> list[dict]:
        """Flatten a snapshot into rows suitable for a DataFrame."""
        ts = snapshot["timestamp"]
        rows = []
        for circuit_id, data in snapshot["circuits"].items():
            rows.append({
                "timestamp": ts,
                "circuit_id": circuit_id,
                "circuit_name": data["name"],
                "power_w": data["instant_power_w"],
                "imported_wh": data["imported_energy_wh"],
                "exported_wh": data["exported_energy_wh"],
                "relay_state": data["relay_state"],
            })
        return rows

    def _save_chunk(self, df: pd.DataFrame, date_str: str) -> Path:
        """Append data to the day's file."""
        if self.format == "parquet":
            path = self.data_dir / f"{date_str}.parquet"
            if path.exists():
                existing = pd.read_parquet(path)
                df = pd.concat([existing, df], ignore_index=True)
            df.to_parquet(path, index=False)
        else:
            path = self.data_dir / f"{date_str}.csv"
            header = not path.exists()
            df.to_csv(path, mode="a", index=False, header=header)
        return path

    def record_snapshot(self) -> pd.DataFrame | None:
        """Take a single snapshot and save it. Returns the DataFrame."""
        try:
            snapshot = self.client.snapshot()
        except Exception as e:
            logger.error("Failed to collect snapshot: %s", e)
            return None

        rows = self._snapshot_to_rows(snapshot)
        if not rows:
            logger.warning("Empty snapshot - no circuit data")
            return None

        df = pd.DataFrame(rows)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self._save_chunk(df, date_str)
        logger.debug("Saved %d readings to %s", len(rows), path)
        return df

    def run_continuous(self, duration_seconds: int | None = None):
        """Continuously record snapshots at the configured interval.

        Args:
            duration_seconds: If set, stop after this many seconds. None = run forever.
        """
        interval = self.config.span.poll_interval_seconds
        logger.info(
            "Starting continuous recording every %ds (duration=%s)",
            interval,
            f"{duration_seconds}s" if duration_seconds else "infinite",
        )

        start = time.time()
        count = 0
        while True:
            self.record_snapshot()
            count += 1

            if duration_seconds and (time.time() - start) >= duration_seconds:
                logger.info("Recording complete: %d snapshots in %ds", count, duration_seconds)
                break

            time.sleep(interval)

    def load_historical(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        """Load historical data from stored files.

        Args:
            start_date: ISO date string (YYYY-MM-DD), inclusive
            end_date: ISO date string (YYYY-MM-DD), inclusive

        Returns:
            DataFrame with all readings in the date range.
        """
        ext = ".parquet" if self.format == "parquet" else ".csv"
        files = sorted(self.data_dir.glob(f"*{ext}"))

        if start_date:
            files = [f for f in files if f.stem >= start_date]
        if end_date:
            files = [f for f in files if f.stem <= end_date]

        if not files:
            logger.warning("No data files found for date range %s to %s", start_date, end_date)
            return pd.DataFrame()

        dfs = []
        for f in files:
            if ext == ".parquet":
                dfs.append(pd.read_parquet(f))
            else:
                dfs.append(pd.read_csv(f))

        df = pd.concat(dfs, ignore_index=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values(["circuit_id", "timestamp"]).reset_index(drop=True)
        logger.info("Loaded %d readings from %d files", len(df), len(files))
        return df
