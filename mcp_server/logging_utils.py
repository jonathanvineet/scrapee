"""Logging helpers for MCP server modules."""

from __future__ import annotations

import logging
import sys

def setup_logging(name: str, level: str = "INFO") -> logging.Logger:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=numeric_level,
            stream=sys.stderr,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    logger = logging.getLogger(name)
    logger.setLevel(numeric_level)
    return logger


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
