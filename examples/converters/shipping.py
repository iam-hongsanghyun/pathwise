"""Convert the shipping fleet dataset (Reference.xlsx) into a pathwise workbook.

Mapping (sector data → generic schema):
    Main Engine Fuel Type → technology (engine class)
    clarkson ships        → aggregated into one fleet facility per engine class
                            (throughput = ship count; each meets its own activity)
    fuel_spec fuels       → energy streams; emission = well_to_wake; cost = cost·trend
    fuel_pairing + mix    → io blend group "fuel"; baseline_fuelmix = baseline share;
                            fuel_max / fuel_min = share bounds (representative year)
    emission_scenario     → fleet CO2 target trajectory (soft), scaled to baseline
    operation_scenario    → activity (kept flat here)

Decarbonisation happens by shifting the fuel blend (bio / LNG / e-fuels) within
share bounds under the tightening emission target — engine transitions are off in
this dataset, so the blend-share lever does the work.

Run:  uv run python examples/converters/shipping.py [SOURCE.xlsx]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _writer import Workbook, verify, write_workbook  # noqa: E402

DEFAULT_SRC = Path.home() / "Downloads" / "Reference.xlsx"
OUT = Path(__file__).resolve().parents[2] / "frontend/pathwise/public/examples/shipping.xlsx"
ENGINE = "Main Engine Fuel Type"


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
    clark = xl.parse("clarkson")

    years = _years(fmax)
    rep = years[-1]  # representative year for (static) share bounds — most permissive

    counts = clark[ENGINE].value_counts().to_dict()
    engines = [e for e in counts if isinstance(e, str)]

    wtw = spec["well_to_wake"].to_dict()
    base_cost = spec["cost"].to_dict()
    fuels_used = sorted({str(f) for f in pairing["Fuel"] if str(f) in base_cost})

    # ── commodities + temporal fuel prices (cost × trend) ────────────────────
    commodities = [{"commodity_id": "transport", "kind": "product", "unit": "ship-yr"}]
    commodities += [{"commodity_id": f, "kind": "energy", "unit": "t"} for f in fuels_used]
    trend = {str(r["Fuel"]): {y: float(r[y]) for y in years} for _, r in cost_trend.iterrows()}
    price_rows = [
        {"year": y, **{f: base_cost[f] * trend.get(f, {}).get(y, 1.0) for f in fuels_used}}
        for y in years
    ]

    # ── impacts (CO2, well-to-wake) ──────────────────────────────────────────
    impacts = [{"impact_id": "CO2", "unit": "tCO2"}]
    commodity_impacts = [
        {"commodity_id": f, "impact_id": "CO2", "factor": float(wtw.get(f, 0.0))}
        for f in fuels_used
    ]

    # ── technologies (engine classes) + io blend group ───────────────────────
    def bounds(engine: str, fuel: str) -> tuple[float, float]:
        mn = fmin[(fmin[ENGINE] == engine) & (fmin["Fuel"] == fuel)]
        mx = fmax[(fmax[ENGINE] == engine) & (fmax["Fuel"] == fuel)]
        lo = float(mn[rep].iloc[0]) if len(mn) else 0.0
        hi = float(mx[rep].iloc[0]) if len(mx) else 1.0
        return lo, hi

    def baseline_share(engine: str, fuel: str) -> float:
        row = base_mix[(base_mix[ENGINE] == engine) & (base_mix["Fuel"] == fuel)]
        return float(row["fuel mix"].iloc[0]) if len(row) else 0.0

    technologies = []
    io: list[dict[str, object]] = []
    for e in engines:
        technologies.append({"technology_id": e, "lifespan": 25, "actions": "continue"})
        paired = [str(f) for f in pairing[pairing[ENGINE] == e]["Fuel"] if str(f) in base_cost]
        for f in paired:
            lo, hi = bounds(e, f)
            io.append(
                {
                    "technology_id": e,
                    "target": f,
                    "role": "input",
                    "coefficient": baseline_share(e, f),  # fuel per ship-yr at baseline
                    "group": "fuel",
                    "share_min": lo,
                    "share_max": hi,
                }
            )
        io.append(
            {
                "technology_id": e,
                "target": "transport",
                "role": "output",
                "coefficient": 1.0,
                "is_product": True,
            }
        )

    # ── fleet facilities (one per engine) + activity demand ──────────────────
    processes = []
    demand = []
    baseline_emission = 0.0
    for e in engines:
        n = float(counts[e])
        processes.append({"process_id": e, "company": e, "baseline_technology": e, "capacity": n})
        for y in years:
            demand.append({"company": e, "commodity_id": "transport", "year": y, "amount": n})
        paired = [str(f) for f in pairing[pairing[ENGINE] == e]["Fuel"] if str(f) in base_cost]
        baseline_emission += n * sum(baseline_share(e, f) * float(wtw.get(f, 0.0)) for f in paired)

    # ── emission target (Tier1 scenario, scaled to baseline; soft) ───────────
    scen = {y: float(emis.loc["Tier1", y]) for y in years}
    base_idx = scen[years[0]] or 1.0
    pen = 5.0 * max(base_cost.values())
    impact_caps = [
        {
            "company": "all",
            "impact_id": "CO2",
            "year": y,
            "limit": baseline_emission * scen[y] / base_idx,
            "soft": True,
            "penalty": pen,
        }
        for y in years
    ]

    return {
        "meta": [
            {"key": "title", "value": "Shipping fleet (engine fuel-mix transition)"},
            {"key": "base_year", "value": years[0]},
        ],
        "periods": [{"year": y, "duration_years": 1} for y in years],
        "commodities": commodities,
        "commodities_t__price": price_rows,
        "impacts": impacts,
        "commodity_impacts": commodity_impacts,
        "technologies": technologies,
        "io": io,
        "processes": processes,
        "demand": demand,
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
