"""Per-voyage chokepoint toll: a transit fee on every voyage through a maritime
corridor, priced as ``toll · legflow / ship_size`` and independent of the corridor's
closure probability.

The KR→EU lane (Busan→Rotterdam) traverses Suez, so a Suez toll lands on it. Demand
is hard and there is one route, so the cargo (hence the voyage count) is fixed: adding
the toll must raise the objective by EXACTLY ``toll · delivered / ship_size``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

_SC = ScenarioConfig.from_dict(
    {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
)

_DEMAND = 1000.0  # kt/yr delivered
_SHIP_SIZE = 50.0  # cargo / voyage  → 20 voyages to move the demand


def _wb(*, suez_toll: float = 0.0) -> dict[str, Any]:
    ship = {
        "ship_size": _SHIP_SIZE,
        "speed": 600.0,
        "turnaround_days": 4.0,
        "operating_days": 330.0,
        "opex": 0.0,
        "count": 1000.0,  # ample carriers so the count never binds
    }
    return {
        "meta": [{"key": "base_year", "value": 2025}],
        "periods": [{"year": 2025}],
        "flows": [
            {
                "flow_id": "cargo",
                "kind": "material",
                "unit": "kt",
                "purchasable": 0,
                "sellable": 0,
            },
            {"flow_id": "prod", "kind": "product", "unit": "kt"},
            {
                "flow_id": "hfo",
                "kind": "energy",
                "unit": "t",
                "price": 0.0,
            },  # free fuel: isolate the toll
        ],
        "impacts": [{"impact_id": "co2", "unit": "t"}],
        "flow_impacts": [{"flow_id": "hfo", "impact_id": "co2", "factor": 0.0}],
        "technologies": [
            # A small make cost pins delivery to exactly demand (no free overproduction),
            # so the only thing that changes between the runs is the toll.
            {"technology_id": "make", "opex": 1.0},
            {"technology_id": "deliver", "opex": 0.0},
        ],
        "io": [
            {"technology_id": "make", "target": "cargo", "role": "output", "coefficient": 1.0},
            {"technology_id": "deliver", "target": "cargo", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "deliver",
                "target": "prod",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
        ],
        "nodes": [
            {"node_id": "vc", "kind": "group", "level": "value_chain", "label": "VC"},
            {
                "node_id": "vc/kr",
                "kind": "group",
                "level": "company",
                "label": "KR",
                "parent_id": "vc",
                "lon": 129.04,
                "lat": 35.10,
            },
            {
                "node_id": "vc/kr/plant",
                "kind": "asset",
                "level": "asset",
                "label": "plant",
                "parent_id": "vc/kr",
            },
            {
                "node_id": "vc/eu",
                "kind": "group",
                "level": "company",
                "label": "EU",
                "parent_id": "vc",
                "lon": 4.48,
                "lat": 51.95,
            },
            {
                "node_id": "vc/eu/term",
                "kind": "asset",
                "level": "asset",
                "label": "term",
                "parent_id": "vc/eu",
            },
        ],
        "assets": [
            {"asset_id": "vc/kr/plant", "baseline_technology": "make", "capacity": 1e7},
            {"asset_id": "vc/eu/term", "baseline_technology": "deliver", "capacity": 1e7},
        ],
        "links": [{"from_node": "vc/kr", "to_node": "vc/eu", "flow_id": "cargo"}],
        "routes": [
            {
                "process": "rt",
                "from_node": "vc/kr",
                "to_node": "vc/eu",
                "flow": "cargo",
                "mode": "sea",
                "distance": 20000.0,
            },
        ],
        "fleet": [
            {
                "fleet_id": "ship",
                "group": "c",
                "company": "carrier",
                "cargo": "cargo",
                "fuel": "hfo",
                "efficiency": 0.0,
                **ship,
            }
        ],
        "fleet_routes": [{"process": "rt", "fleet_id": "ship"}],
        "fleet_groups": [{"group_id": "c", "label": "Carrier", "level": "company"}],
        "corridors": [{"corridor": "suez", "toll": suez_toll}],
        "demand": [{"company": "vc/eu", "flow_id": "prod", "year": 2025, "amount": _DEMAND}],
    }


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    return extract_results(solve(build(assemble_problem(wb, _SC)))).copy()


def _delivered(res: dict[str, Any]) -> float:
    return sum(
        float(r["value"]) for r in res["outputs"]["throughput"] if r.get("process") == "vc/eu/term"
    )


def test_suez_toll_adds_exactly_toll_times_voyages() -> None:
    base = _solve(_wb(suez_toll=0.0))
    tolled = _solve(_wb(suez_toll=1.0e5))
    assert base["status"] == "optimal" and tolled["status"] == "optimal"
    # Demand met both ways (one route, hard demand) ⇒ identical cargo + voyage count.
    assert abs(_delivered(base) - _DEMAND) < 1e-6
    assert abs(_delivered(tolled) - _DEMAND) < 1e-6
    # The only difference is the toll: 1e5 / voyage × (1000 / 50) = 20 voyages = 2e6.
    expected = 1.0e5 * (_DEMAND / _SHIP_SIZE)
    np.testing.assert_allclose(tolled["objective"] - base["objective"], expected, rtol=1e-6)


def test_toll_does_not_apply_to_a_lane_that_misses_the_corridor() -> None:
    # Reroute the lane to Busan→Sydney (no Suez); the Suez toll must not bite.
    wb = _wb(suez_toll=1.0e5)
    for nd in wb["nodes"]:
        if nd["node_id"] == "vc/eu":
            nd["lon"], nd["lat"] = 151.21, -33.87  # Sydney — a Pacific lane, no Suez
    tolled = _solve(wb)
    wb0 = _wb(suez_toll=0.0)
    for nd in wb0["nodes"]:
        if nd["node_id"] == "vc/eu":
            nd["lon"], nd["lat"] = 151.21, -33.87
    base = _solve(wb0)
    assert tolled["status"] == "optimal"
    np.testing.assert_allclose(tolled["objective"], base["objective"], rtol=1e-6)
