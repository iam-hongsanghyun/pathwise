"""Assets as real parallel sub-units: a facility = the sum of its assets.

With a node hierarchy, each asset becomes its own process, so one facility can
run MULTIPLE technologies in the SAME year — impossible in the flat model where a
process runs exactly one technology per period. Scope (demand at the company
level) still resolves through the synthesized company/group.
"""

from __future__ import annotations

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

SC = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _wb() -> dict:
    # vc → co (company) → mill (facility) → {bf, eaf} assets, both make steel.
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "flows": [
            {"flow_id": "steel", "kind": "product"},
            {"flow_id": "power", "kind": "energy", "price": 1.0},
        ],
        "technologies": [{"technology_id": "BF"}, {"technology_id": "EAF"}],
        "io": [
            {"technology_id": "BF", "target": "power", "role": "input", "coefficient": 2},
            {
                "technology_id": "BF",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
            {"technology_id": "EAF", "target": "power", "role": "input", "coefficient": 1},
            {
                "technology_id": "EAF",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "nodes": [
            {"node_id": "vc", "kind": "group", "level": "value_chain"},
            {"node_id": "co", "parent_id": "vc", "kind": "group", "level": "company"},
            {"node_id": "mill", "parent_id": "co", "kind": "group", "level": "facility"},
            {"node_id": "bf", "parent_id": "mill", "kind": "asset", "level": "asset"},
            {"node_id": "eaf", "parent_id": "mill", "kind": "asset", "level": "asset"},
        ],
        "assets": [
            {"asset_id": "bf", "baseline_technology": "BF", "capacity": 100},
            {"asset_id": "eaf", "baseline_technology": "EAF", "capacity": 100},
        ],
        "demand": [{"company": "co", "flow_id": "steel", "year": 2025, "amount": 150}],
    }


def _throughput(res: dict) -> dict:
    return {r["process"]: r["value"] for r in res["outputs"]["throughput"] if r["period"] == 2025}


def test_two_machines_run_in_parallel_under_one_facility() -> None:
    res = extract_results(solve(build(assemble_problem(_wb(), SC))))
    assert res["status"] == "optimal"
    assert not res["outputs"]["demand_slack"], "company-level demand should be met by the assets"
    tp = _throughput(res)
    # 150 demand, each asset caps at 100 ⇒ BOTH must run (two technologies, one year).
    assert tp.get("bf", 0) > 0 and tp.get("eaf", 0) > 0
    assert tp.get("bf", 0) + tp.get("eaf", 0) == 150


def test_flat_model_is_unaffected() -> None:
    # No nodes sheet ⇒ flat behaviour: one process, one technology.
    wb = {
        "periods": [{"year": 2025}],
        "flows": [
            {"flow_id": "steel", "kind": "product"},
            {"flow_id": "power", "kind": "energy", "price": 1.0},
        ],
        "technologies": [{"technology_id": "EAF"}],
        "io": [
            {"technology_id": "EAF", "target": "power", "role": "input", "coefficient": 1},
            {
                "technology_id": "EAF",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "processes": [
            {"process_id": "Mill", "company": "co", "baseline_technology": "EAF", "capacity": 200}
        ],
        "demand": [{"company": "co", "flow_id": "steel", "year": 2025, "amount": 100}],
    }
    res = extract_results(solve(build(assemble_problem(wb, SC))))
    assert res["status"] == "optimal" and not res["outputs"]["demand_slack"]
