"""Smoke tests for the project skeleton."""

from __future__ import annotations

import pathwise
from pathwise.config import get_settings
from pathwise.logger import get_logger
from pathwise.units import get_registry


def test_version() -> None:
    assert pathwise.__version__ == "0.1.0"


def test_settings_defaults() -> None:
    s = get_settings()
    assert s.port == 8077
    assert s.solver_name == "highs"
    assert s.highs_user_bound_scale == -8


def test_logger() -> None:
    log = get_logger("pathwise.test")
    log.info("smoke")  # must not raise


def test_units_registry() -> None:
    ureg = get_registry()
    q = 1000.0 * ureg.gram
    assert q.to("kilogram").magnitude == 1.0
