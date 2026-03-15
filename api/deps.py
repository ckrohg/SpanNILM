"""Shared dependencies for the FastAPI app."""

import os
from functools import lru_cache

from dotenv import load_dotenv

from span_nilm.collector.sources.tempiq_source import TempIQSource
from span_nilm.utils.config import Config

load_dotenv()


@lru_cache
def get_config() -> Config:
    return Config.from_yaml("span_config.yaml")


@lru_cache
def get_tempiq_source() -> TempIQSource:
    return TempIQSource(
        database_url=os.environ["TEMPIQ_DATABASE_URL"],
        property_id=os.environ["TEMPIQ_PROPERTY_ID"],
    )
