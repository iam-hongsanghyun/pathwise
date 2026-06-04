"""Shared ``pint`` unit registry.

A single process-wide registry so quantities compare and convert correctly
across modules. Use it at I/O boundaries (parsing data, presenting results) to
attach/convert units; keep the optimisation matrix itself in consistent base
units for good numerical scaling.
"""

from __future__ import annotations

from functools import lru_cache

from pint import UnitRegistry


@lru_cache(maxsize=1)
def get_registry() -> UnitRegistry:
    """Return the process-wide pint :class:`UnitRegistry` (cached)."""
    ureg: UnitRegistry = UnitRegistry()
    # Common modelling units not in pint's defaults.
    ureg.define("USD = [currency]")
    ureg.define("tCO2e = 1e6 * gram")  # tonnes CO2-equivalent (mass proxy)
    return ureg
