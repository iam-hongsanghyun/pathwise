"""Stations: refuelling infrastructure that caps + prices a fleet's fuel.

A station dispenses a fuel flow to the fleets in its scope; their fuel demand
(efficiency × distance × cargo) must be served by the scope's stations, capacity-
limited, at a per-unit fee on top of the fuel price. A station whose scope doesn't
cover the fleet is inert (the fleet refuels at the flat fuel price). Uses a
physicalised connection-route lane (Layer 1c), where the fleet's fuel is a real
demand the station serves.
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
_EFF = 0.003  # fuel = eff·dist·cargo = 24·cargo  ⇒  full delivery burns 24 000 t bunker


def _wb(*, stations: list[dict] | None = None) -> dict[str, Any]:
    ship = {
        "ship_size": 50.0,
        "speed": 600.0,
        "turnaround_days": 4.0,
        "operating_days": 330.0,
        "opex": 1.0e6,
        "count": 1000.0,
        "efficiency": _EFF,
        "cargo": "cargo",
        "company": "carrier",
        "group": "c",
    }
    wb: dict[str, Any] = {
        "meta": [{"key": "base_year", "value": 2025}],
        "periods": [{"year": 2025}],
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
                "distance": _DIST,
            },
        ],
        "fleet_groups": [{"group_id": "c", "label": "Carrier", "level": "company"}],
        "fleet": [{"fleet_id": "ship", "fuel": "bunker", **ship}],
        "fleet_routes": [{"process": "rt", "fleet_id": "ship"}],
        "demand": [{"company": "vc/dst", "flow_id": "prod", "year": 2025, "amount": _DEMAND}],
    }
    if stations is not None:
        wb["stations"] = stations
    return wb


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    return extract_results(solve(build(assemble_problem(wb, _SC))))


def _delivered(res: dict[str, Any]) -> float:
    return sum(
        float(r["value"]) for r in res["outputs"]["throughput"] if r.get("process") == "vc/dst/term"
    )


def test_no_station_meets_demand() -> None:
    res = _solve(_wb())
    assert res["status"] == "optimal"
    assert abs(_delivered(res) - _DEMAND) < 1e-6  # fuel at the flat price, demand fully met


def test_station_capacity_throttles_delivery() -> None:
    # Fleet fuel = 24·cargo. A 12 000/yr refuelling cap ⇒ cargo ≤ 500, so at most half
    # the demand can be carried (the rest goes undelivered).
    res = _solve(
        _wb(
            stations=[
                {
                    "station_id": "S",
                    "company": "carrier",
                    "refuel_flow": "bunker",
                    "refuel_capacity": 12000.0,
                }
            ]
        )
    )
    assert res["status"] == "optimal"
    assert _delivered(res) <= 500.0 + 1e-3
    assert _delivered(res) > 0.0


def test_station_fee_raises_cost_without_changing_delivery() -> None:
    base = _solve(_wb())
    fee = _solve(
        _wb(
            stations=[
                {
                    "station_id": "S",
                    "company": "carrier",
                    "refuel_flow": "bunker",
                    "refuel_fee": 2.0,
                }
            ]
        )
    )
    assert fee["status"] == "optimal"
    assert abs(_delivered(fee) - _DEMAND) < 1e-6  # uncapped ⇒ demand still met
    # Dispensed fuel = 24·1000 = 24000; a $2/unit fee adds $48000 over the base cost.
    assert abs((fee["objective"] - base["objective"]) - 48_000.0) < 1.0


def test_station_capacity_is_temporal() -> None:
    # A stations_t__refuel_capacity wide sheet gives a per-year dispensing cap, read via
    # Station.refuel_capacity_at; absent years fall back to the scalar.
    wb = _wb(
        stations=[
            {
                "station_id": "S",
                "company": "carrier",
                "refuel_flow": "bunker",
                "refuel_capacity": 9000.0,
            }
        ]
    )
    wb["stations_t__refuel_capacity"] = [{"year": 2025, "S": 12000.0}]
    st = next(s for s in assemble_problem(wb, _SC).stations if s.station_id == "S")
    assert abs(st.refuel_capacity_at(2025) - 12000.0) < 1e-6  # per-year override
    assert abs(st.refuel_capacity_at(2030) - 9000.0) < 1e-6  # falls back to the scalar


def test_station_in_another_scope_is_inert() -> None:
    # A station scoped to a different company doesn't gate the carrier's fleet.
    res = _solve(
        _wb(
            stations=[
                {
                    "station_id": "S",
                    "company": "other",
                    "refuel_flow": "bunker",
                    "refuel_capacity": 1.0,
                }
            ]
        )
    )
    assert res["status"] == "optimal"
    assert abs(_delivered(res) - _DEMAND) < 1e-6
