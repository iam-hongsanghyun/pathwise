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
from _writer import Workbook, verify, write_workbook

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
    is_ore = lambda f: "ore" in f.lower()  # noqa: E731 — iron-ore feedstocks → iron stage

    # Each integrated route splits into iron-making → steel-making, linked by a
    # 1:1 `iron` intermediate. Fuels + iron-ore land on iron-making; scrap/HBI on
    # steel-making — so the route's per-tonne inputs/emissions/costs are preserved
    # exactly, just reorganised into two stages. EAF is scrap-based (single stage).
    stage = {  # route → (iron-making tech | None, steel-making tech)
        "BF-BOF": ("BF", "BOF"),
        "BF-BOF-FX": ("BF-FX", "BOF-FX"),
        "H2-DRI-ESF": ("H2-DRI", "ESF"),
        "EAF": (None, "EAF"),
    }

    # ── commodities + temporal prices ────────────────────────────────────────
    commodities = [
        {"commodity_id": "steel", "kind": "product", "unit": "t"},
        {"commodity_id": "iron", "kind": "material", "unit": "t"},  # intermediate
    ]
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

    # ── 2-stage technologies + per-stage io + cost mapping ───────────────────
    technologies: list[dict[str, object]] = []
    io: list[dict[str, object]] = []
    lifespan = {str(r["technology"]): int(r["lifespan"]) for _, r in tech_df.iterrows()}
    avail = {str(r["technology"]): str(r["availability"]) for _, r in tech_df.iterrows()}
    capex_src: dict[str, str | None] = {}  # new tech → route for capex/renewal (None ⇒ 0)
    opex_src: dict[str, str | None] = {}  # new tech → route for opex

    def add_inputs(tech: str, route: str, kind: str) -> None:
        pairs = (fuel_pairs if kind == "fuel" else feed_pairs)
        col = "fuel" if kind == "fuel" else "feedstock"
        for _, fp in pairs[pairs["technology"] == route].iterrows():
            f = str(fp[col])
            if kind == "feed_ore" and not is_ore(f):
                continue
            if kind == "feed_scrap" and is_ore(f):
                continue
            intensity = fuel_intensity if kind == "fuel" else feed_intensity
            mix = (fuel_mix if kind == "fuel" else feed_mix)[route]
            io.append(
                {
                    "technology_id": tech,
                    "target": f,
                    "role": "input",
                    "coefficient": mix.get(f, 0.0) * intensity.get(f, 0.0),
                    "group": kind,
                    "share_min": float(fp["min"]),
                    "share_max": float(fp["max"]),
                }
            )

    for route, (iron_tech, steel_tech) in stage.items():
        if iron_tech:  # iron-making: fuels + iron-ore → iron
            technologies.append({"technology_id": iron_tech, "lifespan": lifespan[route], "actions": avail[route]})
            add_inputs(iron_tech, route, "fuel")
            add_inputs(iron_tech, route, "feed_ore")
            io.append({"technology_id": iron_tech, "target": "iron", "role": "output", "coefficient": 1.0})
            capex_src[iron_tech] = route  # capital sits in iron-making
            opex_src[iron_tech] = None
            # steel-making: iron + scrap → steel
            technologies.append({"technology_id": steel_tech, "lifespan": lifespan[route], "actions": avail[route]})
            io.append({"technology_id": steel_tech, "target": "iron", "role": "input", "coefficient": 1.0})
            add_inputs(steel_tech, route, "feed_scrap")
            io.append({"technology_id": steel_tech, "target": "steel", "role": "output", "coefficient": 1.0, "is_product": True})
            capex_src[steel_tech] = None
            opex_src[steel_tech] = route  # O&M per tonne steel
        else:  # EAF: electricity + scrap → steel (single stage)
            technologies.append({"technology_id": steel_tech, "lifespan": lifespan[route], "actions": avail[route]})
            add_inputs(steel_tech, route, "fuel")
            add_inputs(steel_tech, route, "feed_scrap")
            io.append({"technology_id": steel_tech, "target": "steel", "role": "output", "coefficient": 1.0, "is_product": True})
            capex_src[steel_tech] = route
            opex_src[steel_tech] = route

    new_techs = [str(t["technology_id"]) for t in technologies]
    capex_rows = [
        {"year": y, **{t: capex.get(capex_src[t] or "", {}).get(y, 0.0) for t in new_techs}} for y in years
    ]
    renew_rows = [
        {"year": y, **{t: renewal.get(capex_src[t] or "", {}).get(y, 0.0) for t in new_techs}} for y in years
    ]
    opex_rows = [
        {"year": y, **{t: opex.get(opex_src[t] or "", {}).get(y, 0.0) for t in new_techs}} for y in years
    ]

    # ── facilities: each plant → iron-making + steel-making facilities ───────
    prod_by = _by_name(production, "system", years)
    processes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    owner_prod: dict[str, dict[int, float]] = {}
    for _, r in baseline.iterrows():
        system = str(r["system"])
        route = str(r["technology"])
        iron_tech, steel_tech = stage[route]
        cap = max(prod_by.get(system, {0: 0.0}).values()) if prod_by.get(system) else 0.0
        owner = "Hyundai Steel" if system.lower().startswith("hyundai") else "POSCO"
        steel_fac = f"{system} · steel"
        if iron_tech:
            iron_fac = f"{system} · iron"
            processes.append({"process_id": iron_fac, "company": owner, "group": "Korea steel",
                              "baseline_technology": iron_tech, "capacity": cap, "introduced_year": int(r["introduced_year"])})
            edges.append({"from_process": iron_fac, "to_process": steel_fac, "commodity_id": "iron"})
        processes.append({"process_id": steel_fac, "company": owner, "group": "Korea steel",
                          "baseline_technology": steel_tech, "capacity": cap, "introduced_year": int(r["introduced_year"])})
        for y in years:
            owner_prod.setdefault(owner, {})[y] = owner_prod.get(owner, {}).get(y, 0.0) + prod_by.get(system, {}).get(y, 0.0)
    demand = [
        {"company": owner, "commodity_id": "steel", "year": y, "amount": amt}
        for owner, by_y in owner_prod.items()
        for y, amt in by_y.items()
    ]

    # ── transitions: decarbonise iron (BF→H2-DRI) and steel (BOF→ESF/EAF) ─────
    def cx(route: str) -> float:
        return capex.get(route, {}).get(years[0], 0.0)

    transitions = [
        {"from_technology": "BF", "to_technology": "H2-DRI", "action": "replace", "capex_per_capacity": cx("H2-DRI-ESF")},
        {"from_technology": "BF-FX", "to_technology": "H2-DRI", "action": "replace", "capex_per_capacity": cx("H2-DRI-ESF")},
        {"from_technology": "BOF", "to_technology": "ESF", "action": "replace", "capex_per_capacity": cx("H2-DRI-ESF") * 0.3},
        {"from_technology": "BOF-FX", "to_technology": "ESF", "action": "replace", "capex_per_capacity": cx("H2-DRI-ESF") * 0.3},
        {"from_technology": "BOF", "to_technology": "EAF", "action": "replace", "capex_per_capacity": cx("EAF")},
        {"from_technology": "BOF-FX", "to_technology": "EAF", "action": "replace", "capex_per_capacity": cx("EAF")},
    ]

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
            {"key": "title", "value": "Steel (Korea, PLANiT MACC) — iron→steel chain"},
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
        "edges": edges,
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
