"""Convert a legacy shipping workbook (``Reference.xlsx``) to the generic schema.

The legacy model stored its data across ~18 bespoke sheets (``clarkson``,
``fuel_spec``, ``emission_scenario``, …). This one-off converter reshapes them
into the canonical generic workbook that :func:`pathwise.data.assemble.assemble_problem`
consumes, so the new engine can run on existing data.

It is idempotent and never mutates the source. Run::

    uv run python tools/migrate_shipping_to_generic.py data/Reference.xlsx data/fleet.xlsx

Coverage (v1): assets (existing ships with computed baseline energy),
technologies, carriers (price in USD/MJ + cost trajectory), engine↔fuel
compatibility, baseline mix, transitions, and per-operator intensity targets.
Not yet mapped (documented TODOs): orderbook deliveries, fuel blend min/max,
carrier/class limits, operation-scenario activity multipliers, efficiency
trajectories, MACC measures, and new-build options (the last two are net-new
data the legacy workbook does not contain).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from pathwise.data.workbook import Workbook, write_workbook
from pathwise.logger import get_logger

logger = get_logger(__name__)

G_PER_TONNE = 1.0e6


def _years(df: pd.DataFrame) -> list[int]:
    return [int(c) for c in df.columns if isinstance(c, int)]


def _baseline_energy_mj(
    engine: str,
    ttw_tonnes: float,
    baseline_mix: pd.DataFrame,
    ttw_intensity: dict[str, float],
) -> float:
    """Baseline annual energy [MJ] from a ship's TtW emissions and fuel mix.

    energy = Σ_f (ttw_tonnes·share_f·1e6) / intensity_ttw_f   [gCO2e / (gCO2e/MJ)].
    """
    mix = baseline_mix[baseline_mix["Main Engine Fuel Type"] == engine]
    total = 0.0
    for _, row in mix.iterrows():
        fuel = row["Fuel"]
        share = row["fuel mix"]
        intensity = ttw_intensity.get(fuel, 0.0)
        if intensity > 0 and share > 0 and not pd.isna(ttw_tonnes):
            total += (ttw_tonnes * share * G_PER_TONNE) / intensity
    return total


def migrate(reference_path: str | Path) -> Workbook:
    """Read a legacy shipping workbook and return a generic workbook."""
    frames = pd.read_excel(reference_path, sheet_name=None, engine="openpyxl")
    clarkson = frames["clarkson"]
    fuel_spec = frames["fuel_spec"]
    fuel_pairing = frames["fuel_pairing"]
    baseline_fuelmix = frames["baseline_fuelmix"]
    transition_rule = frames["transition_rule"]
    transition_cost = frames["transition_cost"]
    fuelcost_trend = frames["fuelcost_trend"]
    emission_scenario = frames["emission_scenario"]

    years = _years(fuelcost_trend)
    base_year = years[0]

    ttw_intensity = {r["Fuel"]: float(r["tank_to_wake"]) for _, r in fuel_spec.iterrows()}

    wb: Workbook = {}

    # periods
    wb["periods"] = [{"year": int(y), "duration_years": 1, "activity_multiplier": 1} for y in years]
    wb["meta"] = [
        {"key": "schema_version", "value": "1.0"},
        {"key": "domain", "value": "shipping"},
        {"key": "base_period", "value": int(base_year)},
    ]

    # carriers + cost trajectory (USD/MJ = cost/LCV; trajectory = fuelcost multiplier)
    carriers = []
    carrier_cost = []
    trend_by_fuel = {r["Fuel"]: r for _, r in fuelcost_trend.iterrows()}
    for _, r in fuel_spec.iterrows():
        fuel = r["Fuel"]
        lcv = float(r["LCV"]) if not pd.isna(r["LCV"]) and float(r["LCV"]) != 0 else 1.0
        base_cost_per_mj = float(r["cost"]) / lcv if not pd.isna(r["cost"]) else 0.0
        carriers.append(
            {
                "carrier_id": fuel,
                "intensity": float(r["well_to_wake"]) if not pd.isna(r["well_to_wake"]) else 0.0,
                "cost": base_cost_per_mj,
                "class": r.get("Class"),
            }
        )
        if fuel in trend_by_fuel:
            for y in years:
                mult = trend_by_fuel[fuel][y]
                if not pd.isna(mult):
                    carrier_cost.append(
                        {"carrier_id": fuel, "year": int(y), "multiplier": float(mult)}
                    )
    wb["carriers"] = carriers
    if carrier_cost:
        wb["carrier_cost"] = carrier_cost

    # technologies (engines) + transition flag
    can_transition = {
        str(r["Main Engine Fuel Type"]): bool(r["Transition"])
        for _, r in transition_rule.iterrows()
    }
    engines = sorted(set(baseline_fuelmix["Main Engine Fuel Type"]) | set(can_transition))
    wb["technologies"] = [{"technology_id": e, "specific_energy": 1.0} for e in engines]

    # compatibility + baseline mix
    wb["carrier_compatibility"] = [
        {"technology_id": r["Main Engine Fuel Type"], "carrier_id": r["Fuel"]}
        for _, r in fuel_pairing.iterrows()
    ]
    wb["baseline_mix"] = [
        {
            "technology_id": r["Main Engine Fuel Type"],
            "carrier_id": r["Fuel"],
            "share": float(r["fuel mix"]),
        }
        for _, r in baseline_fuelmix.iterrows()
        if not pd.isna(r["fuel mix"])
    ]

    # transitions: any baseline engine → any transition-allowed engine
    tcost_by_engine = {str(r["Main Engine Fuel Type"]): r for _, r in transition_cost.iterrows()}
    targets_engines = [e for e, ok in can_transition.items() if ok]
    transitions = []
    for to_eng in targets_engines:
        capex = 0.0
        if to_eng in tcost_by_engine and base_year in tcost_by_engine[to_eng]:
            v = tcost_by_engine[to_eng][base_year]
            capex = float(v) if not pd.isna(v) else 0.0
        for from_eng in engines:
            if from_eng != to_eng:
                transitions.append(
                    {
                        "from_technology_id": from_eng,
                        "to_technology_id": to_eng,
                        "capex_per_size": capex,
                        "lifetime": 20,
                    }
                )
    wb["transitions"] = transitions

    # assets (existing ships with computed baseline energy)
    assets = []
    dropped = 0
    seen_ids: dict[str, int] = {}
    for _, ship in clarkson.iterrows():
        engine = str(ship["Main Engine Fuel Type"]).strip()
        ttw = ship["tank_to_wake"]
        energy = _baseline_energy_mj(engine, ttw, baseline_fuelmix, ttw_intensity)
        gt = ship["GT"]
        if energy <= 0 or pd.isna(gt) or engine not in engines:
            dropped += 1
            continue
        built = ship["Built"]
        # Ship names are not unique in the source — disambiguate.
        name = str(ship["Name"])
        seen_ids[name] = seen_ids.get(name, 0) + 1
        asset_id = name if seen_ids[name] == 1 else f"{name} #{seen_ids[name]}"
        assets.append(
            {
                "asset_id": asset_id,
                "group": str(ship["Operator"]),
                "capacity": energy,
                "size": float(gt),
                "technology_id": engine,
                "built_year": int(built) if not pd.isna(built) else None,
                "activity": energy,
            }
        )
    wb["assets"] = assets

    # targets: per operator, per scenario, intensity cap (gCO2e/MJ)
    operators = sorted({str(a["group"]) for a in assets})
    targets = []
    for _, row in emission_scenario.iterrows():
        scenario = str(row["Scenario"])
        for op in operators:
            for y in years:
                limit = row[y]
                if not pd.isna(limit):
                    targets.append(
                        {
                            "target_set": scenario,
                            "group": op,
                            "target_type": "intensity_cap",
                            "year": int(y),
                            "limit": float(limit),
                        }
                    )
    wb["targets"] = targets

    logger.info(
        "migrated %d ships (%d dropped), %d engines, %d carriers, %d transitions, %d operators",
        len(assets),
        dropped,
        len(engines),
        len(carriers),
        len(transitions),
        len(operators),
    )
    return wb


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: migrate_shipping_to_generic.py <reference.xlsx> <out.xlsx>", file=sys.stderr)
        return 2
    wb = migrate(argv[1])
    write_workbook(wb, argv[2])
    print(f"wrote generic workbook: {argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
