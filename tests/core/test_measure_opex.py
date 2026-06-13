"""Measure opex: a recurring O&M cost charged every period while adopted.

A block now carries both ``capex`` (a one-off lump at adoption) and ``opex`` (a
fixed cost per year while adopted, scaled by the adoption level). The opex term
is weighted by discount × duration like any other O&M, so a recurring cost above
the annual saving makes a measure uneconomic even when its capex is trivial.
"""

from __future__ import annotations

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _wb(opex: float) -> dict:
    """One facility on T (fuel 2/unit @ 10) — a 20% fuel measure saves 400/yr.

    Capacity 100 → baseline fuel reference 100·2 = 200 units → bill 2,000/yr; a
    0.2 reduction saves 0.2·200·10 = 400/yr. Capex is a one-off 100 (saving beats
    it), so adoption turns purely on the recurring opex.
    """
    return {
        "periods": [{"year": 2025}],
        "commodities": [
            {"commodity_id": "fuel", "kind": "energy", "price": 10.0},
            {"commodity_id": "widget", "kind": "product"},
        ],
        "technologies": [{"technology_id": "T"}],
        "io": [
            {"technology_id": "T", "target": "fuel", "role": "input", "coefficient": 2},
            {
                "technology_id": "T",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 100}
        ],
        "measures": [
            {
                "measure_id": "fuel_saver",
                "type": "energy_efficiency",
                "target": "fuel",
                "facility": "P",
            }
        ],
        "measure_blocks": [
            {"measure_id": "fuel_saver", "block": 0, "reduction": 0.2, "capex": 100.0, "opex": opex}
        ],
        "demand": [{"company": "C", "commodity_id": "widget", "year": 2025, "amount": 100}],
        "impacts": [],
        "markets": [],
        "storage": [],
    }


def _solve(wb: dict) -> dict:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return extract_results(solve(build(assemble_problem(wb, sc))))


def _adoption(res: dict) -> float:
    return next((m["adoption"] for m in res["outputs"]["measures"] if m["process"] == "P"), 0.0)


def test_zero_opex_block_is_adopted() -> None:
    res = _solve(_wb(0.0))
    assert res["status"] == "optimal"
    assert _adoption(res) > 0.99, "400/yr saving beats the one-off capex of 100"


def test_recurring_opex_above_saving_blocks_adoption() -> None:
    # Capex stays a trivial 100, but a 600/yr opex outweighs the 400/yr saving,
    # so the measure must NOT be adopted — proving opex is charged per period.
    res = _solve(_wb(600.0))
    assert res["status"] == "optimal"
    assert _adoption(res) < 0.01, "recurring opex above the annual saving must deter adoption"
