"""The shipped steel cradle-to-gate LCIA example runs under the simulate backend
and reports a complete multi-impact, foreground/background-split inventory.

This guards roadmap item #2 (LCA coverage): the bundled example must report GWP +
≥1 of AP/EP/PM, a non-zero background contribution, and a baseline-vs-variant
comparison — end to end through the real example workbook.
"""

from __future__ import annotations

from importlib.resources import files

import pytest

from pathwise.api.workbook_io import parse_sqlite
from pathwise.backends.registry import get_backend

_SCENARIO = {
    "economics": {"base_year": 2025},
    "horizon": {"start": 2025, "end": 2025},
    "simulate": {"baseline": {"plan": "as-is"}},
}


def _load() -> dict:
    src = files("pathwise.assets.examples") / "steel_lcia.sqlite"
    return parse_sqlite(src.read_bytes())


def test_steel_lcia_example_runs_multi_category() -> None:
    res = get_backend("simulate").run(_load(), _SCENARIO, {})
    assert res["status"] == "optimal"
    lca = res["outputs"]["lca"]
    assert lca["functional_unit"]["flow"] == "steel"
    by_impact = {d["impact"]: d["total"] for d in lca["by_impact"]}
    # Multi-category LCIA: GWP plus acidification, eutrophication, PM, ozone.
    for cat in ("GWP", "AP", "EP_marine", "PM", "POCP"):
        assert cat in by_impact, f"missing category {cat}"
        assert by_impact[cat] > 0, f"category {cat} should be positive"
    # GWP is the AR6 weighted sum of the gases.
    gwp = by_impact["CO2"] + 27.0 * by_impact["CH4"] + 273.0 * by_impact["N2O"]
    assert by_impact["GWP"] == pytest.approx(gwp, rel=1e-6)


def test_steel_lcia_example_has_background_and_phases() -> None:
    res = get_backend("simulate").run(_load(), _SCENARIO, {})
    lca = res["outputs"]["lca"]
    origin = {d["impact"]: d for d in lca["by_origin"]}
    # Purchased carriers (electricity / gas / coal / limestone) → non-zero background.
    assert origin["CO2"]["background"] > 0
    assert origin["GWP"]["background"] > 0
    assert origin["CO2"]["foreground"] > origin["CO2"]["background"]  # mostly on-site
    # foreground + background reconciles to the engine total.
    assert origin["CO2"]["foreground"] + origin["CO2"]["background"] == pytest.approx(
        origin["CO2"]["total"]
    )
    # Lifecycle-phase rollup: materials (mining + coking) and manufacturing (mill).
    phases = {d["phase"] for d in lca.get("by_phase", [])}
    assert {"materials", "manufacturing"} <= phases


def test_steel_lcia_green_variant_abates() -> None:
    res = get_backend("simulate").run(_load(), _SCENARIO, {})
    comparison = res["outputs"].get("comparison", [])
    assert comparison, "the model-resident green variant should be evaluated"
    green = comparison[0]
    assert green["status"] == "optimal"
    assert (green.get("abatement") or 0) > 0  # H2-DRI + EAF emits less GWP than BF-BOF
