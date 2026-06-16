"""Build the steel example as a framework-native value chain (MILP).

Faithful port of the Korean steel-transition model
(``PLANiT-Institute/systempathway``), built entirely from its vendored input data
(``scripts/sources/steel/model.json``) — 16 facilities, 4 technologies, 14 fuels,
8 feedstocks, the declining CO2 cap (104 Mt → 0).

Structure (the framework's own vocabulary):
- **Technologies** (component recipes): BF-BOF (baseline) + the alternatives
  BF-BOF-FX (CCS, emission-intensity ×0.8), H2-DRI-ESF (hydrogen DRI) and EAF
  (scrap/electric). Each carries its fuel + feedstock inputs (per-tonne
  intensities × representative shares) and its CO2 as ``direct_impact`` =
  ``technology_ei × Σ(share × fuel_intensity × fuel_emission)``.
- **Facilities**: all 16 plants, value-chain nodes; capacity pinned to the
  exogenous production trajectory; baseline technology + install year.
- **Transitions** (technology changes): BF-BOF → {BF-BOF-FX, H2-DRI-ESF, EAF},
  per each technology's ``availability``, gated by **vintage timing** (switch
  only at ``age % lifespan == 0``) and the fleet ``max_count`` caps.
- The declining CO2 cap is a hard ``impact_cap``; the MILP picks least-cost
  transitions to stay under it.

Note: the source additionally optimises the fuel/feedstock *blend shares* within
bounds; here shares are fixed at representative values, so the cost is in the
right structure but not bit-identical to the source's blend optimum. Run:
``uv run python scripts/build_steel.py``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pathwise.api.workbook_io import write_sqlite
from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig
from pathwise.data.components import extract_library_from_workbook

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts" / "sources" / "steel" / "model.json"
ASSETS = ROOT / "src" / "pathwise" / "assets"

#: Representative blend shares per technology (within the source's bounds; sum 1).
FUEL_SHARE = {
    "BF-BOF": {"Coal_BB": 0.87, "BF gas_BB": 0.07, "COG_BB": 0.05, "BOF gas_BB": 0.01},
    "BF-BOF-FX": {"Coal_BX": 0.9, "BF gas_BX": 0.05, "BOF gas_BX": 0.05},
    "H2-DRI-ESF": {"Hydrogen_H2": 0.65, "Electricity_H2": 0.35},
    "EAF": {"Electricity_EAF": 1.0},
}
FEEDSTOCK_SHARE = {
    "BF-BOF": {"Iron ore_BB": 0.9, "Scrap_BB": 0.1},
    "BF-BOF-FX": {"Iron ore_BX": 1.0},
    "H2-DRI-ESF": {"Iron ore_H2": 1.0},
    "EAF": {"Scrap_EAF": 0.5, "HBI_EAF": 0.5},
}
STEEL = "steel"


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_")


def _by_year(rows: list[dict], key: str, years: list[int]) -> dict[str, dict[int, float]]:
    """Long table keyed by ``key`` with year columns → {id: {year: value}}."""
    out: dict[str, dict[int, float]] = {}
    for r in rows:
        out[str(r[key])] = {y: float(r[str(y)]) for y in years if str(y) in r}
    return out


def build_workbook() -> dict[str, list[dict[str, Any]]]:
    d = json.loads(SRC.read_text())
    years = list(range(2025, 2051))
    techs = [r["technology"] for r in d["technology"]]
    life = {r["technology"]: int(r["lifespan"]) for r in d["technology"]}
    avail = {r["technology"]: str(r["availability"]) for r in d["technology"]}
    max_count = {r["technology"]: int(r["max_count"]) for r in d["technology"]}

    capex = _by_year(d["capex"], "technology", years)
    opex = _by_year(d["opex"], "technology", years)
    renewal = _by_year(d["renewal"], "technology", years)
    ei = _by_year(d["technology_ei"], "technology", years)
    fuel_int = _by_year(d["fuel_intensity"], "fuel", years)
    fuel_em = _by_year(d["fuel_emission"], "fuel", years)
    fuel_cost = _by_year(d["fuel_cost"], "fuel", years)
    fs_int = _by_year(d["feedstock_intensity"], "feedstock", years)
    fs_cost = _by_year(d["feedstock_cost"], "feedstock", years)
    cap = {y: float(d["emission"][0][str(y)]) for y in years}
    prod = _by_year(d["production"], "system", years)

    fuels = sorted({f for sh in FUEL_SHARE.values() for f in sh})
    feedstocks = sorted({f for sh in FEEDSTOCK_SHARE.values() for f in sh})

    # ── Streams: fuels + feedstocks (purchasable, real prices) + steel ─────────
    commodities = [{"commodity_id": _safe(f), "kind": "energy", "purchasable": True} for f in fuels]
    commodities += [
        {"commodity_id": _safe(f), "kind": "material", "purchasable": True} for f in feedstocks
    ]
    commodities += [{"commodity_id": STEEL, "kind": "product", "unit": "t"}]
    commodity_prices = [
        {"commodity_id": _safe(f), "year": y, "price": fuel_cost[f][y]}
        for f in fuels
        for y in years
    ] + [
        {"commodity_id": _safe(f), "year": y, "price": fs_cost[f][y]}
        for f in feedstocks
        for y in years
    ]

    # ── Technologies: per-tonne recipe + CO2 (technology_ei × Σ share·int·emit) ─
    technologies, io, io_t, tech_impacts_t = [], [], [], []
    for t in techs:
        acts = ",".join(a.strip() for a in avail[t].split(",")) + ",continue"
        technologies.append(
            {
                "technology_id": _safe(t),
                "lifespan": life[t],
                "actions": acts,
                "capex": capex[t][years[0]],
            }
        )
        for f, share in FUEL_SHARE[t].items():
            for y in years:
                io_t.append(
                    {
                        "technology_id": _safe(t),
                        "target": _safe(f),
                        "role": "input",
                        "year": y,
                        "coefficient": share * fuel_int[f][y],
                    }
                )
        for f, share in FEEDSTOCK_SHARE[t].items():
            for y in years:
                io_t.append(
                    {
                        "technology_id": _safe(t),
                        "target": _safe(f),
                        "role": "input",
                        "year": y,
                        "coefficient": share * fs_int[f][y],
                    }
                )
        io.append(
            {
                "technology_id": _safe(t),
                "target": STEEL,
                "role": "output",
                "coefficient": 1.0,
                "is_product": True,
            }
        )
        for y in years:
            co2 = ei[t][y] * sum(
                sh * fuel_int[f][y] * fuel_em[f][y] for f, sh in FUEL_SHARE[t].items()
            )
            tech_impacts_t.append(
                {"technology_id": _safe(t), "impact_id": "CO2", "year": y, "factor": co2}
            )

    # per-year capex/opex/renewal trajectories (wide temporal sheets)
    tech_capex_t = [{"year": y, **{_safe(t): capex[t][y] for t in techs}} for y in years]
    tech_opex_t = [{"year": y, **{_safe(t): opex[t][y] for t in techs}} for y in years]
    tech_renewal_t = [{"year": y, **{_safe(t): renewal[t][y] for t in techs}} for y in years]

    # ── Transitions: baseline BF-BOF → each alternative (per availability) ──────
    transitions = []
    for t in techs:
        if t == "BF-BOF":
            continue
        transitions.append(
            {
                "from_technology": _safe("BF-BOF"),
                "to_technology": _safe(t),
                "action": "replace" if "replace" in avail[t] else "renew",
                "capex_per_capacity": capex[t][years[0]],
            }
        )

    technology_caps = [{"technology_id": _safe(t), "max_count": max_count[t]} for t in techs]

    # ── Facilities (value chain): 16 plants, capacity pinned to production ──────
    nodes = [
        {
            "node_id": "steel",
            "parent_id": "",
            "kind": "group",
            "level": "sector",
            "label": "Korean steel",
        }
    ]
    machines = []
    for r in d["baseline"]:
        sys = r["system"]
        sid = _safe(sys)
        nodes.append(
            {
                "node_id": sid,
                "parent_id": "steel",
                "kind": "machine",
                "level": "facility",
                "label": sys,
            }
        )
        machines.append(
            {
                "machine_id": sid,
                "baseline_technology": _safe(r["technology"]),
                "capacity": prod[sys][years[0]],
                "introduced_year": int(r["introduced_year"]),
            }
        )
    # wide per-year capacity = production trajectory (pins output per facility)
    proc_cap_t = [
        {"year": y, **{_safe(r["system"]): prod[r["system"]][y] for r in d["baseline"]}}
        for y in years
    ]

    # ── Demand pulls full production; hard declining CO2 cap ───────────────────
    demand = [
        {
            "company": "all",
            "commodity_id": STEEL,
            "year": y,
            "amount": sum(prod[r["system"]][y] for r in d["baseline"]),
        }
        for y in years
    ]
    impact_caps = [
        {"company": "all", "impact_id": "CO2", "year": y, "limit": cap[y], "soft": True}
        for y in years
    ]

    return {
        "meta": [
            {"key": "label", "value": "Steel transition — Korea (systempathway)"},
            {"key": "source", "value": "PLANiT-Institute/systempathway"},
            {"key": "vintage_timing", "value": "true"},
        ],
        "periods": [{"year": y, "duration_years": 1} for y in years],
        "commodities": commodities,
        "commodity_prices": commodity_prices,
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}],
        "technologies": technologies,
        "io": io,
        "io_t": io_t,
        "tech_impacts_t": tech_impacts_t,
        "technologies_t__capex": tech_capex_t,
        "technologies_t__opex": tech_opex_t,
        "technologies_t__renewal": tech_renewal_t,
        "transitions": transitions,
        "technology_caps": technology_caps,
        "nodes": nodes,
        "machines": machines,
        "processes_t__capacity": proc_cap_t,
        "demand": demand,
        "impact_caps": impact_caps,
    }


def main() -> None:
    wb = build_workbook()
    print(
        f"  built: {len(wb['machines'])} facilities, {len(wb['technologies'])} technologies, "
        f"{len(wb['transitions'])} transitions, vintage_timing on"
    )
    # Write the structure first; the solve is a time-boxed sanity check only.
    (ASSETS / "examples" / "steel.sqlite").write_bytes(write_sqlite(wb))
    lib = extract_library_from_workbook(wb, label="Steel transition (KR)")
    (ASSETS / "component_libraries" / "steel.json").write_text(
        json.dumps(lib.model_dump(), indent=2), encoding="utf-8"
    )
    print("  wrote steel.sqlite + component_libraries/steel.json")
    try:
        res = run_model(
            wb,
            ScenarioConfig.from_dict(
                {
                    "economics": {"base_year": 2025, "discount_rate": 0.0},
                    "solver": {"mip_gap": 0.02, "time_limit_s": 120},
                }
            ),
        )
        co2 = {s["period"]: s["total"] for s in res["summary"]["impacts"] if s["impact"] == "CO2"}
        tail = (
            f" | CO2 2025={co2.get(2025, 0) / 1e6:.1f}→2050={co2.get(2050, 0) / 1e6:.1f} Mt"
            if co2
            else ""
        )
        print(f"  sanity solve: status={res['status']} objective={res.get('objective')}{tail}")
    except Exception as exc:
        print(f"  sanity solve skipped: {type(exc).__name__}")


if __name__ == "__main__":
    main()
