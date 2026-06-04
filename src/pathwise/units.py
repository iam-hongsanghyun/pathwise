"""Unit handling via :mod:`pint`.

Physical quantities crossing module boundaries (energy, power, emission
intensity, currency rates, activity) must carry units rather than being passed
as bare floats. This module owns the single shared :class:`pint.UnitRegistry`
and a couple of domain-relevant unit definitions.

Inside the numerical core (linopy matrix assembly) we still work with bare
floats for performance — units are validated and normalised to base units at
the data/core boundary, then stripped.

Example:
    >>> from pathwise.units import ureg, Q_
    >>> energy = Q_(10.0, "GJ")
    >>> energy.to("MJ").magnitude
    10000.0
"""

from __future__ import annotations

from functools import lru_cache

import pint


@lru_cache(maxsize=1)
def _build_registry() -> pint.UnitRegistry:
    """Construct the shared unit registry with pathwise-specific units.

    Returns:
        A configured :class:`pint.UnitRegistry`. Cached so all callers share
        one registry (pint quantities from different registries cannot be
        combined).
    """
    reg: pint.UnitRegistry = pint.UnitRegistry()
    # Emission mass unit used throughout decarbonisation work.
    reg.define("tCO2e = 1000 * kg = tonne_CO2e")
    reg.define("gCO2e = 0.001 * g = gram_CO2e")
    # Generic "activity" placeholder — domains attach their own dimension via
    # the workbook `meta` unit declarations (e.g. nautical_mile, tonne_km).
    reg.define("activity = [activity]")
    # Currency is treated dimensionless-with-a-name; scenarios fix the symbol.
    reg.define("USD = [currency]")
    return reg


#: The process-wide unit registry. Import this, never construct your own.
ureg: pint.UnitRegistry = _build_registry()

#: Shorthand quantity constructor, ``Q_(value, "unit")``.
Q_ = ureg.Quantity
