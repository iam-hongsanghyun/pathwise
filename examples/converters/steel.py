"""Convert the PLANiT global steel MACC dataset into a pathwise workbook.

Mapping (sector data → generic schema):
    system          → facility (its own company; meets its own production)
    technology      → technology (one active per facility; transitions per
                      `availability`); capex/opex/renewal temporal
    fuel            → energy stream; amount = share·fuel_intensity [GJ/t];
                      emission = ·fuel_emission [tCO2/GJ]; cost = fuel_cost [/GJ]
    feedstock       → material stream; amount = share·feedstock_intensity [t/t];
                      emission = ·feedstock_emission [tCO2/t]; cost = feedstock_cost
    fuel/feedstock  → io blend groups "fuel" / "feedstock" with min/max shares
    production      → demand trajectory per facility
    emission        → global CO2 cap (soft target)
    carbonprice     → CO2 impact price

Run:  uv run python examples/converters/steel.py [SOURCE.xlsx]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _writer import Workbook, verify, write_workbook  # noqa: E402

DEFAULT_SRC = Path.home() / "Downloads" / "Steel Data Mar 10 Global.xlsx"
OUT = Path(__file__).resolve().parents[2] / "frontend/pathwise/public/examples/steel.xlsx"


def _years(df: pd.DataFrame) -> list[int]:
    return [int(c) for c in df.columns if isinstance(c, int) or str(c).isdigit()]


def _by_name(df: pd.DataFrame, key: str, years: list[int]) -> dict[str, dict[int, float]]:
    """Wide temporal sheet (key column + year columns) → {name: {year: value}}."""
    out: dict[str, dict[int, float]] = {}
    for _, row in df.iterrows():
        name = str(row[key])
        out[name] = {y: float(row[y]) for y in years if pd.notna(row.get(y))}
    return out


def _split(cell: object) -> list[str]:
    return [s.strip() for s in str(cell).split(",")] if pd.notna(cell) else []


def build_workbook(src: Path) -> Workbook:
    xl = pd.ExcelFile(src)
    fuel_int = xl.parse("fuel_intensity")
    feed_int = xl.parse("feedstock_intensity")
    all_years = _years(fuel_int)
    # Solve at 5-year resolution (standard MACC practice) — annual resolution
    # over a 16-facility fleet is an intractably large MILP for an interactive run.
    step = 5
    years = [y for y in all_years if (y - all_years[0]) % step == 0]
    if all_years[-1] not in years:
        years.append(all_years[-1])

    fuel_intensity = {k: v[years[0]] for k, v in _by_name(fuel_int, "fuel", years).items()}
    feed_intensity = {k: v[years[0]] for k, v in _by_name(feed_int, "feedstock", years).items()}
    fuel_emission = {
        k: v[years[0]] for k, v in _by_name(xl.parse("fuel_emission"), "fuel", years).items()
    }
    feed_emission = {
        k: v[years[0]]
        for k, v in _by_name(xl.parse("feedstock_emission"), "feedstock", years).items()
    }
    fuel_cost = _by_name(xl.parse("fuel_cost"), "fuel", years)
    feed_cost = _by_name(xl.parse("feedstock_cost"), "feedstock", years)
    capex = _by_name(xl.parse("capex"), "technology", years)
    opex = _by_name(xl.parse("opex"), "technology", years)
    renewal = _by_name(xl.parse("renewal"), "technology", years)
    carbonprice = _by_name(xl.parse("carbonprice"), "emission", years)["global"]
    emission_cap = _by_name(xl.parse("emission"), "emission", years)["global"]

    fuel_pairs = xl.parse("technology_fuel_pairs")
    feed_pairs = xl.parse("technology_feedstock_pairs")
    tech_df = xl.parse("technology")
    baseline = xl.parse("baseline")
    production = xl.parse("production")

    techs = list(tech_df["technology"])

    # Baseline mix per technology from the fleet; synthesise from pair midpoints
    # for technologies absent from the baseline (e.g. H2-DRI-ESF).
    def fleet_mix(
        group_pairs: pd.DataFrame, share_col: str, name_col: str
    ) -> dict[str, dict[str, float]]:
        mix: dict[str, dict[str, float]] = {}
        for _, r in baseline.iterrows():
            names = _split(r[name_col])
            shares = [float(x) for x in _split(r[share_col])]
            mix[str(r["technology"])] = dict(zip(names, shares, strict=False))
        for t in techs:
            if t in mix:
                continue
            rows = group_pairs[group_pairs["technology"] == t]
            mids = {
                str(r[group_pairs.columns[1]]): (float(r["min"]) + float(r["max"])) / 2
                for _, r in rows.iterrows()
            }
            tot = sum(mids.values()) or 1.0
            mix[t] = {k: v / tot for k, v in mids.items()}
        return mix

    fuel_mix = fleet_mix(fuel_pairs, "fuel_share", "fuel")
    feed_mix = fleet_mix(feed_pairs, "feedstock_share", "feedstock")

    fuels = sorted(set(fuel_pairs["fuel"]))
    feeds = sorted(set(feed_pairs["feedstock"]))

    # ── commodities + temporal prices ────────────────────────────────────────
    commodities = [{"commodity_id": "steel", "kind": "product", "unit": "t"}]
    commodities += [{"commodity_id": f, "kind": "energy", "unit": "GJ"} for f in fuels]
    commodities += [{"commodity_id": f, "kind": "material", "unit": "t"} for f in feeds]
    price_rows = []
    for y in years:
        row: dict[str, object] = {"year": y}
        for f in fuels:
            row[f] = fuel_cost.get(f, {}).get(y, 0.0)
        for f in feeds:
            row[f] = feed_cost.get(f, {}).get(y, 0.0)
        price_rows.append(row)

    # ── impacts (CO2 + carbon price trajectory) ──────────────────────────────
    impacts = [{"impact_id": "CO2", "unit": "tCO2"}]
    impacts_price = [{"year": y, "CO2": carbonprice.get(y, 0.0)} for y in years]
    commodity_impacts = [
        {"commodity_id": f, "impact_id": "CO2", "factor": fuel_emission.get(f, 0.0)} for f in fuels
    ] + [
        {"commodity_id": f, "impact_id": "CO2", "factor": feed_emission.get(f, 0.0)} for f in feeds
    ]

    # ── technologies + temporal costs + io blend groups ──────────────────────
    technologies = []
    capex_rows = [{"year": y, **{t: capex.get(t, {}).get(y, 0.0) for t in techs}} for y in years]
    opex_rows = [{"year": y, **{t: opex.get(t, {}).get(y, 0.0) for t in techs}} for y in years]
    renew_rows = [{"year": y, **{t: renewal.get(t, {}).get(y, 0.0) for t in techs}} for y in years]
    io: list[dict[str, object]] = []
    for _, tr in tech_df.iterrows():
        t = str(tr["technology"])
        technologies.append(
            {
                "technology_id": t,
                "lifespan": int(tr["lifespan"]),
                "actions": str(tr["availability"]),
            }
        )
        for _, fp in fuel_pairs[fuel_pairs["technology"] == t].iterrows():
            f = str(fp["fuel"])
            coef = fuel_mix[t].get(f, 0.0) * fuel_intensity.get(f, 0.0)
            io.append(
                {
                    "technology_id": t,
                    "target": f,
                    "role": "input",
                    "coefficient": coef,
                    "group": "fuel",
                    "share_min": float(fp["min"]),
                    "share_max": float(fp["max"]),
                }
            )
        for _, fp in feed_pairs[feed_pairs["technology"] == t].iterrows():
            f = str(fp["feedstock"])
            coef = feed_mix[t].get(f, 0.0) * feed_intensity.get(f, 0.0)
            io.append(
                {
                    "technology_id": t,
                    "target": f,
                    "role": "input",
                    "coefficient": coef,
                    "group": "feedstock",
                    "share_min": float(fp["min"]),
                    "share_max": float(fp["max"]),
                }
            )
        io.append(
            {
                "technology_id": t,
                "target": "steel",
                "role": "output",
                "coefficient": 1.0,
                "is_product": True,
            }
        )

    # ── facilities (one per system, own company) + demand ────────────────────
    prod_by = _by_name(production, "system", years)
    processes = []
    demand = []
    for _, r in baseline.iterrows():
        system = str(r["system"])
        cap = max(prod_by.get(system, {0: 0.0}).values()) if prod_by.get(system) else 0.0
        # Owner group (for per-company emission caps): Pohang/Gwangyang → POSCO,
        # Hyundai plants → Hyundai Steel; each plant is still its own demand scope.
        owner = "Hyundai Steel" if system.lower().startswith("hyundai") else "POSCO"
        processes.append(
            {
                "process_id": system,
                "company": system,
                "group": owner,
                "baseline_technology": str(r["technology"]),
                "capacity": cap,
                "introduced_year": int(r["introduced_year"]),
            }
        )
        for y in years:
            demand.append(
                {
                    "company": system,
                    "commodity_id": "steel",
                    "year": y,
                    "amount": prod_by.get(system, {}).get(y, 0.0),
                }
            )

    # ── transitions: each baseline tech may switch to any other technology ────
    baseline_techs = sorted(set(baseline["technology"]))
    transitions = []
    for frm in baseline_techs:
        for to in techs:
            if to == frm:
                continue
            transitions.append(
                {
                    "from_technology": frm,
                    "to_technology": to,
                    "action": "replace",
                    "capex_per_capacity": capex.get(to, {}).get(years[0], 0.0),
                }
            )

    # ── global emission cap (soft target) ────────────────────────────────────
    pen = 3.0 * max(carbonprice.values())
    impact_caps = [
        {
            "company": "all",
            "impact_id": "CO2",
            "year": y,
            "limit": emission_cap.get(y, 0.0),
            "soft": True,
            "penalty": pen,
        }
        for y in years
    ]

    return {
        "meta": [
            {"key": "title", "value": "Steel (Korea, PLANiT MACC)"},
            {"key": "base_year", "value": years[0]},
        ],
        "periods": [{"year": y, "duration_years": step} for y in years],
        "commodities": commodities,
        "commodities_t__price": price_rows,
        "impacts": impacts,
        "impacts_t__price": impacts_price,
        "commodity_impacts": commodity_impacts,
        "technologies": technologies,
        "technologies_t__capex": capex_rows,
        "technologies_t__opex": opex_rows,
        "technologies_t__renewal": renew_rows,
        "io": io,
        "processes": processes,
        "demand": demand,
        "transitions": transitions,
        "impact_caps": impact_caps,
    }


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    wb = build_workbook(src)
    verify(wb, "steel")
    write_workbook(wb, OUT)
    print(f"[steel] wrote {OUT}  ({sum(len(v) for v in wb.values())} rows across {len(wb)} sheets)")


if __name__ == "__main__":
    main()
