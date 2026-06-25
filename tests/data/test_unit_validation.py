"""Unit validation: unitless / unparseable / mis-dimensioned streams warn.

Every finding is a *warning* (units are metadata — a wrong unit can't make the
solve infeasible), so a clean workbook validates with no unit warnings and a
mangled one surfaces them without erroring.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from pathwise.config import get_settings
from pathwise.data.validation import validate
from pathwise.units import reload as units_reload
from tests.data.example import example_workbook


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PATHWISE_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    units_reload()
    yield
    get_settings.cache_clear()
    units_reload()


def _unit_warnings(workbook: dict[str, Any]) -> list[str]:
    return [w for w in validate(workbook).warnings if "unit" in w.lower()]


def test_clean_workbook_has_no_unit_warnings() -> None:
    report = validate(example_workbook())
    assert report.ok  # no errors
    assert _unit_warnings(example_workbook()) == []


def test_placeholder_unit_warns() -> None:
    wb = example_workbook()
    wb["flows"][2]["unit"] = "unit"  # 'ore' left on the placeholder
    warns = _unit_warnings(wb)
    assert any("ore" in w and "placeholder" in w for w in warns)


def test_unparseable_unit_warns() -> None:
    wb = example_workbook()
    wb["flows"][2]["unit"] = "zzz"
    assert any("ore" in w and "unrecognised" in w for w in _unit_warnings(wb))


def test_energy_stream_with_mass_unit_warns() -> None:
    wb = example_workbook()
    # 'coal' is an energy stream; tonnes is mass-dimensioned and it has no
    # energy_content factor, so it can't be converted to energy → warn.
    wb["flows"][0]["unit"] = "t"
    assert any("coal" in w and "energy_content" in w for w in _unit_warnings(wb))


def test_energy_stream_in_mass_with_energy_content_ok() -> None:
    wb = example_workbook()
    wb["flows"][0]["unit"] = "t"  # tonnes of coal …
    wb["flow_properties"] = [
        {"flow_id": "coal", "property": "energy_content", "value": 24.0}
    ]  # … but it declares GJ per tonne, so the fuel-in-mass case is legitimate.
    assert not any("coal" in w for w in _unit_warnings(wb))


def test_validation_never_errors_on_units() -> None:
    wb = example_workbook()
    wb["flows"][0]["unit"] = "zzz"
    wb["flows"][1]["unit"] = "unit"
    assert validate(wb).ok  # unit problems are warnings, never blockers
