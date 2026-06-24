"""Build the candidate-fleet example (assets/examples/fleet_candidates.sqlite).

The Layer-1c+ demonstration: value-chain stream connections made **physical** and
served by a fleet the optimiser *chooses* from a candidate set. A Korean exporter
ships one cargo to two markets — Australia (near) and Europe (far, via Suez). Each
lane is a value-chain connection (``KR → market``) physicalised into a route; the
carrier owns several fleet TYPES (HFO / LNG / ammonia) and only SOME may run each
lane:

  * KR→Australia (lax policy)  — candidates: HFO, LNG
  * KR→Europe    (strict)      — candidates: LNG, ammonia

Distance drives both the carriers needed (a longer lane ⇒ fewer round trips ⇒ more
ships) and the fuel burned (efficiency × distance × cargo), priced at the fuel's
price + the carbon price on its CO2. As the CO2 price rises 2025→2050 the optimiser
switches the chosen fleet: HFO→LNG on the AU lane and LNG→ammonia on the EU lane —
the "which fleet on which lane, and when" decision. Unphysicalised connections stay
virtual (teleport); see ``core/build.py:_connection_fleet``.

Run:  uv run python scripts/build_fleet_candidates.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pathwise.api.workbook_io import write_sqlite
from pathwise.routing import route_distance_km

# Ports (lon, lat). Busan loads; the rest are destination markets.
BUSAN = (129.04, 35.10)
SYDNEY = (151.21, -33.87)
ROTTERDAM = (4.48, 51.95)

DEMAND_KT = 2000.0  # delivered cargo per market [kt / yr]
YEARS = [2025, 2030, 2040, 2050]
CO2_PRICE = {2025: 30.0, 2030: 70.0, 2040: 130.0, 2050: 200.0}  # $/t CO2 (rising)

# Common ship physics (so the carriers-needed = same per lane across fleets → the
# fleet choice is driven purely by fuel cost + carbon, not by ship geometry).
SHIP = {"ship_size": 50.0, "speed": 600.0, "turnaround_days": 4.0, "operating_days": 330.0}

# Fleet types: fuel, price [$/t], CO2 [t/t fuel], efficiency [t fuel / kt cargo / km].
FLEETS = {
    "hfo": {"label": "HFO ships", "fuel": "hfo", "price": 500.0, "co2": 3.10, "eff": 0.0030},
    "lng": {"label": "LNG ships", "fuel": "lng", "price": 600.0, "co2": 2.75, "eff": 0.0028},
    "ammonia": {
        "label": "Ammonia ships",
        "fuel": "ammonia",
        "price": 900.0,
        "co2": 0.0,
        "eff": 0.0035,
    },
}
# Lanes: market node, port, demand product, and which fleets MAY run it (some, not all).
LANES = {
    "au": {"label": "Australia", "port": SYDNEY, "candidates": ["hfo", "lng"]},
    "eu": {"label": "Europe", "port": ROTTERDAM, "candidates": ["lng", "ammonia"]},
}
OPEX_PER_SHIP = 2.0e6  # $/ship/yr (identical → neutral to the choice, realistic)
SHIP_COUNT = 60.0  # ample pool per fleet (the choice is economic, not capacity-bound)


def build() -> dict[str, list[dict[str, Any]]]:
    commodities: list[dict[str, Any]] = [
        # The shipped stream: made in KR, not buyable/sellable elsewhere ⇒ it MUST
        # travel the physical route to reach a market.
        {
            "commodity_id": "cargo",
            "kind": "material",
            "unit": "kt",
            "purchasable": 0,
            "sellable": 0,
        },
    ]
    for f in FLEETS.values():
        commodities.append(
            {"commodity_id": f["fuel"], "kind": "energy", "unit": "t", "price": f["price"]}
        )
    impacts = [{"impact_id": "co2", "unit": "t"}]
    impact_prices = [{"impact_id": "co2", "year": y, "price": p} for y, p in CO2_PRICE.items()]
    commodity_impacts = [
        {"commodity_id": f["fuel"], "impact_id": "co2", "factor": f["co2"]} for f in FLEETS.values()
    ]

    technologies: list[dict[str, Any]] = [{"technology_id": "make", "opex": 0.01}]
    io: list[dict[str, Any]] = [
        {"technology_id": "make", "target": "cargo", "role": "output", "coefficient": 1.0},
    ]
    nodes: list[dict[str, Any]] = [
        {"node_id": "vc", "kind": "group", "level": "value_chain", "label": "Cargo exporter"},
        {
            "node_id": "vc/kr",
            "kind": "group",
            "level": "company",
            "label": "Korea export (Busan)",
            "parent_id": "vc",
            "lon": BUSAN[0],
            "lat": BUSAN[1],
        },
        {
            "node_id": "vc/kr/plant",
            "kind": "machine",
            "level": "machine",
            "label": "Cargo plant",
            "parent_id": "vc/kr",
        },
    ]
    machines: list[dict[str, Any]] = [
        {"machine_id": "vc/kr/plant", "baseline_technology": "make", "capacity": 1.0e7},
    ]
    connections: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    fleet_routes: list[dict[str, Any]] = []
    demand: list[dict[str, Any]] = []

    for lane, spec in LANES.items():
        prod = f"cargo_{lane}"
        commodities.append({"commodity_id": prod, "kind": "product", "unit": "kt"})
        tech = f"deliver_{lane}"
        technologies.append({"technology_id": tech, "opex": 0.01})
        io.append({"technology_id": tech, "target": "cargo", "role": "input", "coefficient": 1.0})
        io.append(
            {
                "technology_id": tech,
                "target": prod,
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            }
        )
        lon, lat = spec["port"]
        company = f"vc/{lane}"
        nodes.append(
            {
                "node_id": company,
                "kind": "group",
                "level": "company",
                "label": f"{spec['label']} import",
                "parent_id": "vc",
                "lon": lon,
                "lat": lat,
            }
        )
        nodes.append(
            {
                "node_id": f"{company}/term",
                "kind": "machine",
                "level": "machine",
                "label": f"{spec['label']} terminal",
                "parent_id": company,
            }
        )
        machines.append(
            {"machine_id": f"{company}/term", "baseline_technology": tech, "capacity": 1.0e7}
        )
        # The virtual stream connection (KR → market), then its physicalisation: a
        # route carrying that stream, plus the candidate fleets that MAY serve it.
        connections.append({"from_node": "vc/kr", "to_node": company, "commodity_id": "cargo"})
        rproc = f"rt_{lane}"
        dist = route_distance_km(BUSAN, (lon, lat), "sea")
        routes.append(
            {
                "process": rproc,
                "from_node": "vc/kr",
                "to_node": company,
                "commodity": "cargo",
                "mode": "sea",
                "distance": round(dist, 1),
            }
        )
        for fid in spec["candidates"]:
            fleet_routes.append({"process": rproc, "fleet_id": fid})
        for y in YEARS:
            demand.append(
                {"company": company, "commodity_id": prod, "year": y, "amount": DEMAND_KT}
            )

    fleet_groups = [
        {"group_id": "carrier_co", "parent_id": "", "label": "Carrier", "level": "company"}
    ]
    fleet = [
        {
            "fleet_id": fid,
            "label": f["label"],
            "group": "carrier_co",
            "company": "carrier",
            "mode": "sea",
            "cargo": "cargo",
            "fuel": f["fuel"],
            "efficiency": f["eff"],
            "opex": OPEX_PER_SHIP,
            "count": SHIP_COUNT,
            **SHIP,
        }
        for fid, f in FLEETS.items()
    ]

    return {
        "meta": [
            {
                "key": "title",
                "value": "Fleet candidates — optimiser picks the fleet per lane (KR→AU/EU)",
            },
            {"key": "base_year", "value": 2025},
            {"key": "currency", "value": "USD"},
        ],
        "periods": [{"year": y} for y in YEARS],
        "commodities": commodities,
        "impacts": impacts,
        "impact_prices": impact_prices,
        "commodity_impacts": commodity_impacts,
        "technologies": technologies,
        "io": io,
        "nodes": nodes,
        "machines": machines,
        "connections": connections,
        "routes": routes,
        "fleet_groups": fleet_groups,
        "fleet": fleet,
        "fleet_routes": fleet_routes,
        "demand": demand,
    }


def main() -> None:
    out = (
        Path(__file__).resolve().parents[1] / "src/pathwise/assets/examples/fleet_candidates.sqlite"
    )
    out.write_bytes(write_sqlite(build()))
    print(f"wrote {out} — {len(LANES)} physicalised lanes, {len(FLEETS)} candidate fleet types")


if __name__ == "__main__":
    main()
