"""Logging setup for SPAN NILM."""

import logging
import sys
from span_nilm.utils.config import LoggingConfig


def setup_logging(cfg: LoggingConfig) -> logging.Logger:
    """Configure and return the application logger."""
    logger = logging.getLogger("span_nilm")
    logger.setLevel(getattr(logging, cfg.level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler
    if cfg.file:
        fh = logging.FileHandler(cfg.file)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger
