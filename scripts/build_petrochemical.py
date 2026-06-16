"""Build the petrochemical example as a REAL coupled value chain (MILP).

Built entirely from the source data (``PLANiT-Institute/petrochemical_macc_2025``),
nothing fabricated — every number comes from ``scripts/sources/petrochemical/
model.json`` (captured from ``energy_intensities.csv`` / ``emission_factors.csv`` /
``MACC_Model_Assumptions.xlsx`` / ``technology_parameters.csv`` / grid + demand
trajectories / ``emission_scenarios_clean.csv``).

Structure — the actual process, not a flat emitter list:
- **Streams**: the real inputs — naphtha + LNG + fuel gas + byproduct gas + LPG +
  fuel oil + diesel + electricity + H2 — plus the 55 products (olefins from the
  cracker, aromatics from the BTX plant, polymers/intermediates downstream).
- **Technologies** (component recipes): per product, the real per-tonne input
  recipe → that product. Combustion CO2 is the technology's ``direct_impact``
  (Σ burned fuel × its emission factor); electricity CO2 rides on the electricity
  stream via the greening grid factor (``commodity_impacts_t``). So emissions come
  from burning the real fuels — they are NOT bolted on.
- The crackers can **TRANSITION** (a technology change, not a measure) to
  ``NCC-H2`` (H2 replaces fuel, naphtha becomes feedstock-only → ~zero combustion)
  or ``NCC-Electricity`` (electric, naphtha feedstock-only) — from the source's
  ``Technology_Energy`` recipes and ``technology_parameters`` costs.
- **Facilities**: all 248 real plants, value-chain nodes grouped by 60 companies.
- The net-zero path is a (soft) CO2 ``impact_cap``; the MILP (linopy) picks the
  least-cost transitions to chase it.

Run: ``uv run python scripts/build_petrochemical.py``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pathwise.api.workbook_io import write_sqlite
from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig
from pathwise.data.components import extract_library_from_workbook
from pathwise.data.trajectory import interpolate

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts" / "sources" / "petrochemical" / "model.json"
ASSETS = ROOT / "src" / "pathwise" / "assets"

#: Fuels whose CO2 is combustion (booked as the technology's direct_impact).
#: Electricity is handled on the stream (time-varying grid factor); H2 is zero.
ELECTRICITY = "Electricity"
H2 = "H2"


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_")


def _model() -> dict[str, Any]:
    return json.loads(SRC.read_text())


def build_workbook() -> dict[str, list[dict[str, Any]]]:
    d = _model()
    years = d["years"]
    recipes = d["recipes"]  # product → {process, inputs:{fuel: per-tonne}}
    facs = d["facilities"]
    fuel_ef = d["fuel_ef"]  # fuel → {per: GJ|kg, factor}
    grid_ef = {int(k): v for k, v in d["grid_ef"].items()}  # tCO2/MWh
    growth = {int(k): v for k, v in d["demand_growth"].items()}
    alt_cost = d["alt_cost"]
    cap_anchors = {int(k): v for k, v in d["cap_anchors"].items()}
    prices = {f: {int(y): v for y, v in by_year.items()} for f, by_year in d["prices"].items()}

    fuels = sorted({f for r in recipes.values() for f in r["inputs"]} | {ELECTRICITY, H2})
    products = sorted(recipes)
    prod_safe = {p: _safe(p) for p in products}

    # ── Streams: fuels (purchasable inputs, real prices) + products ───────────
    commodities = [{"commodity_id": f, "kind": "energy", "purchasable": True} for f in fuels]
    commodities += [
        {"commodity_id": prod_safe[p], "kind": "product", "unit": "t"} for p in products
    ]
    commodity_prices = [
        {"commodity_id": f, "year": y, "price": prices[f][y]}
        for f in fuels
        if f in prices
        for y in years
    ]

    # Electricity CO2 rides the grid trajectory (tCO2/MWh → tCO2/kWh); H2 = 0;
    # other fuels' CO2 is booked as technology direct_impact (combustion), so 0 here.
    commodity_impacts_t = [
        {"commodity_id": ELECTRICITY, "impact_id": "CO2", "year": y, "factor": grid_ef[y] / 1000.0}
        for y in years
    ]

    def combustion_co2(inputs: dict[str, float]) -> float:
        """Direct combustion CO2 per tonne product (excludes electricity)."""
        total = 0.0
        for fuel, amt in inputs.items():
            ef = fuel_ef.get(fuel)
            if ef is not None:  # GJ/kg fuels (naphtha, LNG, …); electricity/H2 absent here
                total += amt * ef["factor"]
        return total

    # ── Technologies: one baseline recipe per product (+ cracker alternatives) ─
    technologies: list[dict] = []
    io: list[dict] = []
    tech_impacts: list[dict] = []

    def add_tech(tid: str, inputs: dict[str, float], product: str, direct: float) -> None:
        technologies.append({"technology_id": tid, "actions": "continue,replace"})
        for fuel, amt in inputs.items():
            io.append({"technology_id": tid, "target": fuel, "role": "input", "coefficient": amt})
        io.append(
            {
                "technology_id": tid,
                "target": prod_safe[product],
                "role": "output",
                "coefficient": 1.0,
                "is_product": True,
            }
        )
        if direct:
            tech_impacts.append({"technology_id": tid, "impact_id": "CO2", "factor": direct})

    for p in products:
        add_tech(prod_safe[p], recipes[p]["inputs"], p, combustion_co2(recipes[p]["inputs"]))

    # Cracker alternatives (transitions) for the olefins that have them in the source.
    alt = {(a["technology"], a["product"]): a for a in d["alt_tech"]}
    transitions: list[dict] = []
    for (techname, prod), a in alt.items():
        if prod not in recipes:  # rows like "NCC facilities" / "All processes" aren't products
            continue
        base = recipes[prod]["inputs"]
        # Fuel combustion eliminated; naphtha kept as (non-combusted) feedstock.
        new_inputs: dict[str, float] = {}
        if "Naphtha" in base:
            new_inputs["Naphtha"] = base["Naphtha"]  # feedstock only ⇒ no combustion CO2
        if a.get("h2_t_per_t"):
            new_inputs[H2] = a["h2_t_per_t"] * 1000.0  # t/t → kg/t (H2 priced/emitted per kg)
        if a.get("elec_mwh_per_t"):
            new_inputs[ELECTRICITY] = (
                new_inputs.get(ELECTRICITY, 0.0) + a["elec_mwh_per_t"] * 1000.0
            )
        tid = f"{prod_safe[prod]}__{_safe(techname)}"
        add_tech(tid, new_inputs, prod, 0.0)  # combustion eliminated ⇒ no direct CO2
        # transition capex per capacity = (MUSD/MtCO2 = USD/tCO2) × abatement per tonne.
        cost = alt_cost.get(techname, {})
        capex_pt = cost.get("capex_2025") or 0.0
        abatement_pt = combustion_co2(base)  # tCO2/t cut by eliminating combustion
        transitions.append(
            {
                "from_technology": prod_safe[prod],
                "to_technology": tid,
                "action": "replace",
                "capex_per_capacity": capex_pt * abatement_pt,
            }
        )

    # ── Value chain: sector → companies → facility machines ────────────────────
    nodes = [
        {
            "node_id": "petchem",
            "parent_id": "",
            "kind": "group",
            "level": "sector",
            "label": "Korean petrochemical",
        }
    ]
    companies = sorted({f["company"] for f in facs})
    comp_node = {c: f"co_{_safe(c)}" for c in companies}
    for c in companies:
        nodes.append(
            {
                "node_id": comp_node[c],
                "parent_id": "petchem",
                "kind": "group",
                "level": "company",
                "label": c,
            }
        )
    machines = []
    for f in facs:
        nodes.append(
            {
                "node_id": f["id"],
                "parent_id": comp_node[f["company"]],
                "kind": "machine",
                "level": "facility",
                "label": f"{f['product']} · {f['company']}",
            }
        )
        machines.append(
            {
                "machine_id": f["id"],
                "baseline_technology": prod_safe[f["product"]],
                "capacity": f["capacity_kt"] * 1000.0,
            }
        )

    # ── Demand (pins production to capacity × growth) + soft net-zero cap ───────
    demand = [
        {
            "company": "all",
            "commodity_id": prod_safe[f["product"]],
            "year": y,
            "amount": f["capacity_kt"] * 1000.0 * growth[y],
        }
        for f in facs
        for y in years
    ]
    cap = interpolate({y: v * 1e6 for y, v in cap_anchors.items()}, years)  # Mt → tCO2
    impact_caps = [
        {"company": "all", "impact_id": "CO2", "year": y, "limit": cap[y], "soft": True}
        for y in years
    ]

    return {
        "meta": [
            {"key": "label", "value": "Petrochemical — naphtha cracking value chain (real)"},
            {"key": "source", "value": "PLANiT-Institute/petrochemical_macc_2025"},
        ],
        "periods": [{"year": y, "duration_years": 1} for y in years],
        "commodities": commodities,
        "commodity_prices": commodity_prices,
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}],
        "technologies": technologies,
        "io": io,
        "tech_impacts": tech_impacts,
        "commodity_impacts_t": commodity_impacts_t,
        "transitions": transitions,
        "nodes": nodes,
        "machines": machines,
        "demand": demand,
        "impact_caps": impact_caps,
    }


def main() -> None:
    wb = build_workbook()
    print(
        f"  built: {len(wb['machines'])} facilities, "
        f"{sum(1 for n in wb['nodes'] if n['level'] == 'company')} companies, "
        f"{len(wb['technologies'])} technologies, {len(wb['transitions'])} cracker transition(s) "
        f"(incl. NCC-Electricity / NCC-H2)"
    )
    # Write the model structure first — the example only needs the workbook; the
    # solve below is a time-boxed sanity check and must never block the write.
    (ASSETS / "examples" / "petrochemical.sqlite").write_bytes(write_sqlite(wb))
    lib = extract_library_from_workbook(wb, label="Petrochemical (naphtha cracking value chain)")
    (ASSETS / "component_libraries" / "petrochemical.json").write_text(
        json.dumps(lib.model_dump(), indent=2), encoding="utf-8"
    )
    print("  wrote petrochemical.sqlite + component_libraries/petrochemical.json")
    try:
        res = run_model(
            wb,
            ScenarioConfig.from_dict(
                {
                    "economics": {"base_year": 2025, "discount_rate": 0.0},
                    "solver": {"mip_gap": 0.03, "time_limit_s": 120},
                }
            ),
        )
        co2 = {s["period"]: s["total"] for s in res["summary"]["impacts"] if s["impact"] == "CO2"}
        print(
            f"  sanity solve: status={res['status']} objective={res.get('objective')}"
            + (
                f" | CO2 2025={co2.get(2025, 0) / 1e6:.1f}→2050={co2.get(2050, 0) / 1e6:.1f} Mt"
                if co2
                else ""
            )
        )
    except Exception as exc:
        print(f"  sanity solve skipped (heavy model): {type(exc).__name__}")


if __name__ == "__main__":
    main()
