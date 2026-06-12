"""Named MACC sets: link once, expand per facility, adopt independently."""

from __future__ import annotations

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _wb() -> dict:
    """Two facilities running the SAME technology, different capacities.

    One shared MACC set ("T retrofits") is linked to the TECHNOLOGY, so both
    facilities receive their own copy. The measure cuts fuel use 20% for an
    absolute block capex of 100 on a single-year horizon: at Big (capacity 100,
    fuel bill 100·2·10 = 2,000/yr) the saving is 400 > 100 → adopt; at Small
    (capacity 10, bill 200/yr) the saving is 40 < 100 → don't. Independent
    adoption ⇒ the two facilities decide differently.
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
            {"process_id": "Big", "company": "C", "baseline_technology": "T", "capacity": 100},
            {"process_id": "Small", "company": "C", "baseline_technology": "T", "capacity": 10},
        ],
        "measures": [
            {
                "measure_id": "fuel_saver",
                "set": "T retrofits",
                "type": "energy_efficiency",
                "target": "fuel",
                "lifetime": 15,
            }
        ],
        "measure_blocks": [
            {"measure_id": "fuel_saver", "block": 0, "reduction": 0.2, "capex": 100.0}
        ],
        "measure_links": [{"set": "T retrofits", "applies_to": "T"}],
        "demand": [{"company": "C", "commodity_id": "widget", "year": 2025, "amount": 110}],
        "impacts": [],
        "markets": [],
        "storage": [],
    }


def _solve(wb: dict) -> dict:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return extract_results(solve(build(assemble_problem(wb, sc))))


def test_set_linked_to_technology_expands_per_facility() -> None:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    prob = assemble_problem(_wb(), sc)
    ids = sorted(m.measure_id for m in prob.measures)
    assert ids == ["fuel_saver @ Big", "fuel_saver @ Small"]
    assert {m.applies_to for m in prob.measures} == {"Big", "Small"}


def test_each_facility_adopts_independently() -> None:
    res = _solve(_wb())
    assert res["status"] == "optimal"
    adopted = {m["process"]: m["adoption"] for m in res["outputs"]["measures"]}
    assert adopted.get("Big", 0) > 0.99, "saving 400/yr beats capex 100"
    assert adopted.get("Small", 0) in (0, None) or adopted.get("Small", 0) < 0.01, (
        "saving 40/yr must not justify capex 100"
    )


def test_direct_facility_link_still_works() -> None:
    wb = _wb()
    wb["measure_links"] = [{"set": "T retrofits", "applies_to": "Small"}]
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    prob = assemble_problem(wb, sc)
    assert [m.applies_to for m in prob.measures] == ["Small"]


def test_negative_cost_block_is_adopted_immediately() -> None:
    wb = _wb()
    wb["measure_blocks"][0]["capex"] = -50.0  # e.g. a subsidised retrofit
    res = _solve(wb)
    adopted = {m["process"]: m["adoption"] for m in res["outputs"]["measures"]}
    assert adopted.get("Big", 0) > 0.99 and adopted.get("Small", 0) > 0.99
