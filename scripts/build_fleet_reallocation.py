"""Build the fleet-reallocation example (assets/examples/fleet_reallocation.sqlite).

The Layer-1b demonstration: a carrier owns ONE shared pool of ships and decides,
each year, how many to put on each of three lanes out of Korea (→ Australia, the
US, the EU). Ships are interchangeable — the fleet is a TABLE (a pool count), not
a box per vessel — and the optimiser reallocates them across lanes as demand
shifts. Total demand stays flat at 8 500 kt/yr, but it migrates from EU to AU over
2025→2050, so ships steam off the shrinking EU lane and onto the growing AU lane.

Mechanism (see ``core/build.py:_fleet``):
  * ``units[process, year]`` — integer ships assigned to a lane,
  * capacity-from-fleet  Σ_k x ≤ capacity·units  (one ship carries ``SHIP_KT`` kt/yr),
  * shared-pool          Σ_lane units ≤ available  (the fleet's in-service count).

The pool is sized to the binding requirement (85 ships = 8 500 / 100), so the
allocation is forced and the reallocation is plainly visible in ``outputs.fleet``.
Per-lane CO2 is region-tagged and priced (EU > US > AU) for reporting; with one
fuel and no abatement here the prices don't change the dispatch — the story is the
reallocation. For the policy "balloon effect" and re-engining, see
``shipping_carrier``.

Run:  uv run python scripts/build_fleet_reallocation.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pathwise.api.workbook_io import write_sqlite

YEARS = [2025, 2030, 2035, 2040, 2045, 2050]
SHIP_KT = 100.0  # one ship moves 100 kt cargo / yr (the per-route capacity share)
FLEET_SHIPS = 85.0  # shared pool: 8 500 kt total demand / 100 kt per ship

# bunker fuel: price [$/MT] and tank-to-wake CO2 [t CO2 / MT].
BUNKER_PRICE = 550.0
BUNKER_CO2 = 3.10

# Lane: fuel intensity [MT fuel / kt cargo] (∝ distance) and demand path [kt/yr].
# Total is flat at 8 500 every year; it migrates EU → AU over the horizon, so the
# shared pool has to reallocate ships from the shrinking lane to the growing one.
LANES = {
    "au": {
        "label": "Australia",
        "intensity": 8.0,
        "demand": [2000, 2400, 2800, 3200, 3600, 4000],
    },
    "us": {
        "label": "US",
        "intensity": 12.0,
        "demand": [3000, 3000, 3000, 3000, 3000, 3000],
    },
    "eu": {
        "label": "EU",
        "intensity": 14.0,
        "demand": [3500, 3100, 2700, 2300, 1900, 1500],
    },
}

# Per-region CO2 price path [$/t] (reporting flavour; EU highest, AU lowest).
CO2_PRICE = {
    "eu": [90, 150, 210, 270, 320, 360],
    "us": [40, 60, 80, 100, 115, 125],
    "au": [15, 25, 35, 45, 55, 65],
}


def build() -> dict[str, list[dict[str, Any]]]:
    commodities: list[dict[str, Any]] = [
        {"commodity_id": "cargo_kr", "kind": "material", "unit": "kt", "price": 0.0},
        {"commodity_id": "bunker", "kind": "energy", "unit": "MT", "price": BUNKER_PRICE},
    ]
    for r in LANES:
        commodities.append({"commodity_id": f"cargo_{r}", "kind": "product", "unit": "kt"})

    impacts = [{"impact_id": f"co2_{r}", "unit": "t"} for r in LANES]
    impacts.append({"impact_id": "co2_total", "unit": "t"})
    characterisation = [
        {"flow_impact_id": f"co2_{r}", "category_id": "co2_total", "factor": 1.0} for r in LANES
    ]

    technologies: list[dict[str, Any]] = []
    io: list[dict[str, Any]] = []
    for r, lane in LANES.items():
        intensity = float(lane["intensity"])
        tech = f"ship_{r}"
        technologies.append({"technology_id": tech, "lifespan": 25})
        io.append(
            {"technology_id": tech, "target": "cargo_kr", "role": "input", "coefficient": 1.0}
        )
        io.append(
            {"technology_id": tech, "target": "bunker", "role": "input", "coefficient": intensity}
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
        io.append(
            {
                "technology_id": tech,
                "target": f"co2_{r}",
                "role": "impact",
                "coefficient": intensity * BUNKER_CO2,  # t CO2 / kt cargo on this lane
            }
        )

    # Node hierarchy: one carrier owning a lane node (machine) per route. Capacity
    # is left high so the FLEET pool is the binding limit. The expanded process id
    # is the machine id (``p_au`` …) and its company resolves to the root carrier.
    nodes = [
        {"node_id": "carrier", "kind": "group", "level": "value_chain", "label": "Carrier"},
    ]
    machines = []
    for r, lane in LANES.items():
        nodes.append(
            {
                "node_id": f"p_{r}",
                "kind": "machine",
                "level": "machine",
                "label": f"KR–{lane['label']} lane",
                "parent_id": "carrier",
            }
        )
        machines.append(
            {"machine_id": f"p_{r}", "baseline_technology": f"ship_{r}", "capacity": 1e7}
        )

    # The fleet: one carrier class (a shared pool of ships) owned by the carrier,
    # carrying cargo at SHIP_KT per ship/yr, and the lanes (routes) it serves.
    fleet = [
        {
            "fleet_id": "ship",
            "company": "carrier",
            "mode": "sea",
            "cargo": "cargo_kr",
            "capacity": SHIP_KT,
            "count": FLEET_SHIPS,
        }
    ]
    fleet_routes = [{"process": f"p_{r}", "fleet_id": "ship"} for r in LANES]

    impact_prices = [
        {"impact_id": f"co2_{r}", "year": y, "price": CO2_PRICE[r][i]}
        for r in LANES
        for i, y in enumerate(YEARS)
    ]

    demand = [
        {"company": "carrier", "commodity_id": f"cargo_{r}", "year": y, "amount": lane["demand"][i]}
        for r, lane in LANES.items()
        for i, y in enumerate(YEARS)
    ]

    return {
        "meta": [
            {"key": "title", "value": "Fleet reallocation — shared ship pool (KR ↔ AU/US/EU)"},
            {"key": "base_year", "value": 2025},
            {"key": "currency", "value": "USD"},
        ],
        "periods": [{"year": y, "duration_years": 5} for y in YEARS],
        "commodities": commodities,
        "impacts": impacts,
        "characterisation": characterisation,
        "technologies": technologies,
        "io": io,
        "nodes": nodes,
        "machines": machines,
        "fleet": fleet,
        "fleet_routes": fleet_routes,
        "impact_prices": impact_prices,
        "demand": demand,
    }


def main() -> None:
    out = (
        Path(__file__).resolve().parents[1]
        / "src/pathwise/assets/examples/fleet_reallocation.sqlite"
    )
    out.write_bytes(write_sqlite(build()))
    print(f"wrote {out} — {int(FLEET_SHIPS)} ships, {len(LANES)} lanes, {len(YEARS)} periods")


if __name__ == "__main__":
    main()
