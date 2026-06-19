"""Unit-system helpers: dimension-universal conversion + classification.

These exercise the canonical unit system loaded from ``assets/units.yaml`` (the
bundled seed; tests point ``data_dir`` at a tmp path so no writable copy exists).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest

from pathwise import units
from pathwise.config import get_settings


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # No units.yaml under the tmp data dir ⇒ reads the bundled seed deterministically.
    monkeypatch.setenv("PATHWISE_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    units.reload()
    yield
    get_settings.cache_clear()
    units.reload()


def test_universal_conversion() -> None:
    np.testing.assert_allclose(units.convert(1.0, "MWh", "GJ"), 3.6, rtol=1e-12)
    np.testing.assert_allclose(units.convert(3.6, "GJ", "MWh"), 1.0, rtol=1e-12)
    np.testing.assert_allclose(units.convert(1.0, "t", "kg"), 1000.0, rtol=1e-12)
    np.testing.assert_allclose(units.convert(1.0, "USD", "KRW"), 1300.0, rtol=1e-12)
    np.testing.assert_allclose(units.convert(1.0, "boe", "GJ"), 6.118, rtol=1e-12)


def test_incompatible_conversion_raises() -> None:
    with pytest.raises(ValueError):
        units.convert(1.0, "t", "GJ")  # mass ↔ energy needs a commodity factor


def test_dimension_classification() -> None:
    assert units.dimension_of("GJ") == "energy"
    assert units.dimension_of("MWh") == "energy"
    assert units.dimension_of("t") == "mass"
    assert units.dimension_of("tCO2e") == "emissions"
    assert units.dimension_of("USD") == "currency"
    # Placeholder / nonsense classify as "no known dimension", not a crash.
    assert units.dimension_of("unit") is None
    assert units.dimension_of("zzz") is None


def test_emissions_distinct_from_mass() -> None:
    # tCO2e is its own dimension, so it must NOT silently convert to/from mass.
    assert not units.units_compatible("t", "tCO2e")
    assert units.is_compatible("MWh", "energy")
    assert not units.is_compatible("t", "energy")


def test_parseable() -> None:
    assert units.is_parseable("GJ")
    assert units.is_parseable("tCO2e")
    assert not units.is_parseable("zzz")


def test_unit_factors_table() -> None:
    factors = units.unit_factors()
    assert factors["MWh"] == {"dimension": "energy", "factor_to_base": pytest.approx(3.6)}
    assert factors["GJ"]["factor_to_base"] == pytest.approx(1.0)
    assert factors["kg"]["dimension"] == "mass"
