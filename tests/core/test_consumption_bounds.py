"""Per-asset intake bounds (the consumer-side mirror of min/max_production).

``max_consumption`` caps how much of a commodity a asset may take in (a max
purchase); ``min_consumption`` forces a minimum (a required offtake / take-or-pay).
Tested on a fuel blend (coal cheap, H2 dear) so the bound is non-trivial: capping
one input shifts the optimiser onto the other.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _sc() -> ScenarioConfig:
    return ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    return extract_results(solve(build(assemble_problem(wb, _sc()))))


def _wb() -> dict[str, Any]:
    # P makes 50 widgets; tech T burns a coal+H2 blend (1+1 = 2 energy/widget), so
    # total fuel = 100. Coal is cheap ($10), H2 dear ($100); least cost ⇒ all coal.
    return {
        "periods": [{"year": 2025}],
        "commodities": [
            {"commodity_id": "coal", "kind": "energy", "price": 10},
            {"commodity_id": "h2", "kind": "energy", "price": 100},
            {"commodity_id": "widget", "kind": "product"},
        ],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 100}
        ],
        "io": [
            {
                "technology_id": "T",
                "target": "coal",
                "role": "input",
                "coefficient": 1,
                "group": "fuel",
                "share_min": 0,
                "share_max": 1,
            },
            {
                "technology_id": "T",
                "target": "h2",
                "role": "input",
                "coefficient": 1,
                "group": "fuel",
                "share_min": 0,
                "share_max": 1,
            },
            {
                "technology_id": "T",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "demand": [{"company": "C", "commodity_id": "widget", "year": 2025, "amount": 50}],
    }


def test_baseline_picks_the_cheap_input() -> None:
    res = _solve(_wb())
    assert res["status"] == "optimal"
    # 100 fuel, all coal @ $10 = $1000.
    np.testing.assert_allclose(res["objective"], 1000.0, rtol=1e-6)


def test_max_consumption_is_assembled() -> None:
    wb = _wb()
    wb["max_consumption"] = [{"company": "P", "commodity_id": "coal", "amount": 30}]
    prob = assemble_problem(wb, _sc())
    assert prob.max_consumption[("P", "coal", 2025)] == 30


def test_max_consumption_caps_an_input_and_forces_the_other() -> None:
    wb = _wb()
    # Cap coal intake at 30 ⇒ the other 70 fuel must be the dear H2.
    wb["max_consumption"] = [{"company": "P", "commodity_id": "coal", "amount": 30}]
    res = _solve(wb)
    assert res["status"] == "optimal"
    # 30 coal ($300) + 70 H2 ($7000) = $7300.
    np.testing.assert_allclose(res["objective"], 7300.0, rtol=1e-6)


def test_min_consumption_forces_required_offtake() -> None:
    wb = _wb()
    # Require ≥40 H2 intake even though coal is cheaper.
    wb["min_consumption"] = [{"company": "P", "commodity_id": "h2", "amount": 40}]
    res = _solve(wb)
    assert res["status"] == "optimal"
    # 40 H2 ($4000) + 60 coal ($600) = $4600.
    np.testing.assert_allclose(res["objective"], 4600.0, rtol=1e-6)
