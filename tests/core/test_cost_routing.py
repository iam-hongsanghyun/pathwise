"""Cost-weighted route selection: a lane's path is chosen to minimise
``fuel_price · efficiency · distance + toll / ship_size``, not just distance.

The KR→EU lane's shortest path crosses Suez. With a small Suez toll, crossing (and
paying) stays cheapest, so the assembled route keeps the short path. With a large
enough toll, the longer Cape-of-Good-Hope detour becomes cheaper, so the engine
selects THAT path instead — longer distance, zero toll. Asserted on the assembled
:class:`ConnectionRoute` (no solve needed). Uses searoute, like ``test_routing``.
"""

from __future__ import annotations

from typing import Any

from pathwise.data import ScenarioConfig, assemble_problem

_SC = ScenarioConfig.from_dict(
    {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
)


# c/km = efficiency · fuel_price = 0.01 · 500 = 5 $/cargo/km; the Suez detour adds
# ~3,940 km ⇒ ~19,700 $/cargo extra fuel. Per-cargo toll = toll / ship_size (50).
# Cross is cheaper while toll/50 < 19,700 (toll < ~985k); detour wins above that.
def _wb(*, suez_toll: float) -> dict[str, Any]:
    ship = {
        "ship_size": 50.0,
        "speed": 600.0,
        "turnaround_days": 4.0,
        "operating_days": 330.0,
        "count": 1000.0,
        "opex": 0.0,
    }
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
        ],
        "impacts": [{"impact_id": "co2", "unit": "t"}],
        "commodity_impacts": [{"commodity_id": "hfo", "impact_id": "co2", "factor": 0.0}],
        "technologies": [
            {"technology_id": "make", "opex": 0.0},
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
        "connections": [{"from_node": "vc/kr", "to_node": "vc/eu", "commodity_id": "cargo"}],
        # No authored distance ⇒ derived ⇒ cost-weighted path selection engages.
        "routes": [
            {
                "process": "rt",
                "from_node": "vc/kr",
                "to_node": "vc/eu",
                "commodity": "cargo",
                "mode": "sea",
            }
        ],
        "fleet": [
            {
                "fleet_id": "ship",
                "group": "c",
                "company": "carrier",
                "cargo": "cargo",
                "fuel": "hfo",
                "efficiency": 0.01,
                **ship,
            }
        ],
        "fleet_routes": [{"process": "rt", "fleet_id": "ship"}],
        "fleet_groups": [{"group_id": "c", "label": "Carrier", "level": "company"}],
        "corridors": [{"corridor": "suez", "toll": suez_toll}],
        "demand": [{"company": "vc/eu", "commodity_id": "prod", "year": 2025, "amount": 1000.0}],
    }


def _route(suez_toll: float) -> Any:
    prob = assemble_problem(_wb(suez_toll=suez_toll), _SC)
    crs = [cr for cr in prob.connection_routes if cr.process == "rt"]
    assert len(crs) == 1
    return crs[0]


def test_small_toll_keeps_the_short_suez_path() -> None:
    cr = _route(100_000.0)
    assert 18_000 < cr.distance < 22_000  # the short lane, via Suez
    assert cr.toll == 100_000.0  # crosses Suez ⇒ pays its toll


def test_large_toll_selects_the_cheaper_detour() -> None:
    cr = _route(3_000_000.0)
    assert cr.distance > 23_000  # the longer Cape-of-Good-Hope detour
    assert cr.toll == 0.0  # Suez avoided ⇒ no toll on the chosen path


def test_detour_is_actually_longer_than_the_suez_path() -> None:
    assert _route(3_000_000.0).distance > _route(100_000.0).distance
