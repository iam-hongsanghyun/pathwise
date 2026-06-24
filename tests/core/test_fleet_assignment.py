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


def _wb_lifecycle(build_year: int) -> dict[str, Any]:
    """One route served by a fleet class that only enters service in ``build_year``."""
    return {
        "periods": [{"year": 2025}, {"year": 2030}],
        "commodities": [
            {"commodity_id": "cargo_kr", "kind": "material", "unit": "kt", "price": 0.0},
            {"commodity_id": "cargo_a", "kind": "product", "unit": "kt"},
        ],
        "technologies": [{"technology_id": "route_a", "opex": 1}],
        "io": [
            {"technology_id": "route_a", "target": "cargo_kr", "role": "input", "coefficient": 1},
            {
                "technology_id": "route_a",
                "target": "cargo_a",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "processes": [
            {
                "process_id": "pA",
                "company": "carrier",
                "baseline_technology": "route_a",
                "capacity": 1e6,
            },
        ],
        # New fleet schema: a class row with capacity + lifecycle (no per-year rows).
        "fleet": [
            {
                "fleet_id": "ship",
                "company": "carrier",
                "cargo": "cargo_kr",
                "capacity": 100.0,
                "count": 5.0,
                "build_year": build_year,
            }
        ],
        "fleet_routes": [{"process": "pA", "fleet_id": "ship"}],  # share ⇒ fleet capacity
        "demand": [
            {"company": "carrier", "commodity_id": "cargo_a", "year": 2025, "amount": 250.0},
            {"company": "carrier", "commodity_id": "cargo_a", "year": 2030, "amount": 250.0},
        ],
    }


def _delivered_in(res: dict[str, Any], year: int) -> float:
    return sum(float(r["value"]) for r in res["outputs"]["throughput"] if int(r["period"]) == year)


def test_fleet_lifecycle_gates_availability() -> None:
    # The fleet is only built in 2030, so 2025 has no carriers and delivers nothing;
    # 2030 has the 5-ship pool and serves the 250 kt demand.
    res = _solve(_wb_lifecycle(build_year=2030))
    assert res["status"] == "optimal"
    assert _delivered_in(res, 2025) < 1e-6  # not yet in service
    assert abs(_delivered_in(res, 2030) - 250.0) < 1e-6  # pool available → demand met
    # Capacity comes from the fleet (100/unit), so ≥3 carriers are needed to cover
    # 250 kt; units carry no cost, so the solver may hold up to the pool of 5.
    units_2030 = {(r["process"], r["period"]): int(r["ships"]) for r in res["outputs"]["fleet"]}
    assert 3 <= units_2030.get(("pA", 2030), 0) <= 5
    assert ("pA", 2025) not in units_2030  # no carriers in service before build_year
