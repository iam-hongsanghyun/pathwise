"""Layer 1b: a shared ship pool allocated across routes (integer MILP).

Two transport routes draw on ONE archetype's pool. Each route's throughput is
``share·units`` with integer ships (units round up to cover demand), and the
ships on every route of an archetype sum to its available count — so a scarce
fleet forces the pool to bind and demand to go partly unmet.
"""

from __future__ import annotations

from typing import Any

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

_SC = ScenarioConfig.from_dict(
    {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
)


def _wb(
    available: float, demand_a: float = 250.0, demand_b: float = 150.0, share: float = 100.0
) -> dict[str, Any]:
    return {
        "periods": [{"year": 2025}],
        "commodities": [
            {"commodity_id": "cargo_kr", "kind": "material", "unit": "kt", "price": 0.0},
            {"commodity_id": "cargo_a", "kind": "product", "unit": "kt"},
            {"commodity_id": "cargo_b", "kind": "product", "unit": "kt"},
        ],
        "technologies": [
            {"technology_id": "route_a", "opex": 1},
            {"technology_id": "route_b", "opex": 1},
        ],
        "io": [
            {"technology_id": "route_a", "target": "cargo_kr", "role": "input", "coefficient": 1},
            {
                "technology_id": "route_a",
                "target": "cargo_a",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
            {"technology_id": "route_b", "target": "cargo_kr", "role": "input", "coefficient": 1},
            {
                "technology_id": "route_b",
                "target": "cargo_b",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        # Capacity left high so the FLEET (units·share) is the binding limit.
        "processes": [
            {
                "process_id": "pA",
                "company": "carrier",
                "baseline_technology": "route_a",
                "capacity": 1e6,
            },
            {
                "process_id": "pB",
                "company": "carrier",
                "baseline_technology": "route_b",
                "capacity": 1e6,
            },
        ],
        "fleet": [{"archetype": "ship", "year": 2025, "available": available}],
        "fleet_routes": [
            {"process": "pA", "archetype": "ship", "share": share},
            {"process": "pB", "archetype": "ship", "share": share},
        ],
        "demand": [
            {"company": "carrier", "commodity_id": "cargo_a", "year": 2025, "amount": demand_a},
            {"company": "carrier", "commodity_id": "cargo_b", "year": 2025, "amount": demand_b},
        ],
    }


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    return extract_results(solve(build(assemble_problem(wb, _SC)))).copy()


def _units(res: dict[str, Any]) -> dict[str, int]:
    return {str(r["process"]): int(r["ships"]) for r in res["outputs"]["fleet"]}


def _delivered(res: dict[str, Any]) -> float:
    return sum(float(r["value"]) for r in res["outputs"]["throughput"])


def test_integer_ships_round_up_to_cover_demand() -> None:
    # 5 ships available; A needs ceil(250/100)=3, B needs ceil(150/100)=2.
    res = _solve(_wb(available=5))
    assert res["status"] == "optimal"
    u = _units(res)
    assert u["pA"] == 3  # integer ships, capacity 300 ≥ 250
    assert u["pB"] == 2
    assert abs(_delivered(res) - 400.0) < 1e-6  # both lanes fully served


def test_scarce_pool_binds_and_leaves_demand_unmet() -> None:
    # Only 4 ships, but 5 are needed → the shared pool binds; one lane is short.
    res = _solve(_wb(available=4))
    assert res["status"] == "optimal"
    u = _units(res)
    assert u.get("pA", 0) + u.get("pB", 0) == 4  # the whole pool is used
    assert _delivered(res) < 400.0  # demand can't be fully met with 4 ships
