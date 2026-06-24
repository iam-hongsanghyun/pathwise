"""Layer 1c+: a physicalised value-chain connection carried by a chosen fleet.

A virtual stream connection (an Edge — free, instant "teleport") is made physical:
its flow must be carried by carriers drawn from a CANDIDATE set of fleets, with the
route's distance driving both carriers needed and fuel burned (cost + emissions).
The optimiser picks which candidate fleet runs the lane. These tests pin the
mechanism: the cleaner fleet wins under a carbon price, a longer lane needs more
carriers, a blocked corridor stops delivery, and a connection with no fleet stays
virtual (teleport).
"""

from __future__ import annotations

from typing import Any

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

_SC = ScenarioConfig.from_dict(
    {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
)

# Busan → a destination; distance is supplied explicitly so the tests are hermetic
# (no network/searoute dependency).
_DEMAND = 1000.0  # kt/yr of the delivered product


def _wb(
    *,
    co2_price: float = 0.0,
    distance: float = 8000.0,
    candidates: tuple[str, ...] = ("dirty", "clean"),
    blocked: bool = False,
    with_fleets: bool = True,
    co2_cap: float | None = None,
) -> dict[str, Any]:
    """A KR→DST cargo connection physicalised into a route with candidate fleets.

    ``dirty`` burns a cheap high-CO2 fuel; ``clean`` a pricier zero-CO2 fuel, with
    the SAME ship geometry (so carriers-needed is identical and the choice is purely
    fuel cost + carbon).
    """
    # Identical ship geometry + O&M (so idle carriers cost ⇒ unit counts are the
    # minimum needed, and the fleet choice turns only on fuel cost + carbon).
    ship = {
        "ship_size": 50.0,
        "speed": 600.0,
        "turnaround_days": 4.0,
        "operating_days": 330.0,
        "opex": 1.0e6,
        "count": 100.0,
    }
    fleet = [
        {
            "fleet_id": "dirty",
            "group": "c",
            "company": "carrier",
            "cargo": "cargo",
            "fuel": "hfo",
            "efficiency": 0.003,
            **ship,
        },
        {
            "fleet_id": "clean",
            "group": "c",
            "company": "carrier",
            "cargo": "cargo",
            "fuel": "nh3",
            "efficiency": 0.003,
            **ship,
        },
    ]
    fleet_routes = [{"process": "rt", "fleet_id": f} for f in candidates]
    return {
        "meta": [{"key": "base_year", "value": 2025}],
        "periods": [{"year": 2025}],
        "commodities": [
            {
                "commodity_id": "cargo",
                "kind": "material",
                "unit": "kt",
                "purchasable": 0,
                "sellable": 0,
            },
            {"commodity_id": "prod", "kind": "product", "unit": "kt"},
            {"commodity_id": "hfo", "kind": "energy", "unit": "t", "price": 500.0},
            {"commodity_id": "nh3", "kind": "energy", "unit": "t", "price": 700.0},
        ],
        "impacts": [{"impact_id": "co2", "unit": "t"}],
        "impact_prices": [{"impact_id": "co2", "year": 2025, "price": co2_price}],
        "commodity_impacts": [
            {"commodity_id": "hfo", "impact_id": "co2", "factor": 3.0},
            {"commodity_id": "nh3", "impact_id": "co2", "factor": 0.0},
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
                "label": "KR",
                "parent_id": "vc",
                "lon": 129.0,
                "lat": 35.0,
            },
            {
                "node_id": "vc/kr/plant",
                "kind": "machine",
                "level": "machine",
                "label": "plant",
                "parent_id": "vc/kr",
            },
            {
                "node_id": "vc/dst",
                "kind": "group",
                "level": "company",
                "label": "DST",
                "parent_id": "vc",
                "lon": 151.0,
                "lat": -34.0,
            },
            {
                "node_id": "vc/dst/term",
                "kind": "machine",
                "level": "machine",
                "label": "term",
                "parent_id": "vc/dst",
            },
        ],
        "machines": [
            {"machine_id": "vc/kr/plant", "baseline_technology": "make", "capacity": 1e7},
            {"machine_id": "vc/dst/term", "baseline_technology": "deliver", "capacity": 1e7},
        ],
        "connections": [{"from_node": "vc/kr", "to_node": "vc/dst", "commodity_id": "cargo"}],
        "routes": [
            {
                "process": "rt",
                "from_node": "vc/kr",
                "to_node": "vc/dst",
                "commodity": "cargo",
                "mode": "sea",
                "distance": distance,
                **({"blocked": "true"} if blocked else {}),
            }
        ],
        "fleet_groups": [{"group_id": "c", "label": "Carrier", "level": "company"}],
        **({"fleet": fleet, "fleet_routes": fleet_routes} if with_fleets else {}),
        "demand": [{"company": "vc/dst", "commodity_id": "prod", "year": 2025, "amount": _DEMAND}],
        **(
            {
                "impact_caps": [
                    {"company": "all", "impact_id": "co2", "limit": co2_cap, "soft": False}
                ]
            }
            if co2_cap is not None
            else {}
        ),
    }


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    return extract_results(solve(build(assemble_problem(wb, _SC)))).copy()


def _chosen(res: dict[str, Any]) -> dict[str, int]:
    """fleet_id -> ships, for the connection-route legs (process 'rt')."""
    return {
        str(r["fleet"]): int(r["ships"])
        for r in res["outputs"]["fleet"]
        if r.get("process") == "rt" and int(r["ships"]) > 0
    }


def _delivered(res: dict[str, Any]) -> float:
    # The destination terminal's throughput is the product delivered to demand.
    return sum(
        float(r["value"]) for r in res["outputs"]["throughput"] if r.get("process") == "vc/dst/term"
    )


def test_no_carbon_price_picks_the_cheap_dirty_fleet() -> None:
    res = _solve(_wb(co2_price=0.0))
    assert res["status"] == "optimal"
    chosen = _chosen(res)
    assert "dirty" in chosen and "clean" not in chosen  # cheap HFO wins with no carbon price
    assert abs(_delivered(res) - _DEMAND) < 1e-6  # demand met


def test_high_carbon_price_flips_to_the_clean_fleet() -> None:
    # HFO landed-fuel CO2 cost overtakes the NH3 fuel premium once CO2 is dear.
    res = _solve(_wb(co2_price=300.0))
    assert res["status"] == "optimal"
    chosen = _chosen(res)
    assert "clean" in chosen and "dirty" not in chosen  # zero-CO2 fleet wins
    assert abs(_delivered(res) - _DEMAND) < 1e-6


def test_longer_lane_needs_more_carriers() -> None:
    near = _chosen(_solve(_wb(distance=4000.0)))
    far = _chosen(_solve(_wb(distance=16000.0)))
    # Same demand + ship geometry: the longer lane (fewer round trips) needs more ships.
    assert sum(far.values()) > sum(near.values())


def test_blocked_corridor_stops_delivery() -> None:
    res = _solve(_wb(blocked=True))
    assert res["status"] == "optimal"
    assert not _chosen(res)  # no carriers run a closed corridor
    assert _delivered(res) < _DEMAND  # the stream can't reach the market


def test_physicalised_without_a_fleet_stays_virtual_teleport() -> None:
    # A route but NO fleets: the connection is unaffected (free instant delivery).
    res = _solve(_wb(with_fleets=False))
    assert res["status"] == "optimal"
    assert not _chosen(res)  # nothing reported as fleet-carried
    assert abs(_delivered(res) - _DEMAND) < 1e-6  # demand still fully met (teleport)


def test_transport_emissions_count_toward_a_hard_co2_cap() -> None:
    # No carbon price → HFO is cheapest, but a hard CO2 cap forbids its fuel
    # emissions, so the optimiser must switch to the zero-CO2 fleet. Proves the
    # route's fuel emissions enter the impact-cap inventory.
    res = _solve(_wb(co2_price=0.0, co2_cap=1000.0))
    assert res["status"] == "optimal"
    chosen = _chosen(res)
    assert "clean" in chosen and "dirty" not in chosen
    assert abs(_delivered(res) - _DEMAND) < 1e-6
    co2 = sum(float(s["total"]) for s in res["summary"]["impacts"] if s["impact"] == "co2")
    assert co2 <= 1000.0 + 1e-6  # the cap (incl. transport) holds


def test_lcia_objective_minimises_transport_emissions() -> None:
    # objective_impact = co2 with a large weight, no carbon price → minimising the
    # inventory (which now includes transport) picks the zero-CO2 fleet.
    sc = ScenarioConfig.from_dict(
        {
            "economics": {"base_year": 2025, "discount_rate": 0.0},
            "optimisation_scope": "system",
            "objective_impact": "co2",
            "impact_weight": 1.0e6,
        }
    )
    res = extract_results(solve(build(assemble_problem(_wb(co2_price=0.0), sc)))).copy()
    assert res["status"] == "optimal"
    chosen = _chosen(res)
    assert "clean" in chosen and "dirty" not in chosen


def test_blocked_corridor_reroutes_the_far_lane() -> None:
    # Loading the shipped multi-fleet example: closing Suez reroutes the EU lane
    # (longer) but leaves the AU lane (which never uses Suez) untouched — geographic
    # corridor blocking, not a per-lane on/off.
    from pathlib import Path

    from pathwise.api.workbook_io import parse_sqlite

    wb = parse_sqlite(Path("src/pathwise/assets/examples/fleet_candidates.sqlite").read_bytes())
    base = {cr.process: cr.distance for cr in assemble_problem(wb, _SC).connection_routes}
    blocked = {
        cr.process: cr.distance
        for cr in assemble_problem(
            {**wb, "corridors": [{"corridor": "suez", "blocked": True}]}, _SC
        ).connection_routes
    }
    assert blocked["rt_eu"] > base["rt_eu"] + 1000.0  # the far lane reroutes around Suez
    assert abs(blocked["rt_au"] - base["rt_au"]) < 1.0  # the near lane is unaffected


def test_single_candidate_is_forced() -> None:
    # Only the clean fleet may run the lane → it is used even with no carbon price.
    res = _solve(_wb(co2_price=0.0, candidates=("clean",)))
    assert res["status"] == "optimal"
    assert set(_chosen(res)) == {"clean"}
    assert abs(_delivered(res) - _DEMAND) < 1e-6
