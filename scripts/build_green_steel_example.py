"""Build the cross-border green-steel value-chain example from clean components.

This is the *source* for two committed assets:
  * ``assets/component_libraries/green_steel.json`` — a reusable component library
    (technologies + streams + measures/MACCs + machine & group components), the
    clean building blocks the Component tab edits;
  * ``assets/examples/green_steel_chain.sqlite`` — the assembled value chain, built
    by INSTANTIATING the top-level group then adding the scenario sheets.

The model: iron ore + green H2 (Australia), blue H2 (Qatar), and — in Korea —
grid/renewable power, local green H2 (wind→electrolyser), an integrated steel
mill, an automaker and a shipbuilder. Imported gas, coal, scrap and (capped) HBI
are buyable. Each facility carries a MACC and the mill can transition its
iron-making (blast furnace → H2 direct reduction) and steel-making (BOF → EAF).
A rising carbon price and a declining CO2 cap drive the transition over
2025–2050.

Run ``uv run python scripts/build_green_steel_example.py`` to regenerate both
assets; it asserts the model solves at ``system`` and ``value_chain`` scope.
"""

from __future__ import annotations

import json
from pathlib import Path

from pathwise.api.workbook_io import write_sqlite
from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig
from pathwise.data.components import ComponentLibrary, instantiate

ASSETS = Path(__file__).resolve().parents[1] / "src" / "pathwise" / "assets"
YEARS = [2025, 2030, 2035, 2040, 2045, 2050]
CARBON = {2025: 15, 2030: 30, 2035: 55, 2040: 90, 2045: 140, 2050: 200}
# Declining CO2 cap as a fraction of the (dirty) 2025 baseline emissions.
CAP_FRAC = {2025: 0.82, 2030: 0.66, 2035: 0.50, 2040: 0.38, 2045: 0.27, 2050: 0.18}


# ── terse io / template builders ─────────────────────────────────────────────
def inp(target, coef, group=None, smin=None, smax=None):
    return {
        "target": target,
        "role": "input",
        "coefficient": coef,
        "is_product": False,
        "group": group,
        "share_min": smin,
        "share_max": smax,
    }


def out(target, coef, is_product=False):
    return {
        "target": target,
        "role": "output",
        "coefficient": coef,
        "is_product": is_product,
        "group": None,
        "share_min": None,
        "share_max": None,
    }


def co2(coef):
    return {
        "target": "CO2",
        "role": "impact",
        "coefficient": coef,
        "is_product": False,
        "group": None,
        "share_min": None,
        "share_max": None,
    }


def tech(tid, lifespan, capex, opex, io, maccs=()):
    return {
        "technology_id": tid,
        "lifespan": lifespan,
        "capex": capex,
        "opex": opex,
        "io": io,
        "maccs": list(maccs),
    }


def meas(mid, label, mtype, target, blocks, lifetime=15):
    return {
        "measure_id": mid,
        "label": label,
        "type": mtype,
        "target": target,
        "lifetime": lifetime,
        "blocks": blocks,
    }


def blk(reduction, capex, opex=0.0):
    return {"reduction": reduction, "capex_per_capacity": capex, "opex_per_capacity": opex}


def macc(mid, label, measures):
    return {"macc_id": mid, "label": label, "measures": measures}


def machine(name, label, technology, capacity):
    return {
        "name": name,
        "label": label,
        "technology": technology,
        "capacity": capacity,
        "measures": [],
    }


def group(name, label, level, children, connections=()):
    return {
        "name": name,
        "label": label,
        "level": level,
        "children": [{"component": c, "alias": a} for c, a in children],
        "connections": [
            {"source": s, "target": t, "commodity": cm, "lag_years": lg}
            for s, t, cm, lg in connections
        ],
    }


# ── the component library ─────────────────────────────────────────────────────
LIBRARY = {
    "label": "Green steel value chain",
    "commodities": [
        {
            "commodity_id": "iron_ore",
            "kind": "material",
            "unit": "t",
            "price": None,
            "sale_price": None,
        },
        {"commodity_id": "coal", "kind": "energy", "unit": "t", "price": 90.0, "sale_price": None},
        {"commodity_id": "gas", "kind": "energy", "unit": "GJ", "price": 9.0, "sale_price": None},
        {
            "commodity_id": "scrap",
            "kind": "material",
            "unit": "t",
            "price": None,
            "sale_price": None,
        },
        {"commodity_id": "hbi", "kind": "material", "unit": "t", "price": None, "sale_price": None},
        {
            "commodity_id": "electricity",
            "kind": "energy",
            "unit": "MWh",
            "price": None,
            "sale_price": None,
        },
        {
            "commodity_id": "hydrogen",
            "kind": "energy",
            "unit": "t",
            "price": None,
            "sale_price": None,
        },
        {
            "commodity_id": "iron",
            "kind": "material",
            "unit": "t",
            "price": None,
            "sale_price": None,
        },
        {
            "commodity_id": "steel",
            "kind": "product",
            "unit": "t",
            "price": None,
            "sale_price": 800.0,
        },
        {
            "commodity_id": "car",
            "kind": "product",
            "unit": "veh",
            "price": None,
            "sale_price": 30000.0,
        },
        {
            "commodity_id": "ship",
            "kind": "product",
            "unit": "ship",
            "price": None,
            "sale_price": 90000000.0,
        },
    ],
    "technologies": [
        tech("IronOreMine", 30, 50, 5, [out("iron_ore", 1.0), co2(0.03)], ["mine_co2"]),
        tech("WindFarm", 25, 1200, 30, [out("electricity", 1.0)]),
        tech(
            "Electrolyser",
            20,
            900,
            120,
            [inp("electricity", 50.0), out("hydrogen", 1.0), co2(0.0)],
            ["electro_eff"],
        ),
        tech(
            "SMR_CCS",
            25,
            1100,
            30,
            [inp("gas", 165.0), out("hydrogen", 1.0), co2(2.0)],
            ["smr_eff"],
        ),
        tech(
            "GridCCGT",
            25,
            700,
            4,
            [inp("gas", 7.0), out("electricity", 1.0), co2(0.4)],
            ["grid_eff"],
        ),
        # BF carries a token hydrogen co-injection input so the cross-border H2
        # connections wire to this machine — letting it TRANSITION to H2_DRI and
        # draw real hydrogen from the value chain (edges form off baseline io).
        tech(
            "BlastFurnace",
            30,
            900,
            20,
            [
                inp("iron_ore", 1.6),
                inp("coal", 0.6),
                inp("electricity", 0.05),
                inp("hydrogen", 0.005),
                out("iron", 1.0),
                co2(1.8),
            ],
            ["bf_abate"],
        ),
        tech(
            "H2_DRI",
            25,
            1000,
            25,
            [
                inp("iron_ore", 1.45),
                inp("hydrogen", 0.06),
                inp("electricity", 0.5),
                out("iron", 1.0),
                co2(0.1),
            ],
        ),
        tech(
            "BOF",
            25,
            400,
            15,
            [inp("iron", 1.05), inp("electricity", 0.1), out("steel", 1.0, True), co2(0.2)],
            ["bof_abate"],
        ),
        tech(
            "EAF",
            25,
            500,
            18,
            [
                inp("iron", 1.05, group="metallics", smin=0.0, smax=1.0),
                inp("scrap", 0.0, group="metallics", smin=0.0, smax=1.0),
                inp("hbi", 0.0, group="metallics", smin=0.0, smax=1.0),
                inp("electricity", 0.6),
                out("steel", 1.0, True),
                co2(0.1),
            ],
        ),
        tech(
            "Automaker",
            25,
            300,
            50,
            [inp("steel", 1.0), inp("electricity", 1.0), out("car", 1.0, True), co2(0.05)],
            ["auto_eff"],
        ),
        tech(
            "Shipbuilder",
            30,
            400,
            80,
            [inp("steel", 20000.0), inp("electricity", 5000.0), out("ship", 1.0, True), co2(200.0)],
            ["ship_eff"],
        ),
    ],
    "measures": [
        meas(
            "mine_co2", "Mine electrification", "emission_reduction", "CO2", [blk(0.10, 2.0, 0.1)]
        ),
        meas(
            "electro_eff",
            "Electrolyser stack upgrade",
            "energy_efficiency",
            "electricity",
            [blk(0.05, 5.0, 0.2)],
        ),
        meas(
            "smr_eff", "SMR capture uplift", "emission_reduction", "CO2", [blk(0.20, 20.0, 1.0)], 20
        ),
        meas(
            "grid_ccs",
            "CCGT carbon capture",
            "emission_reduction",
            "CO2",
            [blk(0.40, 60.0, 2.0)],
            20,
        ),
        meas(
            "bf_tgr",
            "Top-gas recovery + CCU",
            "emission_reduction",
            "CO2",
            [blk(0.08, 30.0, 1.0), blk(0.06, 70.0, 2.0)],
        ),
        meas(
            "bf_ccs",
            "Blast-furnace carbon capture",
            "emission_reduction",
            "CO2",
            [blk(0.15, 120.0, 4.0)],
            20,
        ),
        meas("bof_abate", "BOF gas recovery", "emission_reduction", "CO2", [blk(0.10, 10.0, 0.5)]),
        meas(
            "auto_eff",
            "Plant electricity efficiency",
            "energy_efficiency",
            "electricity",
            [blk(0.06, 3.0, 0.2)],
        ),
        meas(
            "ship_eff",
            "Yard electricity efficiency",
            "energy_efficiency",
            "electricity",
            [blk(0.05, 5.0, 0.3)],
        ),
    ],
    "maccs": [
        macc("mine_co2", "Mine abatement", ["mine_co2"]),
        macc("electro_eff", "Electrolyser efficiency", ["electro_eff"]),
        macc("smr_eff", "Blue-H2 abatement", ["smr_eff"]),
        macc("grid_eff", "Grid abatement", ["grid_ccs"]),
        macc("bf_abate", "Blast-furnace abatement", ["bf_tgr", "bf_ccs"]),
        macc("bof_abate", "BOF abatement", ["bof_abate"]),
        macc("auto_eff", "Automaker efficiency", ["auto_eff"]),
        macc("ship_eff", "Shipyard efficiency", ["ship_eff"]),
    ],
    "machines": [
        machine("mine", "Iron-ore mine", "IronOreMine", 5_000_000),
        machine("wind", "Wind farm", "WindFarm", 30_000_000),
        machine("electrolyser", "Electrolyser", "Electrolyser", 250_000),
        machine("smr", "SMR + CCS", "SMR_CCS", 250_000),
        machine("grid", "CCGT grid", "GridCCGT", 30_000_000),
        machine("bf", "Blast furnace", "BlastFurnace", 2_500_000),
        machine("bof", "Basic oxygen furnace", "BOF", 2_500_000),
        machine("assembly", "Vehicle assembly", "Automaker", 1_500_000),
        machine("shipyard", "Shipyard", "Shipbuilder", 100),
    ],
    "groups": [
        group("au_ironore", "AU Iron Ore", "company", [("mine", "")]),
        group(
            "au_greenh2",
            "AU Green H2",
            "company",
            [("wind", "wind"), ("electrolyser", "ely")],
            [("wind", "ely", "electricity", 0)],
        ),
        group("australia", "Australia", "country", [("au_ironore", ""), ("au_greenh2", "")]),
        group("qa_blueh2", "Qatar Blue H2", "company", [("smr", "")]),
        group("qatar", "Qatar", "country", [("qa_blueh2", "")]),
        group("kr_power", "Korea Power", "company", [("grid", "grid"), ("wind", "wind")]),
        group(
            "kr_greenh2",
            "Korea Green H2",
            "company",
            [("wind", "wind"), ("electrolyser", "ely")],
            [("wind", "ely", "electricity", 0)],
        ),
        group(
            "kr_mill",
            "Integrated mill",
            "facility",
            [("bf", "bf"), ("bof", "bof")],
            [("bf", "bof", "iron", 0)],
        ),
        group("kr_steel", "Korea Steel", "company", [("kr_mill", "mill")]),
        group("kr_auto", "Korea Automaker", "company", [("assembly", "")]),
        group("kr_ship", "Korea Shipbuilder", "company", [("shipyard", "")]),
        group(
            "korea",
            "Korea",
            "country",
            [
                ("kr_power", ""),
                ("kr_greenh2", ""),
                ("kr_steel", ""),
                ("kr_auto", ""),
                ("kr_ship", ""),
            ],
            [
                ("kr_power", "kr_steel", "electricity", 0),
                ("kr_power", "kr_auto", "electricity", 0),
                ("kr_power", "kr_ship", "electricity", 0),
                ("kr_greenh2", "kr_steel", "hydrogen", 0),
                ("kr_steel", "kr_auto", "steel", 0),
                ("kr_steel", "kr_ship", "steel", 0),
            ],
        ),
        group(
            "green_steel_vc",
            "Green steel value chain",
            "value_chain",
            [("australia", ""), ("qatar", ""), ("korea", "")],
            [
                ("australia", "korea", "iron_ore", 0),
                ("australia", "korea", "hydrogen", 0),
                ("qatar", "korea", "hydrogen", 0),
            ],
        ),
    ],
}


def build_workbook(lib: ComponentLibrary) -> dict:
    """Instantiate the value chain and add the scenario sheets (no solve)."""
    wb = instantiate(lib, "green_steel_vc", instance_id="vc")
    wb["periods"] = [{"year": y, "duration_years": 5} for y in YEARS]
    wb["meta"] = [
        {"key": "title", "value": "Green steel — AU/Qatar→Korea cross-border value chain"},
        {"key": "base_year", "value": 2025},
    ]
    wb["impact_prices"] = [{"impact_id": "CO2", "year": y, "price": CARBON[y]} for y in YEARS]
    wb["transitions"] = [
        {
            "from_technology": "BlastFurnace",
            "to_technology": "H2_DRI",
            "action": "replace",
            "capex_per_capacity": 250,
        },
        {
            "from_technology": "BOF",
            "to_technology": "EAF",
            "action": "replace",
            "capex_per_capacity": 150,
        },
    ]
    wb["demand"] = [
        {"company": "vc/korea/kr_auto", "commodity_id": "car", "year": y, "amount": 1_200_000}
        for y in YEARS
    ] + [
        {"company": "vc/korea/kr_ship", "commodity_id": "ship", "year": y, "amount": 50}
        for y in YEARS
    ]
    # Scrap & HBI are supply-limited imports — capped markets, so deep
    # decarbonisation needs primary green iron (H2-DRI) and the hydrogen chain.
    wb["markets"] = [
        {"market_id": "scrap_import", "target": "scrap", "price": 320, "max_buy": 500_000},
        {"market_id": "hbi_import", "target": "hbi", "price": 420, "max_buy": 300_000},
    ]
    return wb


def _system(wb):
    return run_model(
        wb,
        ScenarioConfig.from_dict(
            {"economics": {"base_year": 2025}, "optimisation_scope": "system"}
        ),
    )


def main() -> None:
    lib = ComponentLibrary.model_validate(LIBRARY)
    (ASSETS / "component_libraries" / "green_steel.json").write_text(
        json.dumps(LIBRARY, indent=2), encoding="utf-8"
    )

    wb = build_workbook(lib)

    # Size the declining CO2 cap from the uncapped (dirty) baseline emissions.
    base = _system(wb)
    assert base["status"] == "optimal", base
    co2c = {
        r["technology_id"]: r["coefficient"]
        for r in wb["io"]
        if r.get("role") == "impact" and r.get("target") == "CO2"
    }
    gross2025 = sum(
        row["value"] * co2c.get(row["technology"], 0.0)
        for row in base["outputs"]["throughput"]
        if row["period"] == 2025
    )
    wb["impact_caps"] = [
        {
            "company": "all",
            "impact_id": "CO2",
            "year": y,
            "limit": round(gross2025 * CAP_FRAC[y]),
            "soft": 1,
            "penalty": 1800,
        }
        for y in YEARS
    ]

    capped = _system(wb)
    assert capped["status"] == "optimal", capped
    vc = run_model(
        wb,
        ScenarioConfig.from_dict(
            {
                "economics": {"base_year": 2025},
                "optimisation_scope": "value_chain",
                "optimisation_mode": "valuechain",
            }
        ),
    )
    assert vc["status"] == "optimal", vc

    (ASSETS / "examples" / "green_steel_chain.sqlite").write_bytes(write_sqlite(wb))
    n_tr = len(capped["outputs"]["transitions"])
    n_ms = len(
        {
            m["measure"]
            for m in capped["outputs"]["measures"]
            if float(m.get("adoption", 0) or 0) > 1e-6
        }
    )
    print(
        f"built green_steel.json + green_steel_chain.sqlite "
        f"({len(wb['nodes'])} nodes, {len(wb['machines'])} machines, "
        f"{n_tr} transition(s) fired, {n_ms} measure instance(s) adopted; "
        f"system & value_chain solves OK)"
    )


if __name__ == "__main__":
    main()
