"""A year-less max_production cap (per-asset / per-stream) applies to every run
year, and a year-specific row overrides the base for its own year."""

from __future__ import annotations

from typing import Any

from pathwise.data import ScenarioConfig
from pathwise.data.assemble import assemble_problem

SC = ScenarioConfig.from_dict({"economics": {"base_year": 2025}})


def _wb(max_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "nodes": [
            {"node_id": "co", "parent_id": None, "kind": "group", "level": "company"},
            {"node_id": "co/bf", "parent_id": "co", "kind": "asset"},
        ],
        "assets": [{"asset_id": "co/bf", "baseline_technology": "BF", "capacity": 100}],
        "technologies": [{"technology_id": "BF", "io": []}],
        "io": [
            {
                "technology_id": "BF",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            }
        ],
        "flows": [{"flow_id": "steel", "kind": "product"}],
        "periods": [{"year": 2025, "duration_years": 1}, {"year": 2030, "duration_years": 1}],
        "max_production": max_rows,
    }


def test_year_less_cap_applies_to_every_year() -> None:
    prob = assemble_problem(_wb([{"company": "co/bf", "flow_id": "steel", "amount": 40}]), SC)
    assert prob.max_production[("co/bf", "steel", 2025)] == 40
    assert prob.max_production[("co/bf", "steel", 2030)] == 40


def test_year_specific_row_overrides_the_base() -> None:
    prob = assemble_problem(
        _wb(
            [
                {"company": "co/bf", "flow_id": "steel", "amount": 40},  # base (all years)
                {"company": "co/bf", "flow_id": "steel", "amount": 10, "year": 2030},
            ]
        ),
        SC,
    )
    assert prob.max_production[("co/bf", "steel", 2025)] == 40
    assert prob.max_production[("co/bf", "steel", 2030)] == 10


def test_year_keyed_only_does_not_spread() -> None:
    prob = assemble_problem(
        _wb([{"company": "all", "flow_id": "steel", "amount": 5, "year": 2025}]), SC
    )
    assert prob.max_production.get(("all", "steel", 2025)) == 5
    assert ("all", "steel", 2030) not in prob.max_production  # no base → no spread


def test_min_production_year_less_floor_applies_to_every_year() -> None:
    wb = _wb([])
    wb["min_production"] = [{"company": "co/bf", "flow_id": "iron", "amount": 30}]
    prob = assemble_problem(wb, SC)
    assert prob.min_production[("co/bf", "iron", 2025)] == 30
    assert prob.min_production[("co/bf", "iron", 2030)] == 30


def test_demand_year_less_target_applies_to_every_year() -> None:
    # A static (year-less) Optimisation constraint holds across the whole horizon —
    # so the UI can store one row instead of one per year.
    wb = _wb([])
    wb["demand"] = [{"company": "all", "flow_id": "iron", "amount": 500}]
    prob = assemble_problem(wb, SC)
    assert prob.demand[("all", "iron", 2025)] == 500
    assert prob.demand[("all", "iron", 2030)] == 500
