"""Petrochemical example is the REAL coupled value chain (build_petrochemical).

The petrochemical port is a framework-native value chain (not the source's greedy
MACC): all 248 plants grouped by company, each cracker able to TRANSITION to an
electric / H2 cracker, and downstream plants consuming the cracker's olefin. This
guards that structure (built from the vendored source data); the heavy joint MILP
solve is exercised separately, not here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _build_workbook() -> dict:
    spec = importlib.util.spec_from_file_location(
        "build_petrochemical", ROOT / "scripts" / "build_petrochemical.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_workbook()


def test_all_248_facilities_by_company() -> None:
    wb = _build_workbook()
    assert len(wb["machines"]) == 248
    companies = {n["node_id"] for n in wb["nodes"] if n.get("level") == "company"}
    assert len(companies) == 60


def test_crackers_can_transition_to_electric_and_h2() -> None:
    wb = _build_workbook()
    trans = {(t["from_technology"], t["to_technology"]) for t in wb["transitions"]}
    assert ("Ethylene", "Ethylene__NCC_Electricity") in trans
    assert ("Ethylene", "Ethylene__NCC_H2") in trans


def test_recipes_consume_real_inputs_and_couple_downstream() -> None:
    io = _build_workbook()["io"]

    def inputs(tech: str) -> set[str]:
        return {r["target"] for r in io if r["technology_id"] == tech and r["role"] == "input"}

    # The cracker burns naphtha + fuels (not "from nothing").
    assert "Naphtha" in inputs("Ethylene")
    # Downstream consumes the cracker's olefin — the coupled chain.
    assert "Ethylene" in inputs("HDPE")
    assert "Propylene" in inputs("PP")
