"""Centralised logging for pathwise.

Use :func:`get_logger` everywhere instead of configuring logging ad hoc. Per
project convention: log shapes and dtypes, never full arrays; never log
secrets, PII, or raw data rows.

Logging levels follow the project handbook:

==========  ====================================================
level       use for
==========  ====================================================
DEBUG       branch decisions, scalar values, array shapes/dtypes
INFO        milestones (data loaded, model built, solve complete)
WARNING     recoverable degradation (imputed values, fallbacks)
ERROR       a failure that returns or skips
CRITICAL    abort
==========  ====================================================
"""

from __future__ import annotations

import logging
import sys

from pathwise.config import get_settings

_CONFIGURED = False
_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def _configure_root() -> None:
    """Attach a single stderr handler to the ``pathwise`` root logger once."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    root = logging.getLogger("pathwise")
    root.setLevel(settings.log_level.upper())
    if not root.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under the ``pathwise`` root.

    Args:
        name: Module name, typically ``__name__``.

    Returns:
        A configured :class:`logging.Logger`. The first call configures the
        shared stderr handler and level from :class:`~pathwise.config.Settings`.
    """
    _configure_root()
    if not name.startswith("pathwise"):
        name = f"pathwise.{name}"
    return logging.getLogger(name)
