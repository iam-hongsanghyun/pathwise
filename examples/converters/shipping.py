"""Convert the shipping fleet dataset (Reference.xlsx) into a pathwise workbook.

Per-company model:
    company (clarkson)    → top fleets become facility owners; the rest aggregate
                            into "Other". Each (owner, engine) is a facility whose
                            `company` (demand scope) is unique per engine, and whose
                            `group` is the owning company — so the CO2 target is
                            applied PER COMPANY (group) while each ship-type meets
                            its own activity.
    Main Engine Fuel Type → technology (engine class)
    fuel_spec fuels       → energy streams; emission = well_to_wake; cost = cost·trend
    fuel_pairing + mix     → io blend group "fuel" (bio / LNG / e-fuels) within bounds
    ammonia / hydrogen     → alternative engines (transition targets, transition_rule
                            = True) burning e-ammonia / e-hydrogen — the decarb levers
    emission_scenario     → per-company CO2 target (Tier1), scaled to each company's
                            baseline (soft)

Run:  uv run python examples/converters/shipping.py [SOURCE.xlsx]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _writer import Workbook, verify, write_workbook

DEFAULT_SRC = Path.home() / "Downloads" / "Reference.xlsx"
OUT = Path(__file__).resolve().parents[2] / "frontend/pathwise/public/examples/shipping.xlsx"
ENGINE = "Main Engine Fuel Type"
N_TOP = 8  # top owners modelled individually; the remaining fleet → "Other"
ALT = {"ammonia": "e-ammonia", "hydrogen": "e-hydrogen"}  # alt engine → its fuel


def _years(df: pd.DataFrame) -> list[int]:
    return [int(c) for c in df.columns if isinstance(c, int) or str(c).isdigit()]


def build_workbook(src: Path) -> Workbook:
    xl = pd.ExcelFile(src)
    spec = xl.parse("fuel_spec").set_index("Fuel")
    pairing = xl.parse("fuel_pairing")
    base_mix = xl.parse("baseline_fuelmix")
    fmax = xl.parse("fuel_max")
    fmin = xl.parse("fuel_min")
    cost_trend = xl.parse("fuelcost_trend")
    emis = xl.parse("emission_scenario").set_index("Scenario")
    tcost = xl.parse("transition_cost").set_index(ENGINE)
    clark = xl.parse("clarkson")

    years = _years(fmax)
    rep = years[-1]
    wtw = spec["well_to_wake"].to_dict()
    base_cost = spec["cost"].to_dict()

    # ── fleet → owners (top N + "Other"), counted by (owner, engine) ─────────
    clark = clark.dropna(subset=["Company", ENGINE])
    top = list(clark["Company"].value_counts().head(N_TOP).index)
    clark["owner"] = clark["Company"].where(clark["Company"].isin(top), "Other")
    counts = clark.groupby(["owner", ENGINE]).size()
    base_engines = sorted({e for _o, e in counts.index})
    # Upper group: each company (operator) rolls up to its Group Company
    # (conglomerate) — Group → Company → Facility → Technology.
    grp_of = (
        clark.groupby("owner")["Group Company"]
        .agg(lambda s: s.mode().iat[0] if len(s.mode()) else "—")
        .to_dict()
    )
    grp_of["Other"] = "Other"

    def bounds(engine: str, fuel: str) -> tuple[float, float]:
        mn = fmin[(fmin[ENGINE] == engine) & (fmin["Fuel"] == fuel)]
        mx = fmax[(fmax[ENGINE] == engine) & (fmax["Fuel"] == fuel)]
        lo = float(mn[rep].iloc[0]) if len(mn) else 0.0
        hi = float(mx[rep].iloc[0]) if len(mx) else 1.0
        return lo, hi

    def baseline_share(engine: str, fuel: str) -> float:
        row = base_mix[(base_mix[ENGINE] == engine) & (base_mix["Fuel"] == fuel)]
        return float(row["fuel mix"].iloc[0]) if len(row) else 0.0

    used_fuels: set[str] = set()
    technologies: list[dict[str, object]] = []
    io: list[dict[str, object]] = []

    def conventional_io(engine: str) -> None:
        paired = [str(f) for f in pairing[pairing[ENGINE] == engine]["Fuel"] if str(f) in base_cost]
        for f in paired:
            lo, hi = bounds(engine, f)
            used_fuels.add(f)
            io.append(
                {
                    "technology_id": engine,
                    "target": f,
                    "role": "input",
                    "coefficient": baseline_share(engine, f),  # fuel per ship-yr (mix)
                    "group": "fuel",
                    "share_min": lo,
                    "share_max": hi,
                }
            )
        io.append(
            {
                "technology_id": engine,
                "target": "transport",
                "role": "output",
                "coefficient": 1.0,
                "is_product": True,
            }
        )

    for e in base_engines:
        technologies.append({"technology_id": e, "lifespan": 25, "actions": "continue,replace"})
        conventional_io(e)
    # Alternative-fuel engines: single zero/low-carbon fuel, 1 unit per ship-yr.
    for alt, fuel in ALT.items():
        technologies.append({"technology_id": alt, "lifespan": 25, "actions": "continue,replace"})
        used_fuels.add(fuel)
        io.append({"technology_id": alt, "target": fuel, "role": "input", "coefficient": 1.0})
        io.append(
            {
                "technology_id": alt,
                "target": "transport",
                "role": "output",
                "coefficient": 1.0,
                "is_product": True,
            }
        )

    # Hierarchy: company (owner) → facility (one per engine class it operates) →
    # technology (engine). The owner is the demand + cap scope; each facility is a
    # ship-group whose capacity = its ship count. Owner demand = total ships, so
    # capacities are tight and every ship-group runs (no idle), while the owner
    # may transition any of its facilities to ammonia / hydrogen.
    commodities: list[dict[str, object]] = [
        {"commodity_id": "transport", "kind": "product", "unit": "ship-yr"}
    ]
    processes: list[dict[str, object]] = []
    baseline_emission: dict[str, float] = {}
    owner_ships: dict[str, float] = {}
    for (owner, engine), n in counts.items():
        processes.append(
            {
                "process_id": f"{owner} · {engine}",  # facility (unit)
                "company": owner,  # company / operator (group of facilities)
                "group": grp_of.get(owner, owner),  # upper group (Group Company)
                "baseline_technology": engine,
                "capacity": float(n),
            }
        )
        paired = [str(f) for f in pairing[pairing[ENGINE] == engine]["Fuel"] if str(f) in base_cost]
        e_base = float(n) * sum(baseline_share(engine, f) * float(wtw.get(f, 0.0)) for f in paired)
        baseline_emission[owner] = baseline_emission.get(owner, 0.0) + e_base
        owner_ships[owner] = owner_ships.get(owner, 0.0) + float(n)

    demand = [
        {"company": owner, "commodity_id": "transport", "year": y, "amount": total}
        for owner, total in owner_ships.items()
        for y in years
    ]

    # ── alt-fuel engine transitions (engine → ammonia / hydrogen) ────────────
    transitions = [
        {
            "from_technology": e,
            "to_technology": alt,
            "action": "replace",
            "capex_per_capacity": float(tcost.loc[alt, rep]) if alt in tcost.index else 1000.0,
        }
        for e in base_engines
        for alt in ALT
    ]

    for f in sorted(used_fuels):
        commodities.append({"commodity_id": f, "kind": "energy", "unit": "t"})
    commodity_impacts = [
        {"commodity_id": f, "impact_id": "CO2", "factor": float(wtw.get(f, 0.0))}
        for f in sorted(used_fuels)
    ]

    # ── temporal fuel prices (cost × trend) ──────────────────────────────────
    trend = {str(r["Fuel"]): {y: float(r[y]) for y in years} for _, r in cost_trend.iterrows()}
    price_rows = [
        {"year": y, **{f: base_cost[f] * trend.get(f, {}).get(y, 1.0) for f in sorted(used_fuels)}}
        for y in years
    ]

    # ── per-company (group) CO2 target — Tier1 scaled to each owner's baseline ─
    scen = {y: float(emis.loc["Tier1", y]) for y in years}
    base_idx = scen[years[0]] or 1.0
    pen = 5.0 * max(base_cost.values())
    impact_caps = [
        {
            "company": owner,
            "impact_id": "CO2",
            "year": y,
            "limit": baseline_emission.get(owner, 0.0) * scen[y] / base_idx,
            "soft": True,
            "penalty": pen,
        }
        for owner in sorted(baseline_emission)
        for y in years
    ]

    return {
        "meta": [
            {"key": "title", "value": "Shipping fleet — per-company transition"},
            {"key": "base_year", "value": years[0]},
        ],
        "periods": [{"year": y, "duration_years": 1} for y in years],
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
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    wb = build_workbook(src)
    verify(wb, "shipping")
    write_workbook(wb, OUT)
    print(f"[shipping] wrote {OUT}  ({sum(len(v) for v in wb.values())} rows, {len(wb)} sheets)")


if __name__ == "__main__":
    main()
