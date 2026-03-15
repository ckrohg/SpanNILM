"""Abstract base class for data sources."""

from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd


class DataSource(ABC):
    """Abstract base - any source that can provide circuit power readings.

    All sources must return DataFrames with columns:
        timestamp, circuit_id, circuit_name, power_w
    """

    @abstractmethod
    def get_readings(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Fetch circuit power readings for a time range."""
        ...

    @abstractmethod
    def get_circuits(self) -> list[dict]:
        """Return list of available circuits with metadata."""
        ...
