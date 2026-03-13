"""SPAN Panel API client for collecting circuit-level power data.

Modeled after TempIQ v2's approach to harvesting Span data - polling the local
REST API at regular intervals and storing timestamped circuit readings.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from span_nilm.utils.config import SpanConfig

logger = logging.getLogger("span_nilm.collector")


class SpanClient:
    """Client for the SPAN Panel local REST API."""

    def __init__(self, config: SpanConfig):
        self.base_url = f"http://{config.host}"
        self.timeout = config.timeout_seconds
        self._session = requests.Session()
        if config.token:
            self._session.headers["Authorization"] = f"Bearer {config.token}"

    def _get(self, endpoint: str) -> dict[str, Any]:
        """Make a GET request to the SPAN API."""
        url = f"{self.base_url}/api/v1{endpoint}"
        resp = self._session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_status(self) -> dict[str, Any]:
        """Get panel status (firmware, connectivity, serial)."""
        return self._get("/status")

    def get_panel(self) -> dict[str, Any]:
        """Get aggregate panel data including per-branch power."""
        return self._get("/panel")

    def get_circuits(self) -> dict[str, Any]:
        """Get detailed per-circuit data (power, energy, relay state)."""
        return self._get("/circuits")

    def get_storage_soe(self) -> dict[str, Any]:
        """Get battery state of charge if available."""
        return self._get("/storage/soe")

    def snapshot(self) -> dict[str, Any]:
        """Take a complete snapshot of all circuit power readings.

        Returns a dict with timestamp and per-circuit instant power,
        suitable for time-series storage and analysis.
        """
        now = datetime.now(timezone.utc)
        circuits_resp = self.get_circuits()

        readings = {}
        circuits = circuits_resp.get("circuits", circuits_resp)

        for circuit_id, circuit_data in circuits.items():
            if not isinstance(circuit_data, dict):
                continue
            readings[circuit_id] = {
                "name": circuit_data.get("name", circuit_id),
                "instant_power_w": circuit_data.get("instantPowerW", 0.0),
                "imported_energy_wh": circuit_data.get("importedActiveEnergyWh", 0.0),
                "exported_energy_wh": circuit_data.get("exportedActiveEnergyWh", 0.0),
                "relay_state": circuit_data.get("relayState", "UNKNOWN"),
                "priority": circuit_data.get("priority", "UNKNOWN"),
            }

        # Also grab panel-level branch data for solar/aggregate
        try:
            panel_resp = self.get_panel()
            panel_branches = panel_resp.get("branches", [])
            for i, branch in enumerate(panel_branches):
                if isinstance(branch, dict):
                    branch_id = f"branch_{i}"
                    if branch_id not in readings:
                        readings[branch_id] = {
                            "name": f"Branch {i}",
                            "instant_power_w": branch.get("instantPowerW", 0.0),
                            "imported_energy_wh": branch.get("importedActiveEnergyWh", 0.0),
                            "exported_energy_wh": branch.get("exportedActiveEnergyWh", 0.0),
                            "relay_state": "N/A",
                            "priority": "N/A",
                        }
        except Exception as e:
            logger.debug("Could not fetch panel branches: %s", e)

        return {
            "timestamp": now.isoformat(),
            "circuits": readings,
        }
