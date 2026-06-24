"""Build the distance-driven fleet example (assets/examples/fleet_distance.sqlite).

The Layer-1c demonstration: a carrier delivers the **same** product volume from
Korea (Busan) to a NEAR market (Sydney) and a FAR market (Rotterdam, routed via
Suez). Sea distances come from the ``searoute`` provider, and a ship's annual
capacity falls with distance (fewer round trips), so the far lane needs **more
ships** for the identical demand — the physical-transport cost the optimiser sees.

Mechanism (see ``core/problem.py:Fleet.capacity_on`` + ``routing.py``):
  * any node carries lon/lat; a ``routes`` row gives a lane its endpoints + mode,
  * sea distance = searoute(from, to); capacity/ship = ship_size · op_days /
    (2·distance/speed + turnaround) — lower on the longer lane,
  * the shared fleet pool is sized to exactly meet both demands, so the split of
    ships across lanes is forced and the distance effect is plain in ``outputs.fleet``.

Run:  uv run python scripts/build_fleet_distance.py
"""

from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import Any

from pathwise.api.workbook_io import write_sqlite
from pathwise.routing import route_distance_km

# Ship physics (one interchangeable class).
SHIP_SIZE = 30.0  # kt cargo / voyage
SPEED = 700.0  # km / day
TURNAROUND = 4.0  # days / round trip (load + unload)
OPERATING_DAYS = 330.0  # in-service days / yr
DEMAND_KT = 1200.0  # identical demand on every lane [kt / yr]
EFFICIENCY = 0.003  # bunker burned per kt cargo per km [t / kt / km]
BUNKER_PRICE = 550.0  # $/t
BUNKER_CO2 = 3.10  # t CO2 / t bunker

# Ports: (lon, lat). Busan is the loading hub; the rest are destination markets.
BUSAN = (129.04, 35.10)
MARKETS = {
    "au": {"label": "Sydney", "lonlat": (151.21, -33.87)},
    "eu": {"label": "Rotterdam", "lonlat": (4.48, 51.95)},
}


def _capacity(distance: float) -> float:
    """Annual cargo one ship delivers on a route of length ``distance`` [kt/yr]."""
    round_trip = 2.0 * distance / SPEED + TURNAROUND
    return SHIP_SIZE * OPERATING_DAYS / round_trip


def build() -> dict[str, list[dict[str, Any]]]:
    commodities: list[dict[str, Any]] = [
        {"commodity_id": "cargo_kr", "kind": "material", "unit": "kt", "price": 0.0},
        {"commodity_id": "bunker", "kind": "energy", "unit": "t", "price": BUNKER_PRICE},
    ]
    impacts = [{"impact_id": "co2", "unit": "t"}]
    commodity_impacts = [{"commodity_id": "bunker", "impact_id": "co2", "factor": BUNKER_CO2}]
    technologies: list[dict[str, Any]] = []
    io: list[dict[str, Any]] = []
    for r in MARKETS:
        commodities.append({"commodity_id": f"cargo_{r}", "kind": "product", "unit": "kt"})
        tech = f"ship_{r}"
        technologies.append({"technology_id": tech, "opex": 1})
        io.append(
            {"technology_id": tech, "target": "cargo_kr", "role": "input", "coefficient": 1.0}
        )
        io.append(
            {
                "technology_id": tech,
                "target": f"cargo_{r}",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            }
        )

    # Node hierarchy: the carrier owns a lane (machine) per market; ports are place
    # nodes carrying coordinates (no machines, so they add no process).
    nodes: list[dict[str, Any]] = [
        {"node_id": "carrier", "kind": "group", "level": "value_chain", "label": "Carrier"},
        {
            "node_id": "busan",
            "kind": "group",
            "level": "port",
            "label": "Busan",
            "parent_id": "carrier",
            "lon": BUSAN[0],
            "lat": BUSAN[1],
        },
    ]
    machines: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    total_ships = 0
    for r, m in MARKETS.items():
        lon, lat = m["lonlat"]
        nodes.append(
            {
                "node_id": f"port_{r}",
                "kind": "group",
                "level": "port",
                "label": m["label"],
                "parent_id": "carrier",
                "lon": lon,
                "lat": lat,
            }
        )
        nodes.append(
            {
                "node_id": f"p_{r}",
                "kind": "machine",
                "level": "machine",
                "label": f"Busan–{m['label']} lane",
                "parent_id": "carrier",
            }
        )
        machines.append(
            {"machine_id": f"p_{r}", "baseline_technology": f"ship_{r}", "capacity": 1e7}
        )
        routes.append(
            {"process": f"p_{r}", "from_node": "busan", "to_node": f"port_{r}", "mode": "sea"}
        )
        dist = route_distance_km(BUSAN, (lon, lat), "sea")
        total_ships += ceil(DEMAND_KT / _capacity(dist))

    # One fleet class; the pool is sized to exactly cover both lanes, so the split is
    # forced and the longer lane's larger ship count is unambiguous in the output.
    fleet = [
        {
            "fleet_id": "ship",
            "company": "carrier",
            "mode": "sea",
            "cargo": "cargo_kr",
            "fuel": "bunker",
            "efficiency": EFFICIENCY,
            "ship_size": SHIP_SIZE,
            "speed": SPEED,
            "turnaround_days": TURNAROUND,
            "operating_days": OPERATING_DAYS,
            "count": float(total_ships),
        }
    ]
    fleet_routes = [{"process": f"p_{r}", "fleet_id": "ship"} for r in MARKETS]
    demand = [
        {"company": "carrier", "commodity_id": f"cargo_{r}", "year": 2025, "amount": DEMAND_KT}
        for r in MARKETS
    ]

    return {
        "meta": [
            {"key": "title", "value": "Fleet distance — ships scale with route length (KR→AU/EU)"},
            {"key": "base_year", "value": 2025},
            {"key": "currency", "value": "USD"},
        ],
        "periods": [{"year": 2025}],
        "commodities": commodities,
        "impacts": impacts,
        "commodity_impacts": commodity_impacts,
        "technologies": technologies,
        "io": io,
        "nodes": nodes,
        "machines": machines,
        "routes": routes,
        "fleet": fleet,
        "fleet_routes": fleet_routes,
        "demand": demand,
    }


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "src/pathwise/assets/examples/fleet_distance.sqlite"
    out.write_bytes(write_sqlite(build()))
    print(f"wrote {out} — {len(MARKETS)} lanes from Busan")


if __name__ == "__main__":
    main()
