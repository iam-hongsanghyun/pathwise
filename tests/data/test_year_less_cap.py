"""A year-less max_production cap (per-machine / per-stream) applies to every run
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
            {"node_id": "co/bf", "parent_id": "co", "kind": "machine"},
        ],
        "machines": [{"machine_id": "co/bf", "baseline_technology": "BF", "capacity": 100}],
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
        "commodities": [{"commodity_id": "steel", "kind": "product"}],
        "periods": [{"year": 2025, "duration_years": 1}, {"year": 2030, "duration_years": 1}],
        "max_production": max_rows,
    }


def test_year_less_cap_applies_to_every_year() -> None:
    prob = assemble_problem(_wb([{"company": "co/bf", "commodity_id": "steel", "amount": 40}]), SC)
    assert prob.max_production[("co/bf", "steel", 2025)] == 40
    assert prob.max_production[("co/bf", "steel", 2030)] == 40


def test_year_specific_row_overrides_the_base() -> None:
    prob = assemble_problem(
        _wb(
            [
                {"company": "co/bf", "commodity_id": "steel", "amount": 40},  # base (all years)
                {"company": "co/bf", "commodity_id": "steel", "amount": 10, "year": 2030},
            ]
        ),
        SC,
    )
    assert prob.max_production[("co/bf", "steel", 2025)] == 40
    assert prob.max_production[("co/bf", "steel", 2030)] == 10


def test_year_keyed_only_does_not_spread() -> None:
    prob = assemble_problem(
        _wb([{"company": "all", "commodity_id": "steel", "amount": 5, "year": 2025}]), SC
    )
    assert prob.max_production.get(("all", "steel", 2025)) == 5
    assert ("all", "steel", 2030) not in prob.max_production  # no base → no spread
