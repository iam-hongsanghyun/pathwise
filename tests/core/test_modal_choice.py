"""Modal choice: several routes (modes) on ONE lane split the flow.

Adding a rail route alongside a sea route on the same connection is the "real
alternative" — both physicalise the same lane's edge, so the lane's flow is SHARED
across modes (Σ carried over every mode == the lane flow), never double-carried. The
optimiser picks the cheapest feasible mix: the cheap mode wins, relative cost flips
the choice, a capacity-limited cheap mode spills onto the alternative, and blocking
one mode shifts the flow to the other (it does not close the lane).
"""

from __future__ import annotations

from typing import Any

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

_SC = ScenarioConfig.from_dict(
    {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
)
_DEMAND = 1000.0  # kt/yr delivered

# Identical ship geometry on both modes (so a per-ship carries the same cargo/yr and the
# choice turns only on fuel price + each mode's capacity).
_GEO = {
    "ship_size": 50.0,
    "speed": 600.0,
    "turnaround_days": 4.0,
    "operating_days": 330.0,
    "opex": 1.0e6,
    "efficiency": 0.003,
    "cargo": "cargo",
    "company": "carrier",
    "group": "c",
}


def _wb(
    *,
    sea_fuel: float = 100.0,
    rail_fuel: float = 100.0,
    sea_count: float = 100.0,
    rail_count: float = 100.0,
    sea_blocked: bool = False,
) -> dict[str, Any]:
    """A KR→DST cargo connection with TWO modal routes (sea + rail) on one lane."""
    return {
        "meta": [{"key": "base_year", "value": 2025}],
        "periods": [{"year": 2025}],
        "flows": [
            {"flow_id": "cargo", "kind": "material", "unit": "kt"},
            {"flow_id": "prod", "kind": "product", "unit": "kt"},
            {"flow_id": "bunker", "kind": "energy", "unit": "t", "price": sea_fuel},
            {"flow_id": "diesel", "kind": "energy", "unit": "t", "price": rail_fuel},
        ],
        "technologies": [
            {"technology_id": "make", "opex": 0.01},
            {"technology_id": "deliver", "opex": 0.01},
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
                "parent_id": "vc",
                "lon": 129.0,
                "lat": 35.0,
            },
            {"node_id": "vc/kr/plant", "kind": "asset", "level": "asset", "parent_id": "vc/kr"},
            {
                "node_id": "vc/dst",
                "kind": "group",
                "level": "company",
                "parent_id": "vc",
                "lon": 151.0,
                "lat": -34.0,
            },
            {"node_id": "vc/dst/term", "kind": "asset", "level": "asset", "parent_id": "vc/dst"},
        ],
        "assets": [
            {"asset_id": "vc/kr/plant", "baseline_technology": "make", "capacity": 1e7},
            {"asset_id": "vc/dst/term", "baseline_technology": "deliver", "capacity": 1e7},
        ],
        "links": [{"from_node": "vc/kr", "to_node": "vc/dst", "flow_id": "cargo"}],
        # TWO routes for the SAME lane → modal alternatives the optimiser chooses between.
        "routes": [
            {
                "process": "rt_sea",
                "from_node": "vc/kr",
                "to_node": "vc/dst",
                "flow": "cargo",
                "mode": "sea",
                "distance": 8000.0,
                **({"blocked": "true"} if sea_blocked else {}),
            },
            {
                "process": "rt_rail",
                "from_node": "vc/kr",
                "to_node": "vc/dst",
                "flow": "cargo",
                "mode": "rail",
                "distance": 8000.0,
            },
        ],
        "fleet_groups": [{"group_id": "c", "label": "Carrier", "level": "company"}],
        "fleet": [
            {"fleet_id": "sea_fleet", "fuel": "bunker", "count": sea_count, **_GEO},
            {"fleet_id": "rail_fleet", "fuel": "diesel", "count": rail_count, **_GEO},
        ],
        "fleet_routes": [
            {"process": "rt_sea", "fleet_id": "sea_fleet"},
            {"process": "rt_rail", "fleet_id": "rail_fleet"},
        ],
        "demand": [{"company": "vc/dst", "flow_id": "prod", "year": 2025, "amount": _DEMAND}],
    }


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    return extract_results(solve(build(assemble_problem(wb, _SC)))).copy()


def _by_mode(res: dict[str, Any]) -> dict[str, float]:
    """process -> cargo carried (throughput) for the two modal routes."""
    out: dict[str, float] = {}
    for r in res["outputs"]["fleet"]:
        p = r.get("process")
        if p in ("rt_sea", "rt_rail") and float(r.get("throughput", 0)) > 1e-6:
            out[p] = out.get(p, 0.0) + float(r["throughput"])
    return out


def _delivered(res: dict[str, Any]) -> float:
    return sum(
        float(r["value"]) for r in res["outputs"]["throughput"] if r.get("process") == "vc/dst/term"
    )


def test_cheapest_mode_wins() -> None:
    # Sea fuel cheap, rail fuel dear → the whole lane goes by sea; rail is the idle
    # alternative. Demand met.
    res = _solve(_wb(sea_fuel=100.0, rail_fuel=2000.0))
    assert res["status"] == "optimal"
    modes = _by_mode(res)
    assert "rt_sea" in modes and "rt_rail" not in modes
    assert abs(_delivered(res) - _DEMAND) < 1e-6


def test_relative_cost_flips_the_mode() -> None:
    # Make rail the cheap mode → the optimiser switches the lane to rail.
    res = _solve(_wb(sea_fuel=2000.0, rail_fuel=100.0))
    assert res["status"] == "optimal"
    modes = _by_mode(res)
    assert "rt_rail" in modes and "rt_sea" not in modes


def test_capacity_limited_mode_spills_to_the_alternative() -> None:
    # Sea is cheapest but only ONE ship is available (≈538 kt/yr at this geometry),
    # so the lane SPLITS: sea carries to its cap, rail carries the remainder. This is
    # the proof the two modes share the lane's flow (not double-carry).
    res = _solve(_wb(sea_fuel=100.0, rail_fuel=2000.0, sea_count=1.0))
    assert res["status"] == "optimal"
    modes = _by_mode(res)
    assert "rt_sea" in modes and "rt_rail" in modes  # both modes carry
    assert abs(sum(modes.values()) - _DEMAND) < 1.0  # together they meet demand exactly
    assert modes["rt_sea"] < _DEMAND and modes["rt_rail"] < _DEMAND


def test_blocking_one_mode_shifts_to_the_other() -> None:
    # Sea is cheapest, but blocking it (a corridor what-if) must NOT close the lane —
    # the flow shifts to the rail alternative and demand is still met.
    res = _solve(_wb(sea_fuel=100.0, rail_fuel=2000.0, sea_blocked=True))
    assert res["status"] == "optimal"
    modes = _by_mode(res)
    assert "rt_rail" in modes and "rt_sea" not in modes
    assert abs(_delivered(res) - _DEMAND) < 1e-6
