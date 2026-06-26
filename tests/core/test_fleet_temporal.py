"""Fleet economic/efficiency values are temporal: a fleet's fuel efficiency, O&M and
build cost can improve over the horizon via `fleet_t__{field}` wide sheets, read by the
engine per-year through `Fleet.*_at(year)`.
"""

from __future__ import annotations

from typing import Any

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

_SC = ScenarioConfig.from_dict(
    {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
)


def _wb(*, eff_2030: float | None = None) -> dict[str, Any]:
    """A KR↔DST cargo lane over 2025+2030; the ship burns `bunker` ∝ efficiency·distance.
    `eff_2030` overrides the fleet's efficiency in 2030 via fleet_t__efficiency."""
    ship = {
        "ship_size": 50.0,
        "speed": 600.0,
        "turnaround_days": 4.0,
        "operating_days": 330.0,
        "opex": 1.0e6,
        "count": 1000.0,
        "efficiency": 0.003,
        "cargo": "cargo",
        "company": "carrier",
        "group": "c",
    }
    wb: dict[str, Any] = {
        "meta": [{"key": "base_year", "value": 2025}],
        "periods": [{"year": 2025, "duration_years": 1}, {"year": 2030, "duration_years": 1}],
        "flows": [
            {"flow_id": "cargo", "kind": "material", "unit": "kt"},
            {"flow_id": "prod", "kind": "product", "unit": "kt"},
            {"flow_id": "bunker", "kind": "energy", "unit": "t", "price": 1.0},
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
                "distance": 8000.0,
            },
        ],
        "fleet_groups": [{"group_id": "c", "label": "Carrier", "level": "company"}],
        "fleet": [{"fleet_id": "ship", "fuel": "bunker", **ship}],
        "fleet_routes": [{"process": "rt", "fleet_id": "ship"}],
        "demand": [
            {"company": "vc/dst", "flow_id": "prod", "year": 2025, "amount": 1000.0},
            {"company": "vc/dst", "flow_id": "prod", "year": 2030, "amount": 1000.0},
        ],
    }
    if eff_2030 is not None:
        wb["fleet_t__efficiency"] = [
            {"year": 2025, "ship": 0.003},
            {"year": 2030, "ship": eff_2030},
        ]
    return wb


def test_fleet_efficiency_accessor_reads_per_year() -> None:
    prob = assemble_problem(_wb(eff_2030=0.0015), _SC)
    fl = prob.fleets["ship"]
    assert abs(fl.efficiency_at(2025) - 0.003) < 1e-9
    assert abs(fl.efficiency_at(2030) - 0.0015) < 1e-9  # improved efficiency in 2030


def test_improving_efficiency_lowers_cost() -> None:
    # Halving the 2030 efficiency halves that year's fuel burn ⇒ lower total fuel cost.
    flat = extract_results(solve(build(assemble_problem(_wb(), _SC))))
    better = extract_results(solve(build(assemble_problem(_wb(eff_2030=0.0015), _SC))))
    assert flat["status"] == "optimal" and better["status"] == "optimal"
    assert better["objective"] < flat["objective"] - 1.0  # 2030 burns less bunker
