"""Build the three repo-derived sector examples (steel, shipping, petrochemical).

Each is regenerated from clean components into two committed assets:
  * ``assets/component_libraries/<sector>.json`` — the reusable component library;
  * ``assets/examples/<sector>.sqlite`` — a runnable node-hierarchy model with the
    baseline technology plus **alternative options** (technology transitions, or
    MACC abatement measures) that a user can solve directly.

Provenance (real datasets, simplified to one representative facility each):
  * steel        — PLANiT-Institute/systempathway (Korean steel transition).
  * shipping     — PLANiT-Institute/shipping_operator (marine fuel transition).
  * petrochemical— PLANiT-Institute/petrochemical_macc_2025 (NCC MACC abatement).

Streams carry physical ``properties`` (temperature, voltage, calorific value, …).
Costs are normalised to clean moderate units (≈ USD) to keep the bare solve
numerically stable; the qualitative structure (a dirty baseline + cleaner, more
expensive alternatives under a rising carbon price) is what the example shows.

Run ``uv run python scripts/build_sector_examples.py`` to regenerate all six
assets; each model is asserted to solve at ``system`` scope and meet demand.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pathwise.api.workbook_io import write_sqlite
from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig
from pathwise.data.components import ComponentLibrary, instantiate

ASSETS = Path(__file__).resolve().parents[1] / "src" / "pathwise" / "assets"
YEARS = [2025, 2030, 2035, 2040, 2045, 2050]


# ── terse builders (shared with the green-steel script's shape) ───────────────
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


def comm(cid, kind, unit, price=None, sale_price=None, properties=None):
    return {
        "commodity_id": cid,
        "kind": kind,
        "unit": unit,
        "price": price,
        "sale_price": sale_price,
        "properties": properties or {},
    }


def tech(tid, lifespan, capex, opex, io, maccs=(), intro=None):
    row: dict[str, Any] = {
        "technology_id": tid,
        "lifespan": lifespan,
        "capex": capex,
        "opex": opex,
        "io": io,
        "maccs": list(maccs),
    }
    if intro is not None:
        row["introduction_year"] = intro
    return row


def meas(mid, label, mtype, target, blocks, lifetime=20):
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


def price_rows(by_commodity: dict[str, dict[int, float]]) -> list[dict]:
    rows = []
    for cid, traj in by_commodity.items():
        for y, v in traj.items():
            rows.append({"commodity_id": cid, "year": y, "price": v})
    return rows


def carbon_rows(carbon: dict[int, float]) -> list[dict]:
    return [{"impact_id": "CO2", "year": y, "price": carbon[y]} for y in YEARS]


# ── 1. STEEL (systempathway) ──────────────────────────────────────────────────
def steel():
    lib = {
        "label": "Steel transition (KR)",
        "commodities": [
            comm("coal", "energy", "GJ", price=7.4, properties={"lhv_MJ_per_kg": 27.0}),
            comm("natural_gas", "energy", "GJ", price=11.7, properties={"lhv_MJ_per_kg": 48.0}),
            comm("electricity", "energy", "GJ", properties={"voltage_kV": 345.0}),
            comm(
                "hydrogen",
                "energy",
                "GJ",
                properties={"lhv_MJ_per_kg": 120.0, "pressure_bar": 30.0},
            ),
            comm("iron_ore", "material", "t", price=103.0, properties={"fe_content_pct": 62.0}),
            comm("scrap", "material", "t", properties={"fe_content_pct": 98.0}),
            comm("steel", "product", "t", sale_price=600.0, properties={"temperature_C": 1650.0}),
        ],
        "technologies": [
            tech(
                "BF_BOF",
                20,
                371,
                185,
                [
                    inp("coal", 18.0),
                    inp("iron_ore", 1.6),
                    inp("electricity", 0.5),
                    out("steel", 1.0, True),
                    co2(2.05),
                ],
                ["bf_abate"],
            ),
            tech(
                "BF_BOF_CCS",
                20,
                460,
                210,
                [
                    inp("coal", 18.0),
                    inp("iron_ore", 1.6),
                    inp("electricity", 0.8),
                    out("steel", 1.0, True),
                    co2(0.6),
                ],
            ),
            tech(
                "H2_DRI_ESF",
                20,
                815,
                407,
                [
                    inp("hydrogen", 16.0),
                    inp("electricity", 16.0),
                    inp("iron_ore", 1.65),
                    out("steel", 1.0, True),
                    co2(0.05),
                ],
                intro=2030,
            ),
            tech(
                "Scrap_EAF",
                20,
                178,
                89,
                [inp("scrap", 1.05), inp("electricity", 6.0), out("steel", 1.0, True), co2(0.05)],
            ),
        ],
        "measures": [
            meas(
                "bf_ccs",
                "Top-gas recovery + CCS",
                "emission_reduction",
                "CO2",
                [blk(0.20, 90.0, 3.0)],
            ),
        ],
        "maccs": [macc("bf_abate", "Blast-furnace abatement", ["bf_ccs"])],
        "machines": [machine("mill", "Integrated steel mill", "BF_BOF", 4_000_000)],
        "groups": [
            group("kr_steel", "Korea Steel", "company", [("mill", "")]),
            group("steel_vc", "Steel value chain", "value_chain", [("kr_steel", "")]),
        ],
    }
    L = ComponentLibrary.model_validate(lib)
    wb = instantiate(L, "steel_vc", instance_id="vc")
    wb["periods"] = [{"year": y, "duration_years": 5} for y in YEARS]
    wb["meta"] = [
        {"key": "title", "value": "Steel transition — Korea (systempathway)"},
        {"key": "base_year", "value": 2025},
    ]
    wb["impact_prices"] = carbon_rows(
        {2025: 48, 2030: 78, 2035: 125, 2040: 201, 2045: 324, 2050: 521}
    )
    # Declining hydrogen price, rising clean-grid electricity price.
    wb["commodity_prices"] = price_rows(
        {
            "hydrogen": {2025: 67.0, 2050: 30.0},
            "electricity": {2025: 35.0, 2038: 51.0},
        }
    )
    # Alternatives: the baseline BF-BOF can switch to CCS retrofit, H2-DRI or scrap-EAF.
    wb["transitions"] = [
        {
            "from_technology": "BF_BOF",
            "to_technology": "BF_BOF_CCS",
            "action": "replace",
            "capex_per_capacity": 200,
        },
        {
            "from_technology": "BF_BOF",
            "to_technology": "H2_DRI_ESF",
            "action": "replace",
            "capex_per_capacity": 815,
        },
        {
            "from_technology": "BF_BOF",
            "to_technology": "Scrap_EAF",
            "action": "replace",
            "capex_per_capacity": 178,
        },
    ]
    wb["demand"] = [
        {"company": "vc/kr_steel", "commodity_id": "steel", "year": y, "amount": 4_000_000}
        for y in YEARS
    ]
    # Scrap is supply-limited (capped import) → deep cuts need primary green iron.
    wb["markets"] = [
        {"market_id": "scrap_import", "target": "scrap", "price": 278, "max_buy": 1_500_000}
    ]
    return lib, wb


# ── 2. SHIPPING (shipping_operator) ───────────────────────────────────────────
def shipping():
    lib = {
        "label": "Marine fuel transition",
        "commodities": [
            comm("ifo380", "energy", "MT", price=500.0, properties={"lhv_MJ_per_kg": 45.0}),
            comm("bio_diesel", "energy", "MT", price=1449.0, properties={"lhv_MJ_per_kg": 37.0}),
            comm(
                "lng",
                "energy",
                "MT",
                price=753.0,
                properties={"lhv_MJ_per_kg": 50.0, "temperature_C": -162.0},
            ),
            comm(
                "e_ammonia",
                "energy",
                "MT",
                price=834.0,
                properties={"lhv_MJ_per_kg": 18.6, "temperature_C": -33.0},
            ),
            comm("voyage", "product", "voyage", sale_price=0.0),
        ],
        "technologies": [
            # One propulsion technology; its fuel is a blend the optimiser mixes
            # within share bounds. ~10,000 MT IFO-equiv energy per voyage-year.
            tech(
                "ShipEngine",
                25,
                0,
                0,
                [
                    inp("ifo380", 1.0, group="marine_fuel", smin=0.0, smax=1.0),
                    inp("bio_diesel", 0.0, group="marine_fuel", smin=0.0, smax=0.3),
                    inp("lng", 0.0, group="marine_fuel", smin=0.0, smax=1.0),
                    inp("e_ammonia", 0.0, group="marine_fuel", smin=0.0, smax=1.0),
                    out("voyage", 1.0, True),
                ],
            ),
        ],
        "measures": [],
        "maccs": [],
        "machines": [machine("ship", "LPG carrier (46k GT)", "ShipEngine", 10_267)],
        "groups": [
            group("fleet", "Shipping fleet", "company", [("ship", "")]),
            group("shipping_vc", "Shipping", "value_chain", [("fleet", "")]),
        ],
    }
    L = ComponentLibrary.model_validate(lib)
    wb = instantiate(L, "shipping_vc", instance_id="vc")
    wb["periods"] = [{"year": y, "duration_years": 5} for y in YEARS]
    wb["meta"] = [
        {"key": "title", "value": "Marine fuel transition (shipping_operator)"},
        {"key": "base_year", "value": 2025},
    ]
    wb["impact_prices"] = carbon_rows(
        {2025: 30, 2030: 60, 2035: 95, 2040: 140, 2045: 195, 2050: 260}
    )
    # Per-MT CO2 emission factors of each fuel (WTW, tCO2/MT).
    wb["commodity_impacts"] = [
        {"commodity_id": "ifo380", "impact_id": "CO2", "factor": 4.122},
        {"commodity_id": "bio_diesel", "impact_id": "CO2", "factor": 0.676},
        {"commodity_id": "lng", "impact_id": "CO2", "factor": 4.18},
        {"commodity_id": "e_ammonia", "impact_id": "CO2", "factor": 0.098},
    ]
    # e-ammonia only available from 2030; max IFO380 share declines over time
    # (the transition lever, via year-varying blend share caps on io_t).
    wb["io_t"] = [
        {
            "technology_id": "ShipEngine",
            "target": "ifo380",
            "role": "input",
            "year": 2025,
            "share_max": 1.0,
        },
        {
            "technology_id": "ShipEngine",
            "target": "ifo380",
            "role": "input",
            "year": 2050,
            "share_max": 0.2,
        },
        {
            "technology_id": "ShipEngine",
            "target": "e_ammonia",
            "role": "input",
            "year": 2025,
            "share_max": 0.0,
        },
        {
            "technology_id": "ShipEngine",
            "target": "e_ammonia",
            "role": "input",
            "year": 2030,
            "share_max": 1.0,
        },
    ]
    wb["demand"] = [
        {"company": "vc/fleet", "commodity_id": "voyage", "year": y, "amount": 10_267}
        for y in YEARS
    ]
    return lib, wb


def _solve(wb):
    return run_model(
        wb,
        ScenarioConfig.from_dict(
            {
                "economics": {"base_year": 2025},
                "optimisation_scope": "system",
                "solver": {"mip_gap": 0.02},
            }
        ),
    )


def main() -> None:
    for sector_id, builder in [
        ("steel", steel),
        ("shipping", shipping),
    ]:
        lib, wb = builder()
        res = _solve(wb)
        assert res["status"] == "optimal", (sector_id, res.get("status"))
        assert not res["outputs"]["demand_slack"], (sector_id, "unmet demand")
        (ASSETS / "component_libraries" / f"{sector_id}.json").write_text(
            json.dumps(lib, indent=2), encoding="utf-8"
        )
        (ASSETS / "examples" / f"{sector_id}.sqlite").write_bytes(write_sqlite(wb))
        n_alt = len(wb.get("transitions", [])) + len(wb.get("measures", []))
        print(
            f"built {sector_id}.json + {sector_id}.sqlite "
            f"({len(wb['machines'])} machine(s), {n_alt} alternative option(s); "
            f"system solve OK, demand met)"
        )


if __name__ == "__main__":
    main()
