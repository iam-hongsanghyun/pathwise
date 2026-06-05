"""Convert the PLANiT petrochemical MACC dataset (CSV bundle) into a workbook.

Mapping (sector data → generic schema):
    facility_database     → aggregated to one facility per (product, process)
    energy_intensities    → baseline technology io inputs (fixed coefficients)
    technology_parameters → abatement technologies as transitions (Naphtha
                            crackers → NCC-H2 / NCC-Electricity)
    emission_factors      → per-fuel CO2 factors (commodity impacts)
    *_price_trajectory    → temporal stream prices (naphtha/LNG/.../H2/electricity)
    demand_growth         → product demand trajectory (capacity × multiplier)
    emission_scenarios    → sector CO2 target (Policy_Target, soft)

Approximations (documented; future refinements): grid emission factor is taken
static at the base year (the engine does not yet support temporal emission
factors); Heat_Pump / RE_PPA levers omitted; abatement capex used as $/t-capacity.

Run:  uv run python examples/converters/petrochemical.py [DATA_DIR]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _writer import Workbook, verify, write_workbook  # noqa: E402

DEFAULT_DIR = Path("/tmp/petro")
OUT = Path(__file__).resolve().parents[2] / "frontend/pathwise/public/examples/petrochemical.xlsx"

# Energy-intensity column → (commodity id, unit, source→unit factor on the
# amount). Electricity is reported in kWh but modelled in MWh (÷1000); other
# energy stays in GJ.
FUELS = {
    "Naphtha_GJ_per_tonne": ("Naphtha", "GJ", 1.0),
    "Electricity_kWh_per_tonne": ("Electricity", "MWh", 1.0e-3),
    "LNG_GJ_per_tonne": ("LNG", "GJ", 1.0),
    "Fuel_Gas_GJ_per_tonne": ("Fuel_Gas", "GJ", 1.0),
    "Byproduct_Gas_GJ_per_tonne": ("Byproduct_Gas", "GJ", 1.0),
    "LPG_GJ_per_tonne": ("LPG", "GJ", 1.0),
    "Fuel_Oil_GJ_per_tonne": ("Fuel_Oil", "GJ", 1.0),
    "Diesel_GJ_per_tonne": ("Diesel", "GJ", 1.0),
}
UNIT = {cid: unit for cid, unit, _f in FUELS.values()} | {"H2": "t", "product": "t"}
PRICE_COL = {
    "Naphtha": "naphtha_usd_per_gj",
    "LNG": "lng_usd_per_gj",
    "Fuel_Gas": "fuel_gas_usd_per_gj",
    "LPG": "lpg_usd_per_gj",
    "Fuel_Oil": "fuel_oil_usd_per_gj",
    "Diesel": "diesel_usd_per_gj",
    "Electricity": "electricity_usd_per_kwh",
}
STEP_YEARS = [2025, 2030, 2035, 2040, 2045, 2050]


def build_workbook(d: Path) -> Workbook:
    fac = pd.read_csv(d / "facility_database.csv")
    ei = pd.read_csv(d / "energy_intensities.csv")
    ef = pd.read_csv(d / "emission_factors.csv").set_index("fuel")
    tp = pd.read_csv(d / "technology_parameters.csv").set_index("technology")
    fuel_price = pd.read_csv(d / "fuel_price_trajectory.csv").set_index("year")
    h2_price = pd.read_csv(d / "h2_price_trajectory.csv").set_index("year")
    grid_ef = pd.read_csv(d / "grid_emission_trajectory.csv").set_index("year")
    demand_mult = pd.read_csv(d / "demand_growth_trajectory.csv").set_index("year")
    scen = pd.read_csv(d / "emission_scenarios_clean.csv")

    years = STEP_YEARS
    base_y = years[0]
    intensity_cols = [c for c in FUELS if c in ei.columns]

    # Aggregate the 248 plants into process archetypes (Naphtha Cracker / BTX
    # Plant / Utility): capacity-weighted mean intensity, summed capacity. Keeps
    # the MILP small enough for an interactive run while preserving the decarb
    # structure (the Naphtha-cracker switch to H2 / electric cracking).
    grp = ei.groupby("process")
    cap = fac.groupby("process")["capacity_kt"].sum()
    mean_int = grp[intensity_cols].mean()

    used_fuels: set[str] = set()
    commodities: list[dict[str, object]] = []
    technologies: list[dict[str, object]] = []
    io: list[dict[str, object]] = []
    processes: list[dict[str, object]] = []
    demand: list[dict[str, object]] = []
    transitions: list[dict[str, object]] = []

    nc_alt = {  # Naphtha-cracker abatement technologies (per the dataset)
        "NCC-H2": {"H2": float(tp.loc["NCC-H2", "h2_ton_per_ton_ethylene"])},  # t H2 / t
        "NCC-Electricity": {  # MWh / t (native unit in the dataset)
            "Electricity": float(tp.loc["NCC-Electricity", "elec_mwh_per_ton_ethylene"])
        },
    }

    # One generic product commodity keeps the commodity dimension small (each
    # facility meets its own demand; the product identity lives in its label).
    for process, row in mean_int.iterrows():
        base_tech = str(process)
        technologies.append(
            {"technology_id": base_tech, "lifespan": 25, "actions": "continue,replace"}
        )
        for col in intensity_cols:
            cid, _unit, fct = FUELS[col]
            coef = float(row[col]) * fct
            if coef <= 0:
                continue
            used_fuels.add(cid)
            io.append(
                {"technology_id": base_tech, "target": cid, "role": "input", "coefficient": coef}
            )
        io.append(
            {
                "technology_id": base_tech,
                "target": "product",
                "role": "output",
                "coefficient": 1.0,
                "is_product": True,
            }
        )

        c = float(cap.get(process, 0.0)) * 1000.0  # kt → t
        processes.append(
            {
                "process_id": base_tech,
                "company": base_tech,
                "baseline_technology": base_tech,
                "capacity": c,
            }
        )
        for y in years:
            mult = (
                float(demand_mult.loc[y, "cumulative_capacity_multiplier"])
                if y in demand_mult.index
                else 1.0
            )
            demand.append(
                {"company": base_tech, "commodity_id": "product", "year": y, "amount": c * mult}
            )

        # Naphtha crackers may switch to H2 or electric cracking.
        if process == "Naphtha Cracker":
            for alt, inputs in nc_alt.items():
                technologies.append(
                    {"technology_id": alt, "lifespan": 25, "actions": "continue,replace"}
                )
                for cid, coef in inputs.items():
                    used_fuels.add(cid)
                    io.append(
                        {"technology_id": alt, "target": cid, "role": "input", "coefficient": coef}
                    )
                io.append(
                    {
                        "technology_id": alt,
                        "target": "product",
                        "role": "output",
                        "coefficient": 1.0,
                        "is_product": True,
                    }
                )
                transitions.append(
                    {
                        "from_technology": base_tech,
                        "to_technology": alt,
                        "action": "replace",
                        "capex_per_capacity": float(tp.loc[alt, "capex_2025_musd_per_mtco2"]),
                    }
                )

    used_fuels.add("H2")
    commodities.append({"commodity_id": "product", "kind": "product", "unit": "t"})
    for cid in sorted(used_fuels):
        commodities.append({"commodity_id": cid, "kind": "energy", "unit": UNIT.get(cid, "GJ")})

    # ── temporal prices ──────────────────────────────────────────────────────
    price_rows = []
    for y in years:
        r: dict[str, object] = {"year": y}
        for cid, col in PRICE_COL.items():
            if y in fuel_price.index:
                v = float(fuel_price.loc[y, col])
                r[cid] = v * 1000.0 if cid == "Electricity" else v  # $/kWh → $/MWh
        if y in h2_price.index:
            r["H2"] = float(h2_price.loc[y, "h2_price_usd_per_kg"]) * 1000.0  # $/kg → $/t
        price_rows.append(r)

    # ── emission factors (static; grid taken at base year — see module note) ──
    grid_mwh = (
        float(grid_ef.loc[base_y, "grid_ef_tco2_per_mwh"]) if base_y in grid_ef.index else 0.0
    )
    commodity_impacts = []
    for cid in sorted(used_fuels):
        if cid == "Electricity":
            factor = grid_mwh  # tCO2 / MWh (native unit)
        elif cid in ef.index and pd.notna(ef.loc[cid, "tCO2_per_GJ"]):
            factor = float(ef.loc[cid, "tCO2_per_GJ"])
        else:
            factor = 0.0
        commodity_impacts.append({"commodity_id": cid, "impact_id": "CO2", "factor": factor})

    # ── emission target (Policy_Target, soft; Mt → t, interpolated to steps) ──
    path = scen[scen["scenario_name"] == "Policy_Target"].set_index("year")["target_mt"]
    impact_caps = []
    for y in years:
        if y in path.index:
            limit = float(path.loc[y]) * 1.0e6
        else:
            limit = float(path.reindex(range(path.index.min(), y + 1)).interpolate().loc[y]) * 1.0e6
        impact_caps.append(
            {
                "company": "all",
                "impact_id": "CO2",
                "year": y,
                "limit": limit,
                "soft": True,
                "penalty": 1.0e3,
            }
        )

    return {
        "meta": [
            {"key": "title", "value": "Petrochemicals (Korea, PLANiT MACC)"},
            {"key": "base_year", "value": base_y},
        ],
        "periods": [{"year": y, "duration_years": 5} for y in years],
        "commodities": commodities,
        "commodities_t__price": price_rows,
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}],
        "commodity_impacts": commodity_impacts,
        "technologies": technologies,
        "io": io,
        "processes": processes,
        "demand": demand,
        "transitions": transitions,
        "impact_caps": impact_caps,
    }


def main() -> None:
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    wb = build_workbook(d)
    verify(wb, "petrochemical")
    write_workbook(wb, OUT)
    print(
        f"[petrochemical] wrote {OUT}  ({sum(len(v) for v in wb.values())} rows, {len(wb)} sheets)"
    )


if __name__ == "__main__":
    main()
