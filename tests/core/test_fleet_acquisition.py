"""Fleet acquisition (capex): the optimiser BUILDS carriers when it's cheaper than
leaving demand unmet — an integer decision charged over the carrier's lifespan, with
a built carrier surviving its lifespan and an optional cap on total builds.

The model is one transport route served by a fleet with an EMPTY legacy pool
(``count`` = 0) but a per-carrier ``capex``, so the only way to deliver is to build.
"""

from __future__ import annotations

from typing import Any

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

_SC = ScenarioConfig.from_dict(
    {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
)


def _wb(
    *,
    capex: float = 1.0e6,
    count: float = 0.0,
    lifespan: int | None = None,
    max_build: float | None = None,
    years: tuple[int, ...] = (2025,),
    demand: float = 250.0,
) -> dict[str, Any]:
    fleet: dict[str, Any] = {
        "fleet_id": "ship",
        "company": "carrier",
        "mode": "sea",
        "cargo": "cargo_kr",
        "capacity": 100.0,
        "count": count,
        "capex": capex,
    }
    if lifespan is not None:
        fleet["lifespan"] = lifespan
    if max_build is not None:
        fleet["max_build"] = max_build
    return {
        "periods": [{"year": y} for y in years],
        "flows": [
            {"flow_id": "cargo_kr", "kind": "material", "unit": "kt", "price": 0.0},
            {"flow_id": "cargo_a", "kind": "product", "unit": "kt"},
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
            }
        ],
        "fleet": [fleet],
        "fleet_routes": [{"process": "pA", "fleet_id": "ship", "share": 100.0}],
        "demand": [
            {"company": "carrier", "flow_id": "cargo_a", "year": y, "amount": demand} for y in years
        ],
    }


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    return extract_results(solve(build(assemble_problem(wb, _SC)))).copy()


def _built(res: dict[str, Any]) -> dict[int, int]:
    return {int(r["period"]): int(r["built"]) for r in res["outputs"]["fleet_built"]}


def _delivered(res: dict[str, Any]) -> float:
    return sum(float(r["value"]) for r in res["outputs"]["throughput"])


def test_optimiser_builds_to_meet_demand() -> None:
    # Empty legacy pool + capex → the optimiser builds ceil(250/100)=3 carriers.
    res = _solve(_wb())
    assert res["status"] == "optimal"
    assert _built(res) == {2025: 3}
    assert abs(_delivered(res) - 250.0) < 1e-6


def test_built_carrier_retires_after_lifespan() -> None:
    # lifespan 5, demand in 2025 AND 2035 (gap > life): the 2025 cohort can't cover
    # 2035, so a second cohort must be built then.
    res = _solve(_wb(lifespan=5, years=(2025, 2035)))
    assert res["status"] == "optimal"
    built = _built(res)
    assert built.get(2025, 0) == 3 and built.get(2035, 0) == 3  # rebuilt after retirement


def test_max_build_caps_total_and_leaves_shortfall() -> None:
    # Cap total builds at 2 though 3 are needed → only 2 built, demand under-met.
    res = _solve(_wb(max_build=2.0))
    assert res["status"] == "optimal"
    assert sum(_built(res).values()) == 2
    assert _delivered(res) < 250.0


def test_no_capex_is_inert() -> None:
    # No capex anywhere → no build var, no fleet_built output (byte-identical path);
    # with an empty pool and no build option, demand goes unmet.
    res = _solve(_wb(capex=0.0))
    assert res["status"] == "optimal"
    assert res["outputs"]["fleet_built"] == []
