"""Device signature library and matching engine.

Loads known device signatures and matches observed power patterns against them.
This is our equivalent of Sense's "multidomain device signature detection" -
but instead of analyzing waveforms at MHz, we work with power-level patterns
at ~1Hz resolution from SPAN circuits.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("span_nilm.models.signatures")


@dataclass
class DeviceSignature:
    """A known device's power consumption signature."""
    name: str
    category: str
    power_min_w: float
    power_max_w: float
    duration_min_s: float
    duration_max_s: float
    duty_cycle_pattern: str  # cycling, sustained, multi_phase, variable
    startup_surge: bool = False
    surge_multiplier: float = 1.0
    steady_state_variance: float = 0.1
    cycle_period_min_s: float | None = None
    cycle_period_max_s: float | None = None
    notes: str = ""


@dataclass
class SignatureMatch:
    """Result of matching an observed pattern against known signatures."""
    device_name: str
    category: str
    confidence: float  # 0.0 to 1.0
    matched_features: list[str] = field(default_factory=list)
    notes: str = ""


class SignatureLibrary:
    """Manages known device signatures and performs matching."""

    def __init__(self, signatures_file: str = "./device_signatures.yaml"):
        self.signatures: dict[str, DeviceSignature] = {}
        self._load_signatures(signatures_file)

    def _load_signatures(self, path: str):
        """Load device signatures from YAML file."""
        sig_path = Path(path)
        if not sig_path.exists():
            logger.warning("Signatures file not found: %s", path)
            return

        with open(sig_path) as f:
            raw = yaml.safe_load(f) or {}

        devices = raw.get("devices", {})
        for name, data in devices.items():
            power_range = data.get("power_range_w", [0, 10000])
            duration_range = data.get("typical_duration_range_s", [0, 86400])
            sig_data = data.get("signature", {})

            cycle_range = sig_data.get("cycle_period_range_s")

            self.signatures[name] = DeviceSignature(
                name=name,
                category=data.get("category", "Unknown"),
                power_min_w=power_range[0],
                power_max_w=power_range[1],
                duration_min_s=duration_range[0],
                duration_max_s=duration_range[1],
                duty_cycle_pattern=data.get("duty_cycle_pattern", "sustained"),
                startup_surge=sig_data.get("startup_surge", False),
                surge_multiplier=sig_data.get("surge_multiplier", 1.0),
                steady_state_variance=sig_data.get("steady_state_variance", 0.1),
                cycle_period_min_s=cycle_range[0] if cycle_range else None,
                cycle_period_max_s=cycle_range[1] if cycle_range else None,
                notes=data.get("notes", ""),
            )

        logger.info("Loaded %d device signatures", len(self.signatures))

    def match(
        self,
        power_w: float,
        duration_s: float | None = None,
        has_surge: bool = False,
        pattern: str | None = None,
    ) -> list[SignatureMatch]:
        """Match observed characteristics against known device signatures.

        Args:
            power_w: Observed steady-state power draw in watts.
            duration_s: Duration of the device run in seconds.
            has_surge: Whether a startup power surge was observed.
            pattern: Observed duty cycle pattern type.

        Returns:
            List of SignatureMatch objects, sorted by confidence (highest first).
        """
        matches = []

        for name, sig in self.signatures.items():
            confidence = 0.0
            features = []

            # Power range match (most important feature)
            if sig.power_min_w <= power_w <= sig.power_max_w:
                # Score higher when closer to the center of the range
                center = (sig.power_min_w + sig.power_max_w) / 2
                range_width = sig.power_max_w - sig.power_min_w
                distance = abs(power_w - center) / (range_width / 2) if range_width > 0 else 0
                power_score = 1.0 - distance * 0.3
                confidence += power_score * 0.4
                features.append(f"power_match({power_w:.0f}W in [{sig.power_min_w:.0f}-{sig.power_max_w:.0f}])")
            else:
                # Allow slight out-of-range with penalty
                if power_w < sig.power_min_w:
                    overshoot = (sig.power_min_w - power_w) / sig.power_min_w
                else:
                    overshoot = (power_w - sig.power_max_w) / sig.power_max_w
                if overshoot < 0.2:
                    confidence += 0.1
                    features.append(f"power_near({power_w:.0f}W)")
                else:
                    continue  # Too far off - skip this signature

            # Duration match
            if duration_s is not None:
                if sig.duration_min_s <= duration_s <= sig.duration_max_s:
                    confidence += 0.25
                    features.append(f"duration_match({duration_s:.0f}s)")
                elif duration_s < sig.duration_min_s:
                    ratio = duration_s / sig.duration_min_s
                    if ratio > 0.3:
                        confidence += 0.1
                        features.append(f"duration_short({duration_s:.0f}s)")
                elif duration_s > sig.duration_max_s:
                    ratio = sig.duration_max_s / duration_s
                    if ratio > 0.3:
                        confidence += 0.1
                        features.append(f"duration_long({duration_s:.0f}s)")

            # Startup surge match
            if has_surge == sig.startup_surge:
                confidence += 0.15
                features.append("surge_match" if has_surge else "no_surge_match")

            # Duty cycle pattern match
            if pattern and pattern == sig.duty_cycle_pattern:
                confidence += 0.2
                features.append(f"pattern_match({pattern})")

            if confidence >= 0.3:
                matches.append(SignatureMatch(
                    device_name=name,
                    category=sig.category,
                    confidence=min(confidence, 1.0),
                    matched_features=features,
                    notes=sig.notes,
                ))

        matches.sort(key=lambda m: m.confidence, reverse=True)
        return matches
