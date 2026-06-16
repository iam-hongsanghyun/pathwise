"""Build the petrochemical example as a framework-native value chain.

An exact port of the Korean Petrochemical MACC model
(``PLANiT-Institute/petrochemical_macc_2025``), default-demand scenario, expressed
in pathwise's own vocabulary — NOT a bolt-on schema:

* **Technologies** (Naphtha Cracker / BTX Plant / Utility) live in the component
  library (recipes).
* **Facilities** — all 248 real plants from ``facility_database.csv`` — are nodes
  in the **value chain**, grouped by their 60 companies. Each carries its real
  per-year baseline CO2 via a per-facility ``process_impacts_t`` intensity
  (fossil scales with demand growth, electricity also with the greening grid).
* The abatement options (renewable PPA, heat pump, electric cracker) are
  **measures** (abatement without a technology change — the framework's MACC),
  deployed onto facility subsets via ``maccs`` + ``macc_links``.
* The net-zero-by-2050 path is a CO2 ``impact_cap``.

The ``macc`` backend (greedy abatement) then reproduces the source's per-year
deployment EXACTLY. The exactness comes from calibrating each measure so the
backend re-derives the source curve from framework primitives:

    reduction(y) = P_src(y) / Σ_subset emission(y)      # ⇒ potential = P_src(y)
    block.capex(y) = capex_ann(y)·20 · P_src(y) / N     # ⇒ $/tCO2 = total_cost,
    block.opex(y)  = (total_cost(y) − capex_ann(y))·P_src(y) / N    CAPEX = source

with measure lifetime 20 (the 20-yr multiplier Module 3 hardcodes), N = subset
size. Module 1+2 outputs were captured once and vendored as
``scripts/sources/petrochemical/model.json``; the run is asserted against
``tests/data/refs/petrochemical_deployment.csv`` before the example is written.

Run: ``uv run python scripts/build_petrochemical.py``
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from pathwise.api.workbook_io import write_sqlite
from pathwise.backends.macc_backend import MaccBackend
from pathwise.data.components import extract_library_from_workbook

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts" / "sources" / "petrochemical" / "model.json"
ASSETS = ROOT / "src" / "pathwise" / "assets"
REF = ROOT / "tests" / "data" / "refs" / "petrochemical_deployment.csv"

# process type → technology id → its product stream.
TECH = {"Naphtha Cracker": "Naphtha_Cracker", "BTX Plant": "BTX_Plant", "Utility": "Utility"}
PRODUCT = {"Naphtha_Cracker": "ethylene", "BTX_Plant": "aromatics", "Utility": "utility_heat"}
# Which technologies each abatement measure applies to (the source's option scope).
SUBSET = {
    "Heat_Pump": {"BTX_Plant", "Utility"},  # non-NCC heat
    "NCC-Electricity": {"Naphtha_Cracker"},  # the cracker
    "RE_PPA": {"Naphtha_Cracker", "BTX_Plant", "Utility"},  # all electricity
}
MEASURE_ID = {"Heat_Pump": "Heat_Pump", "NCC-Electricity": "NCC_Electricity", "RE_PPA": "RE_PPA"}
MEASURE_LABEL = {
    "Heat_Pump": "Industrial heat pump (electrify low-temp heat)",
    "NCC-Electricity": "Electric naphtha cracker (renewable)",
    "RE_PPA": "Renewable PPA (grid → renewable electricity)",
}
LIFETIME = 20


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_")


def _model() -> dict[str, Any]:
    return json.loads(SRC.read_text())


def _emission(fac: dict, y: int, m: dict, gef: dict, gef0: float) -> float:
    """A facility's CO2 emission in MtCO2 for year ``y`` (fossil + greening grid)."""
    return (fac["fossil_kt"] * m[y] + fac["elec_kt"] * m[y] * gef[y] / gef0) / 1000.0


def build_workbook() -> dict[str, list[dict[str, Any]]]:
    """Assemble the 248-facility petrochemical value chain from the vendored model."""
    d = _model()
    years = d["years"]
    m = {int(k): v for k, v in d["m"].items()}
    gef = {int(k): v for k, v in d["grid_ef"].items()}
    gef0 = d["grid_ef_2025"]
    facs = d["facilities"]
    target = {int(k): v for k, v in d["target"].items()}
    macc = {opt: {int(k): v for k, v in by_year.items()} for opt, by_year in d["macc"].items()}

    streams = sorted(set(PRODUCT.values()))
    commodities = [{"commodity_id": s, "kind": "product", "unit": "kt"} for s in streams]
    technologies = [{"technology_id": t, "actions": "continue"} for t in PRODUCT]
    io = [
        {"technology_id": t, "target": p, "role": "output", "coefficient": 1.0, "is_product": True}
        for t, p in PRODUCT.items()
    ]

    # ── Value-chain hierarchy: sector → companies → facility machines ──────────
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
    process_impacts_t = []
    for f in facs:
        tech = TECH[f["process"]]
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
            {"machine_id": f["id"], "baseline_technology": tech, "capacity": f["capacity_kt"]}
        )
        cap = f["capacity_kt"] or 1.0
        for y in years:
            # per-throughput CO2 intensity: capacity × factor = the facility's MtCO2.
            process_impacts_t.append(
                {
                    "process_id": f["id"],
                    "impact_id": "CO2",
                    "year": y,
                    "factor": _emission(f, y, m, gef, gef0) / cap,
                }
            )

    # ── Measures (the MACC) + per-year calibrated cost curve ───────────────────
    measures, maccs, macc_links, measure_blocks, measure_blocks_t = [], [], [], [], []
    for opt, mid in MEASURE_ID.items():
        subset = [f for f in facs if TECH[f["process"]] in SUBSET[opt]]
        n = len(subset)
        measures.append(
            {"measure_id": mid, "type": "emission_reduction", "target": "CO2", "lifetime": LIFETIME}
        )
        maccs.append({"macc": mid, "measure_id": mid})
        for tech in sorted(SUBSET[opt]):
            macc_links.append({"macc": mid, "technology": tech})
        measure_blocks.append(
            {"measure_id": mid, "block": 0, "reduction": 0.0, "capex": 0.0, "opex": 0.0}
        )
        for y in years:
            cell = macc[opt].get(y)
            if cell is None:  # option not yet available (e.g. NCC < 2030)
                row = {"reduction": 0.0, "capex": 0.0, "opex": 0.0}
            else:
                p_src = cell["potential"]
                sigma = sum(_emission(f, y, m, gef, gef0) for f in subset)
                book = cell["capex_ann"] * LIFETIME
                row = {
                    "reduction": p_src / sigma if sigma > 0 else 0.0,
                    "capex": book * p_src / n if n else 0.0,
                    "opex": (cell["total_cost"] - cell["capex_ann"]) * p_src / n if n else 0.0,
                }
            measure_blocks_t.append({"measure_id": mid, "block": 0, "year": y, **row})

    impact_caps = [
        {"company": "all", "impact_id": "CO2", "year": y, "limit": target[y]} for y in years
    ]
    demand = [{"company": "all", "commodity_id": "ethylene", "year": years[0], "amount": 0.0}]

    return {
        "meta": [
            {"key": "label", "value": "Petrochemical MACC — ethylene NCC (exact port)"},
            {"key": "backend", "value": "macc"},
            {"key": "source", "value": "PLANiT-Institute/petrochemical_macc_2025"},
        ],
        "periods": [{"year": y, "duration_years": 1} for y in years],
        "commodities": commodities,
        "impacts": [{"impact_id": "CO2", "unit": "MtCO2"}],
        "technologies": technologies,
        "io": io,
        "nodes": nodes,
        "machines": machines,
        "process_impacts_t": process_impacts_t,
        "measures": measures,
        "maccs": maccs,
        "macc_links": macc_links,
        "measure_blocks": measure_blocks,
        "measure_blocks_t": measure_blocks_t,
        "impact_caps": impact_caps,
        "demand": demand,
    }


def validate(wb: dict[str, list[dict[str, Any]]]) -> None:
    """Run the macc backend and assert it reproduces the source deployment."""
    res = MaccBackend().run(wb, {"economics": {"base_year": 2025}}, {"domain": "process"})
    assert res["status"] == "optimal", res.get("validation")
    by_year = {r["year"]: r for r in res["outputs"]["macc"]["by_year"]}
    with REF.open(newline="") as fh:
        ref = list(csv.DictReader(fh))
    worst_e = worst_c = 0.0
    for r in ref:
        y = int(r["year"])
        got = by_year[y]
        worst_e = max(worst_e, abs(got["actual_emissions"] - float(r["actual_emissions_mt"])))
        worst_c = max(worst_c, abs(got["cumulative_capex"] - float(r["cumulative_capex_musd"])))
    end = by_year[2050]
    assert worst_e < 1e-6, f"emissions diverge by {worst_e}"
    assert worst_c < 1e-3, f"cumulative CAPEX diverges by {worst_c}"
    print(
        f"  validated vs source: {len(ref)} years, max Δemiss={worst_e:.2e} Mt, "
        f"max Δcapex={worst_c:.2e} MUSD"
    )
    print(
        f"  2050: actual_emissions={end['actual_emissions']:.6f} Mt, "
        f"cumulative_capex={end['cumulative_capex']:.3f} MUSD"
    )


def main() -> None:
    wb = build_workbook()
    print(
        f"  built value chain: {len(wb['machines'])} facilities, "
        f"{sum(1 for n in wb['nodes'] if n['level'] == 'company')} companies, "
        f"{len(wb['measures'])} measures"
    )
    validate(wb)
    (ASSETS / "examples" / "petrochemical.sqlite").write_bytes(write_sqlite(wb))
    # The component library (technologies + streams + measures) is recovered from
    # the workbook so it always matches the example's components.
    lib = extract_library_from_workbook(wb, label="Petrochemical (ethylene NCC + MACC)")
    (ASSETS / "component_libraries" / "petrochemical.json").write_text(
        json.dumps(lib.model_dump(), indent=2), encoding="utf-8"
    )
    print("  wrote assets/examples/petrochemical.sqlite + component_libraries/petrochemical.json")


if __name__ == "__main__":
    main()
