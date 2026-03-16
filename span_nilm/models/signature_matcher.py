"""Multi-dimensional device signature matcher.

Matches observed power patterns against the expanded device signature database
using weighted scoring across 7 dimensions: power range, duration, cycling pattern,
location context, time-of-day, season, and power stability.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger("span_nilm.models.signature_matcher")

# Location keywords to extract from circuit names
LOCATION_KEYWORDS: dict[str, list[str]] = {
    "barn": ["barn"],
    "basement": ["basement", "bsmt"],
    "upstairs": ["2nd floor", "upstairs", "second floor", "2nd fl"],
    "garage": ["garage", "gar"],
    "kitchen": ["kitchen", "kitch"],
    "office": ["office"],
    "living_room": ["living", "family", "great room"],
    "bedroom": ["bedroom", "bed rm", "master br", "br"],
    "bathroom": ["bathroom", "bath"],
    "laundry": ["laundry"],
    "outdoor": ["outdoor", "outside", "exterior", "patio", "deck"],
    "attic": ["attic"],
    "crawlspace": ["crawl"],
    "utility": ["utility", "mech"],
    "closet": ["closet"],
    "workshop": ["workshop", "shop"],
    "any": [],  # matches everything
}

# Month-to-season mapping (New England perspective)
MONTH_TO_SEASON: dict[int, str] = {
    1: "winter", 2: "winter", 3: "winter",
    4: "spring", 5: "spring", 6: "summer",
    7: "summer", 8: "summer", 9: "fall",
    10: "fall", 11: "winter", 12: "winter",
}


@dataclass
class DeviceSignatureV2:
    """Extended device signature with location, time, and seasonal context."""
    name: str
    category: str
    power_min_w: float
    power_max_w: float
    duration_min_s: float
    duration_max_s: float
    duty_cycle_pattern: str
    startup_surge: bool = False
    surge_multiplier: float = 1.0
    steady_state_variance: float = 0.1
    typical_locations: list[str] = field(default_factory=lambda: ["any"])
    typical_hours: list[int] = field(default_factory=lambda: [0, 24])
    seasonal: str = "year_round"
    cycling_on_s: float | None = None
    cycling_off_s: float | None = None
    power_stability: float = 0.90
    notes: str = ""


@dataclass
class SignatureMatch:
    """Result of multi-dimensional matching."""
    device_name: str
    category: str
    confidence: float  # 0.0 to 1.0
    reasoning: list[str] = field(default_factory=list)
    dimension_scores: dict[str, float] = field(default_factory=dict)


class SignatureMatcher:
    """Multi-dimensional device signature matcher.

    Scores candidates across 7 weighted dimensions:
        1. Power range match      (30%)
        2. Duration match         (15%)
        3. Cycling pattern match  (15%)
        4. Location context       (15%)
        5. Time-of-day match      (10%)
        6. Seasonal match         (10%)
        7. Power stability match  ( 5%)
    """

    # Dimension weights (must sum to 1.0)
    WEIGHTS = {
        "power": 0.30,
        "duration": 0.15,
        "cycling": 0.15,
        "location": 0.15,
        "time_of_day": 0.10,
        "seasonal": 0.10,
        "stability": 0.05,
    }

    def __init__(self, signatures_file: str = "./device_signatures.yaml"):
        self.signatures: dict[str, DeviceSignatureV2] = {}
        self._load_signatures(signatures_file)

    def _load_signatures(self, path: str) -> None:
        """Load device signatures from the expanded YAML format."""
        sig_path = Path(path)
        if not sig_path.exists():
            logger.warning("Signatures file not found: %s", path)
            return

        with open(sig_path) as f:
            raw = yaml.safe_load(f) or {}

        devices = raw.get("devices", {})
        for name, data in devices.items():
            power_range = data.get("power_range", [0, 10000])
            duration_range = data.get("duration_range", [0, 86400])

            # Handle legacy format (power_range_w / typical_duration_range_s)
            if "power_range_w" in data:
                power_range = data["power_range_w"]
            if "typical_duration_range_s" in data:
                duration_range = data["typical_duration_range_s"]

            sig_data = data.get("signature", {})

            self.signatures[name] = DeviceSignatureV2(
                name=name,
                category=data.get("category", "Unknown"),
                power_min_w=power_range[0],
                power_max_w=power_range[1],
                duration_min_s=duration_range[0],
                duration_max_s=duration_range[1],
                duty_cycle_pattern=data.get("duty_cycle_pattern", "sustained"),
                startup_surge=data.get("startup_surge", sig_data.get("startup_surge", False)),
                surge_multiplier=data.get("surge_multiplier", sig_data.get("surge_multiplier", 1.0)),
                steady_state_variance=data.get("steady_state_variance", sig_data.get("steady_state_variance", 0.1)),
                typical_locations=data.get("typical_locations", ["any"]),
                typical_hours=data.get("typical_hours", [0, 24]),
                seasonal=data.get("seasonal", "year_round"),
                cycling_on_s=data.get("cycling_on_s"),
                cycling_off_s=data.get("cycling_off_s"),
                power_stability=data.get("power_stability", 0.90),
                notes=data.get("notes", ""),
            )

        logger.info("Loaded %d device signatures (v2)", len(self.signatures))

    @staticmethod
    def extract_locations(circuit_name: str) -> list[str]:
        """Extract location hints from a circuit name.

        Parses common keywords like 'barn', 'basement', '2nd floor', etc.
        Returns a list of matched location keys.
        """
        name_lower = circuit_name.lower()
        found: list[str] = []
        for location, keywords in LOCATION_KEYWORDS.items():
            if location == "any":
                continue
            for kw in keywords:
                if kw in name_lower:
                    found.append(location)
                    break
        return found

    @staticmethod
    def current_season() -> str:
        """Get the current season based on month (New England perspective)."""
        return MONTH_TO_SEASON.get(datetime.now().month, "year_round")

    def match(
        self,
        power_w: float,
        duration_s: float | None = None,
        is_cycling: bool = False,
        cycling_on_s: float | None = None,
        cycling_off_s: float | None = None,
        power_stability: float | None = None,
        peak_hours: list[int] | None = None,
        circuit_name: str = "",
        season: str | None = None,
    ) -> list[SignatureMatch]:
        """Multi-dimensional matching with context.

        Args:
            power_w: Observed steady-state power in watts.
            duration_s: Duration of the device run in seconds.
            is_cycling: Whether the device shows cycling behavior.
            cycling_on_s: Observed ON duration per cycle in seconds.
            cycling_off_s: Observed OFF duration per cycle in seconds.
            power_stability: Observed power stability (0-1, 1 = perfectly flat).
            peak_hours: List of hours (0-23) when the device is most active.
            circuit_name: Name of the circuit (used for location extraction).
            season: Override season; defaults to current month.

        Returns:
            Top-5 SignatureMatch results sorted by confidence (highest first).
        """
        if season is None:
            season = self.current_season()

        circuit_locations = self.extract_locations(circuit_name) if circuit_name else []

        candidates: list[SignatureMatch] = []

        for name, sig in self.signatures.items():
            scores: dict[str, float] = {}
            reasoning: list[str] = []

            # --- 1. Power range match (30%) ---
            scores["power"] = self._score_power(power_w, sig, reasoning)
            if scores["power"] < 0.01:
                continue  # Power way too far off, skip entirely

            # --- 2. Duration match (15%) ---
            scores["duration"] = self._score_duration(duration_s, sig, reasoning)

            # --- 3. Cycling pattern match (15%) ---
            scores["cycling"] = self._score_cycling(
                is_cycling, cycling_on_s, cycling_off_s, sig, reasoning
            )

            # --- 4. Location context (15%) ---
            scores["location"] = self._score_location(circuit_locations, sig, reasoning)

            # --- 5. Time-of-day match (10%) ---
            scores["time_of_day"] = self._score_time_of_day(peak_hours, sig, reasoning)

            # --- 6. Seasonal match (10%) ---
            scores["seasonal"] = self._score_seasonal(season, sig, reasoning)

            # --- 7. Power stability match (5%) ---
            scores["stability"] = self._score_stability(power_stability, sig, reasoning)

            # Weighted total
            total = sum(scores[dim] * self.WEIGHTS[dim] for dim in self.WEIGHTS)

            if total >= 0.15:
                candidates.append(SignatureMatch(
                    device_name=name,
                    category=sig.category,
                    confidence=min(total, 1.0),
                    reasoning=reasoning,
                    dimension_scores=scores,
                ))

        # Sort by confidence, return top 5
        candidates.sort(key=lambda m: m.confidence, reverse=True)
        return candidates[:5]

    # ----------------------------------------------------------------
    # Dimension scorers (each returns 0.0 - 1.0)
    # ----------------------------------------------------------------

    @staticmethod
    def _score_power(
        power_w: float, sig: DeviceSignatureV2, reasoning: list[str]
    ) -> float:
        """Score how well observed power fits the signature's range."""
        if sig.power_min_w <= power_w <= sig.power_max_w:
            # Score higher closer to center
            center = (sig.power_min_w + sig.power_max_w) / 2
            half_range = (sig.power_max_w - sig.power_min_w) / 2
            if half_range > 0:
                distance = abs(power_w - center) / half_range
                score = 1.0 - distance * 0.3
            else:
                score = 1.0
            reasoning.append(
                f"power {power_w:.0f}W in range [{sig.power_min_w:.0f}-{sig.power_max_w:.0f}W] (score={score:.2f})"
            )
            return score

        # Allow 25% overshoot with graduated penalty
        if power_w < sig.power_min_w:
            overshoot = (sig.power_min_w - power_w) / max(sig.power_min_w, 1)
        else:
            overshoot = (power_w - sig.power_max_w) / max(sig.power_max_w, 1)

        if overshoot <= 0.25:
            score = max(0.0, 0.5 - overshoot * 2.0)
            reasoning.append(
                f"power {power_w:.0f}W near range [{sig.power_min_w:.0f}-{sig.power_max_w:.0f}W] ({overshoot:.0%} off, score={score:.2f})"
            )
            return score

        return 0.0  # Too far off

    @staticmethod
    def _score_duration(
        duration_s: float | None, sig: DeviceSignatureV2, reasoning: list[str]
    ) -> float:
        """Score how well observed duration fits."""
        if duration_s is None:
            reasoning.append("duration: no data (neutral)")
            return 0.5  # Neutral when no data

        if sig.duration_min_s <= duration_s <= sig.duration_max_s:
            reasoning.append(
                f"duration {duration_s:.0f}s in range [{sig.duration_min_s:.0f}-{sig.duration_max_s:.0f}s]"
            )
            return 1.0

        # Graduated penalty for near-misses
        if duration_s < sig.duration_min_s:
            ratio = duration_s / max(sig.duration_min_s, 1)
        else:
            ratio = sig.duration_max_s / max(duration_s, 1)

        if ratio > 0.5:
            score = ratio
            reasoning.append(
                f"duration {duration_s:.0f}s near range [{sig.duration_min_s:.0f}-{sig.duration_max_s:.0f}s] (score={score:.2f})"
            )
            return score

        reasoning.append(
            f"duration {duration_s:.0f}s outside range [{sig.duration_min_s:.0f}-{sig.duration_max_s:.0f}s]"
        )
        return 0.1

    @staticmethod
    def _score_cycling(
        is_cycling: bool,
        cycling_on_s: float | None,
        cycling_off_s: float | None,
        sig: DeviceSignatureV2,
        reasoning: list[str],
    ) -> float:
        """Score cycling pattern match."""
        sig_is_cycling = sig.duty_cycle_pattern in ("cycling", "variable")

        if is_cycling != sig_is_cycling:
            if is_cycling:
                reasoning.append(f"cycling observed but sig expects '{sig.duty_cycle_pattern}'")
            else:
                reasoning.append(f"no cycling but sig expects '{sig.duty_cycle_pattern}'")
            return 0.2

        if not is_cycling:
            reasoning.append("both non-cycling (match)")
            return 0.8

        # Both cycling -- compare periods if available
        if (
            cycling_on_s is not None
            and sig.cycling_on_s is not None
            and cycling_off_s is not None
            and sig.cycling_off_s is not None
        ):
            on_ratio = min(cycling_on_s, sig.cycling_on_s) / max(cycling_on_s, sig.cycling_on_s, 1)
            off_ratio = min(cycling_off_s, sig.cycling_off_s) / max(cycling_off_s, sig.cycling_off_s, 1)
            score = (on_ratio + off_ratio) / 2
            reasoning.append(
                f"cycling periods: on={cycling_on_s:.0f}s vs {sig.cycling_on_s:.0f}s, "
                f"off={cycling_off_s:.0f}s vs {sig.cycling_off_s:.0f}s (score={score:.2f})"
            )
            return score

        # Both cycling but no period data to compare
        reasoning.append("both cycling (pattern match, no period data)")
        return 0.7

    @staticmethod
    def _score_location(
        circuit_locations: list[str], sig: DeviceSignatureV2, reasoning: list[str]
    ) -> float:
        """Score location context match."""
        if not circuit_locations:
            reasoning.append("location: no circuit context (neutral)")
            return 0.5  # Neutral when no location info

        if "any" in sig.typical_locations:
            reasoning.append("location: device can be anywhere (match)")
            return 0.7

        overlap = set(circuit_locations) & set(sig.typical_locations)
        if overlap:
            reasoning.append(f"location match: {', '.join(overlap)}")
            return 1.0

        reasoning.append(
            f"location mismatch: circuit={circuit_locations}, sig expects {sig.typical_locations}"
        )
        return 0.1

    @staticmethod
    def _score_time_of_day(
        peak_hours: list[int] | None, sig: DeviceSignatureV2, reasoning: list[str]
    ) -> float:
        """Score time-of-day overlap."""
        if peak_hours is None or not peak_hours:
            reasoning.append("time_of_day: no data (neutral)")
            return 0.5

        sig_start, sig_end = sig.typical_hours[0], sig.typical_hours[1]

        # Handle 24-hour devices
        if sig_start == 0 and sig_end == 24:
            reasoning.append("time_of_day: device runs 24h (match)")
            return 0.8

        # Handle wrap-around hours (e.g., [20, 8] for overnight)
        if sig_start <= sig_end:
            sig_hours = set(range(sig_start, sig_end))
        else:
            sig_hours = set(range(sig_start, 24)) | set(range(0, sig_end))

        peak_set = set(peak_hours)
        if not sig_hours:
            return 0.5

        overlap = peak_set & sig_hours
        overlap_ratio = len(overlap) / len(peak_set) if peak_set else 0

        if overlap_ratio >= 0.5:
            reasoning.append(
                f"time_of_day: {len(overlap)}/{len(peak_set)} peak hours overlap sig [{sig_start}-{sig_end}]"
            )
            return 0.6 + overlap_ratio * 0.4
        else:
            reasoning.append(
                f"time_of_day: low overlap ({len(overlap)}/{len(peak_set)} hours) with sig [{sig_start}-{sig_end}]"
            )
            return max(0.1, overlap_ratio)

    @staticmethod
    def _score_seasonal(
        season: str, sig: DeviceSignatureV2, reasoning: list[str]
    ) -> float:
        """Score seasonal match."""
        if sig.seasonal == "year_round":
            reasoning.append("seasonal: year-round device")
            return 0.8

        # Map spring/fall to adjacent seasons for partial credit
        adjacent = {
            "winter": {"winter": 1.0, "fall": 0.5, "spring": 0.5, "summer": 0.1},
            "summer": {"summer": 1.0, "spring": 0.5, "fall": 0.5, "winter": 0.1},
        }

        sig_season = sig.seasonal
        if sig_season in adjacent and season in adjacent[sig_season]:
            score = adjacent[sig_season][season]
        elif sig_season == season:
            score = 1.0
        else:
            score = 0.3

        if score >= 0.8:
            reasoning.append(f"seasonal: {season} matches sig={sig_season}")
        else:
            reasoning.append(f"seasonal: {season} vs sig={sig_season} (score={score:.2f})")
        return score

    @staticmethod
    def _score_stability(
        power_stability: float | None, sig: DeviceSignatureV2, reasoning: list[str]
    ) -> float:
        """Score power stability match."""
        if power_stability is None:
            reasoning.append("stability: no data (neutral)")
            return 0.5

        diff = abs(power_stability - sig.power_stability)
        score = max(0.0, 1.0 - diff * 5.0)  # 0.2 diff => 0.0
        reasoning.append(
            f"stability: observed={power_stability:.2f} vs sig={sig.power_stability:.2f} (score={score:.2f})"
        )
        return score
