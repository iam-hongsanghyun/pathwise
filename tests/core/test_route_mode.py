"""A route's candidate fleets must match its MODE — a rail route never gets ships.

When a physicalised route has no explicit fleet_routes, the default candidate set is
every fleet carrying the flow AND running the route's mode. So a sea lane defaults to
ships only, a rail lane to trains only — no rail-route-with-ships.
"""

from __future__ import annotations

from typing import Any

from pathwise.data import ScenarioConfig, assemble_problem

_SC = ScenarioConfig.from_dict(
    {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
)


def _wb(route_mode: str) -> dict[str, Any]:
    """A KR↔DST cargo lane (one route of the given mode) + a sea ship and a rail train,
    both carrying cargo, with NO explicit fleet_routes (so defaults apply)."""
    geo = {
        "ship_size": 50.0,
        "speed": 600.0,
        "turnaround_days": 4.0,
        "operating_days": 330.0,
        "opex": 1.0e6,
        "count": 10.0,
        "efficiency": 0.003,
        "cargo": "cargo",
        "company": "carrier",
        "group": "c",
    }
    return {
        "meta": [{"key": "base_year", "value": 2025}],
        "periods": [{"year": 2025}],
        "flows": [
            {"flow_id": "cargo", "kind": "material", "unit": "kt"},
            {"flow_id": "prod", "kind": "product", "unit": "kt"},
            {"flow_id": "fuel", "kind": "energy", "unit": "t", "price": 1.0},
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
                "lon": 130.0,
                "lat": 36.0,
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
                "mode": route_mode,
                "distance": 500.0,
            },
        ],
        "fleet_groups": [{"group_id": "c", "label": "Carrier", "level": "company"}],
        "fleet": [
            {"fleet_id": "ship", "fuel": "fuel", "mode": "sea", **geo},
            {"fleet_id": "train", "fuel": "fuel", "mode": "rail", **geo},
        ],
        "demand": [{"company": "vc/dst", "flow_id": "prod", "year": 2025, "amount": 100.0}],
    }


def _legs(route_mode: str) -> set[str]:
    prob = assemble_problem(_wb(route_mode), _SC)
    cr = next(c for c in prob.connection_routes if c.process == "rt")
    return {leg.fleet_id for leg in cr.legs}


def test_sea_route_defaults_to_ships_only() -> None:
    assert _legs("sea") == {"ship"}  # the rail train is NOT a candidate for a sea lane


def test_rail_route_defaults_to_trains_only() -> None:
    assert _legs("rail") == {"train"}  # no rail-route-with-ships
