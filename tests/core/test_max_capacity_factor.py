"""Per-machine max capacity factor: throughput ≤ max_cf × capacity (the
utilisation ceiling mirror of the must-run min_capacity_factor floor)."""

from __future__ import annotations

from typing import Any

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _sc() -> ScenarioConfig:
    return ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    return extract_results(solve(build(assemble_problem(wb, _sc()))))


def _produced(res: dict[str, Any], commodity: str) -> float:
    return sum(s["produced"] for s in res["summary"]["commodity"] if s["commodity"] == commodity)


# ── Flat model ───────────────────────────────────────────────────────────────


def _flat(max_cf: float | None) -> dict[str, Any]:
    p: dict[str, Any] = {
        "process_id": "P",
        "company": "C",
        "baseline_technology": "EAF",
        "capacity": 100,
    }
    if max_cf is not None:
        p["max_capacity_factor"] = max_cf
    return {
        "periods": [{"year": 2025}],
        "commodities": [{"commodity_id": "steel", "kind": "product"}],
        "technologies": [{"technology_id": "EAF", "opex": 1.0}],
        "processes": [p],
        "io": [
            {
                "technology_id": "EAF",
                "target": "steel",
                "role": "output",
                "coefficient": 1.0,
                "is_product": True,
            }
        ],
        "demand": [{"company": "C", "commodity_id": "steel", "year": 2025, "amount": 100.0}],
    }


def test_max_cf_is_assembled() -> None:
    prob = assemble_problem(_flat(0.5), _sc())
    assert prob.processes[0].max_capacity_factor == 0.5
    # Default is 1.0 (no ceiling) when unset.
    assert assemble_problem(_flat(None), _sc()).processes[0].max_capacity_factor == 1.0


def test_no_ceiling_meets_demand() -> None:
    res = _solve(_flat(None))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_produced(res, "steel"), 100.0, rtol=1e-6, atol=1e-6)


def test_max_cf_caps_throughput() -> None:
    # Demand pulls 100 but capacity 100 × max_cf 0.5 = 50 ⇒ output capped at 50.
    res = _solve(_flat(0.5))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_produced(res, "steel"), 50.0, rtol=1e-6, atol=1e-6)


def test_max_cf_zero_locks_the_machine() -> None:
    # An authored 0 means "do not run this machine" and must survive assembly.
    # (The old `_num(...) or 1.0` turned a falsy 0.0 into the 1.0 default, so a
    # locked-out machine silently ran at full capacity.)
    assert assemble_problem(_flat(0.0), _sc()).processes[0].max_capacity_factor == 0.0
    res = _solve(_flat(0.0))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_produced(res, "steel"), 0.0, atol=1e-6)


# ── Node model: machine max_capacity_factor carried through _expand_hierarchy ──


def test_hierarchy_machine_max_cf_caps_throughput() -> None:
    wb = {
        "nodes": [
            {"node_id": "co", "parent_id": None, "kind": "group", "level": "company"},
            {"node_id": "co/m", "parent_id": "co", "kind": "machine"},
        ],
        "machines": [
            {
                "machine_id": "co/m",
                "baseline_technology": "EAF",
                "capacity": 100,
                "max_capacity_factor": 0.5,
            }
        ],
        "technologies": [{"technology_id": "EAF", "opex": 1.0}],
        "io": [
            {
                "technology_id": "EAF",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            }
        ],
        "commodities": [{"commodity_id": "steel", "kind": "product"}],
        "periods": [{"year": 2025}],
        "demand": [{"company": "all", "commodity_id": "steel", "amount": 100}],
    }
    res = _solve(wb)
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_produced(res, "steel"), 50.0, rtol=1e-6, atol=1e-6)


# ── Temporal: the ceiling varies by year (processes_t__max_capacity_factor) ────


def test_max_cf_varies_by_year() -> None:
    wb = _flat(None)
    wb["periods"] = [{"year": 2025}, {"year": 2030}]
    wb["demand"] = [
        {"company": "C", "commodity_id": "steel", "amount": 100}
    ]  # year-less ⇒ both years
    wb["processes_t__max_capacity_factor"] = [{"year": 2025, "P": 1.0}, {"year": 2030, "P": 0.5}]
    res = _solve(wb)
    assert res["status"] == "optimal"
    # 2025 full (100) + 2030 capped at 50 = 150 produced over the two years.
    np.testing.assert_allclose(_produced(res, "steel"), 150.0, rtol=1e-6, atol=1e-6)
