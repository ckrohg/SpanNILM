"""Configuration management for SPAN NILM."""

import os
from pathlib import Path
from dataclasses import dataclass, field

import yaml


@dataclass
class SpanConfig:
    host: str = "192.168.1.100"
    token: str = ""
    poll_interval_seconds: int = 1
    timeout_seconds: int = 5


@dataclass
class StorageConfig:
    data_dir: str = "./data"
    format: str = "parquet"
    retention_days: int = 90


@dataclass
class DetectionConfig:
    min_power_delta_w: float = 15.0
    smoothing_window: int = 5
    min_state_duration_s: int = 3
    max_event_pair_gap_s: int = 7200


@dataclass
class ClassificationConfig:
    min_observations: int = 10
    match_threshold: float = 0.85
    signatures_file: str = "./device_signatures.yaml"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "./span_nilm.log"


@dataclass
class Config:
    span: SpanConfig = field(default_factory=SpanConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_yaml(cls, path: str = "span_config.yaml") -> "Config":
        """Load configuration from YAML file."""
        config_path = Path(path)
        if not config_path.exists():
            return cls()

        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

        cfg = cls()

        if "span" in raw:
            cfg.span = SpanConfig(**raw["span"])
        # Allow env var override for token
        env_token = os.environ.get("SPAN_TOKEN", "")
        if env_token:
            cfg.span.token = env_token

        if "storage" in raw:
            cfg.storage = StorageConfig(**raw["storage"])
        if "detection" in raw:
            cfg.detection = DetectionConfig(**raw["detection"])
        if "classification" in raw:
            cfg.classification = ClassificationConfig(**raw["classification"])
        if "logging" in raw:
            cfg.logging = LoggingConfig(**raw["logging"])

        return cfg
