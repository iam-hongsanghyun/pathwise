"""Green corridors: a per-lane transport emission-intensity cap.

All freight on a lane must keep its cargo-weighted emission intensity (transport
fuel emissions ÷ cargo moved) below the cap. A cap below the dirty fleet's
intensity therefore forces the optimiser onto the clean fleet even with NO carbon
price and the dirty fuel cheaper. A generous cap doesn't bind; a soft cap is
exceeded only at its penalty (so the dirty fleet can stay if switching costs more).
"""

from __future__ import annotations

from typing import Any

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

_SC = ScenarioConfig.from_dict(
    {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
)
_DEMAND = 1000.0  # kt/yr delivered
_DIST = 8000.0
_EFF = 0.003
# dirty intensity = eff·dist·factor(hfo) = 0.003·8000·3 = 72 [t impact / kt cargo]; clean = 0.
_DIRTY_INTENSITY = _EFF * _DIST * 3.0


def _wb(
    *,
    green_limit: float | None = None,
    green_soft: bool = False,
    green_penalty: float = 0.0,
    green_year: int | None = None,
) -> dict[str, Any]:
    """A KR→DST cargo lane carried by a dirty (cheap HFO) or clean (pricier NH3) fleet,
    with an optional green-corridor intensity cap on the lane."""
    ship = {
        "ship_size": 50.0,
        "speed": 600.0,
        "turnaround_days": 4.0,
        "operating_days": 330.0,
        "opex": 1.0e6,
        "count": 100.0,
        "efficiency": _EFF,
        "cargo": "cargo",
        "company": "carrier",
        "group": "c",
    }
    green = []
    if green_limit is not None:
        green = [
            {
                "from_node": "vc/kr",
                "to_node": "vc/dst",
                "flow": "cargo",
                "impact": "emis",
                "limit": green_limit,
                "soft": green_soft,
                "penalty": green_penalty,
                **({"year": green_year} if green_year is not None else {}),
            }
        ]
    return {
        "meta": [{"key": "base_year", "value": 2025}],
        "periods": [{"year": 2025}],
        "flows": [
            {"flow_id": "cargo", "kind": "material", "unit": "kt"},
            {"flow_id": "prod", "kind": "product", "unit": "kt"},
            {"flow_id": "hfo", "kind": "energy", "unit": "t", "price": 500.0},
            {"flow_id": "nh3", "kind": "energy", "unit": "t", "price": 700.0},
        ],
        "impacts": [{"impact_id": "emis", "unit": "t"}],
        "flow_impacts": [
            {"flow_id": "hfo", "impact_id": "emis", "factor": 3.0},
            {"flow_id": "nh3", "impact_id": "emis", "factor": 0.0},
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
        "routes": [
            {
                "process": "rt",
                "from_node": "vc/kr",
                "to_node": "vc/dst",
                "flow": "cargo",
                "mode": "sea",
                "distance": _DIST,
            },
        ],
        "fleet_groups": [{"group_id": "c", "label": "Carrier", "level": "company"}],
        "fleet": [
            {"fleet_id": "dirty", "fuel": "hfo", **ship},
            {"fleet_id": "clean", "fuel": "nh3", **ship},
        ],
        "fleet_routes": [
            {"process": "rt", "fleet_id": "dirty"},
            {"process": "rt", "fleet_id": "clean"},
        ],
        "demand": [{"company": "vc/dst", "flow_id": "prod", "year": 2025, "amount": _DEMAND}],
        **({"green_corridors": green} if green else {}),
    }


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    return extract_results(solve(build(assemble_problem(wb, _SC)))).copy()


def _chosen(res: dict[str, Any]) -> dict[str, int]:
    return {
        str(r["fleet"]): int(r["ships"])
        for r in res["outputs"]["fleet"]
        if r.get("process") == "rt" and int(r["ships"]) > 0
    }


def _delivered(res: dict[str, Any]) -> float:
    return sum(
        float(r["value"]) for r in res["outputs"]["throughput"] if r.get("process") == "vc/dst/term"
    )


def _emis(res: dict[str, Any]) -> float:
    return sum(float(s["total"]) for s in res["summary"]["impacts"] if s["impact"] == "emis")


def test_no_corridor_picks_the_cheap_dirty_fleet() -> None:
    res = _solve(_wb())
    assert res["status"] == "optimal"
    chosen = _chosen(res)
    assert "dirty" in chosen and "clean" not in chosen  # cheap HFO wins, no cap
    assert _emis(res) > 0.0


def test_hard_green_corridor_below_dirty_intensity_forces_clean() -> None:
    # A hard intensity cap well below the dirty fleet's 72 t/kt forces the clean fleet.
    res = _solve(_wb(green_limit=1.0, green_soft=False))
    assert res["status"] == "optimal"
    chosen = _chosen(res)
    assert "clean" in chosen and "dirty" not in chosen
    assert abs(_delivered(res) - _DEMAND) < 1e-6  # demand still met by the clean mode
    # Cargo-weighted intensity holds: total impact ≤ limit · cargo.
    assert _emis(res) <= 1.0 * _DEMAND + 1e-6


def test_generous_green_corridor_does_not_bind() -> None:
    # A cap ABOVE the dirty intensity leaves the cheap dirty fleet in play.
    res = _solve(_wb(green_limit=_DIRTY_INTENSITY + 10.0, green_soft=False))
    assert res["status"] == "optimal"
    assert "dirty" in _chosen(res)


def test_soft_corridor_is_exceeded_when_switching_costs_more() -> None:
    # Soft cap of 0 with a tiny penalty: paying the slack penalty (≈720) is far cheaper
    # than the clean-fuel premium (≈4.8M), so the optimiser keeps the dirty fleet —
    # unlike the hard cap, which forbids it.
    soft = _chosen(_solve(_wb(green_limit=0.0, green_soft=True, green_penalty=0.01)))
    hard = _chosen(_solve(_wb(green_limit=0.0, green_soft=False)))
    assert "dirty" in soft  # soft → pays the penalty, stays dirty
    assert "clean" in hard and "dirty" not in hard  # hard → must go clean


def test_year_scoped_corridor_only_binds_its_year() -> None:
    # A cap pinned to a non-model year (2030) never binds the 2025-only model.
    res = _solve(_wb(green_limit=1.0, green_soft=False, green_year=2030))
    assert res["status"] == "optimal"
    assert "dirty" in _chosen(res)  # the 2030 cap is inert in a 2025 run
