"""Build the shipping-carrier fleet-transition example (assets/examples/shipping_carrier.sqlite).

A single carrier runs ~100 ships on three trade lanes out of Korea — to Australia,
the US and the EU — with a mix of fuels (HFO / LNG) and vintages. From 2030 any
ship can re-engine to ammonia (zero tank-to-wake CO2). Each counterpart prices the
lane's emissions differently (EU highest, then US, AU lowest), modelled as
region-tagged CO2 impacts priced via ``impact_prices`` — so the optimiser shows
the "balloon effect": the carrier decarbonises the high-price lane first while the
lax-policy lanes keep burning fossil.

Annual-capacity assets: a ship cohort's ``capacity`` is its ships × annual cargo
throughput; cross-lane reallocation (a shared fleet split by route) is the deferred
Layer-1b MILP and is NOT modelled here — each cohort serves its own lane.

Run:  uv run python scripts/build_shipping_carrier.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pathwise.api.workbook_io import write_sqlite

YEARS = [2025, 2030, 2035, 2040, 2045, 2050]
SHIP_KT = 100.0  # one ship moves 100 kt cargo / yr

# Fuel: price [$/MT] and tank-to-wake CO2 [t CO2 / MT]. Ammonia unlocks in 2030.
FUELS = {
    "hfo": {"price": 500.0, "co2": 3.10},
    "lng": {"price": 750.0, "co2": 2.75},
    "ammonia": {"price": 900.0, "co2": 0.0},
}

# Lane: fuel intensity [MT fuel / kt cargo] (∝ distance), annual demand [kt],
# and the existing fleet {fuel: (ships, vintage_year)}.
LANES = {
    "au": {
        "label": "Australia",
        "intensity": 8.0,
        "demand": 3000.0,
        "fleet": {"hfo": (18, 2010), "lng": (12, 2018)},
    },
    "us": {
        "label": "US",
        "intensity": 12.0,
        "demand": 3500.0,
        "fleet": {"hfo": (20, 2008), "lng": (15, 2016)},
    },
    "eu": {
        "label": "EU",
        "intensity": 14.0,
        "demand": 3500.0,
        "fleet": {"hfo": (22, 2010), "lng": (13, 2017)},
    },
}

# Per-region CO2 price path [$/t]. EU (ETS + FuelEU) highest; AU lowest.
CO2_PRICE = {
    "eu": [90, 150, 210, 270, 320, 360],
    "us": [40, 60, 80, 100, 115, 125],
    "au": [15, 25, 35, 45, 55, 65],
}

# Re-engine to ammonia: capital cost per unit annual capacity [$/(kt/yr)].
REENGINE_CAPEX = 800.0


def build() -> dict[str, list[dict[str, Any]]]:
    commodities: list[dict[str, Any]] = [
        {"commodity_id": "cargo_kr", "kind": "material", "unit": "kt", "price": 0.0},
    ]
    for r in LANES:
        commodities.append({"commodity_id": f"cargo_{r}", "kind": "product", "unit": "kt"})
    for f, spec in FUELS.items():
        commodities.append(
            {"commodity_id": f, "kind": "energy", "unit": "MT", "price": spec["price"]}
        )

    impacts = [{"impact_id": f"co2_{r}", "unit": "t"} for r in LANES]
    impacts.append({"impact_id": "co2_total", "unit": "t"})
    # Roll the region-tagged emissions up into one reportable total.
    characterisation = [
        {"flow_impact_id": f"co2_{r}", "category_id": "co2_total", "factor": 1.0} for r in LANES
    ]

    technologies: list[dict[str, Any]] = []
    io: list[dict[str, Any]] = []
    for r, lane in LANES.items():
        intensity = float(lane["intensity"])
        for f, spec in FUELS.items():
            tech = f"ship_{r}_{f}"
            t: dict[str, Any] = {
                "technology_id": tech,
                "lifespan": 25,
                "actions": "continue,replace,renew",
            }
            if f == "ammonia":
                t["introduction_year"] = 2030  # the new engine unlocks in 2030
            technologies.append(t)
            io.append(
                {"technology_id": tech, "target": "cargo_kr", "role": "input", "coefficient": 1.0}
            )
            io.append(
                {"technology_id": tech, "target": f, "role": "input", "coefficient": intensity}
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
            co2 = intensity * float(spec["co2"])  # t CO2 / kt cargo on this lane
            if co2 > 0:
                io.append(
                    {
                        "technology_id": tech,
                        "target": f"co2_{r}",
                        "role": "impact",
                        "coefficient": co2,
                    }
                )

    # Fleet cohorts (machines): each = a group of same-fuel, same-vintage ships on a lane.
    machines: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    for r, lane in LANES.items():
        for f, (ships, vintage) in lane["fleet"].items():
            machines.append(
                {
                    "machine_id": f"vc/{r}/{f}_{vintage}",
                    "baseline_technology": f"ship_{r}_{f}",
                    "capacity": ships * SHIP_KT,
                    "introduced_year": vintage,
                }
            )
            # Re-engine that cohort to ammonia (replace), available once ammonia unlocks.
            transitions.append(
                {
                    "from_technology": f"ship_{r}_{f}",
                    "to_technology": f"ship_{r}_ammonia",
                    "action": "replace",
                    "capex_per_capacity": REENGINE_CAPEX,
                }
            )

    impact_prices = [
        {"impact_id": f"co2_{r}", "year": y, "price": CO2_PRICE[r][i]}
        for r in LANES
        for i, y in enumerate(YEARS)
    ]

    demand = [
        {"company": f"vc/{r}", "commodity_id": f"cargo_{r}", "year": y, "amount": lane["demand"]}
        for r, lane in LANES.items()
        for y in YEARS
    ]

    nodes = [
        {
            "node_id": "vc",
            "kind": "group",
            "level": "value_chain",
            "label": "Shipping carrier",
            "parent_id": None,
        }
    ]
    for r, lane in LANES.items():
        nodes.append(
            {
                "node_id": f"vc/{r}",
                "kind": "group",
                "level": "lane",
                "label": f"KR–{lane['label']}",
                "parent_id": "vc",
            }
        )
        for f, (_, vintage) in lane["fleet"].items():
            nodes.append(
                {
                    "node_id": f"vc/{r}/{f}_{vintage}",
                    "kind": "machine",
                    "level": "machine",
                    "label": f"{f.upper()} ships ({vintage})",
                    "parent_id": f"vc/{r}",
                }
            )

    return {
        "meta": [
            {"key": "title", "value": "Shipping carrier — fleet transition (KR ↔ AU/US/EU)"},
            {"key": "base_year", "value": 2025},
            {"key": "currency", "value": "USD"},
        ],
        "periods": [{"year": y, "duration_years": 5} for y in YEARS],
        "commodities": commodities,
        "impacts": impacts,
        "characterisation": characterisation,
        "technologies": technologies,
        "io": io,
        "machines": machines,
        "transitions": transitions,
        "impact_prices": impact_prices,
        "demand": demand,
        "nodes": nodes,
    }


def main() -> None:
    out = (
        Path(__file__).resolve().parents[1] / "src/pathwise/assets/examples/shipping_carrier.sqlite"
    )
    out.write_bytes(write_sqlite(build()))
    total_ships = sum(s for lane in LANES.values() for s, _ in lane["fleet"].values())
    print(f"wrote {out} — {total_ships} ships, {len(LANES)} lanes, {len(YEARS)} periods")


if __name__ == "__main__":
    main()
