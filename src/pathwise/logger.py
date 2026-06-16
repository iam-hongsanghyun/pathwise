"""Centralised logging.

Use :func:`get_logger` everywhere. Log shape and dtype, never full arrays;
never log secrets, PII, or raw data rows.
"""

from __future__ import annotations

import logging
import os

_CONFIGURED = False


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    # Funnel the level through the validated settings (single source of truth);
    # fall back to the raw env var / INFO if settings can't load yet (bootstrap).
    try:
        from pathwise.config import get_settings

        level = get_settings().log_level.upper()
    except Exception:
        level = os.environ.get("PATHWISE_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for ``name`` (typically ``__name__``)."""
    _configure()
    return logging.getLogger(name)
