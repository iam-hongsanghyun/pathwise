"""Generic flat → node-hierarchy conversion (to_hierarchy)."""

from __future__ import annotations

from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig
from pathwise.data.convert import to_hierarchy


def _flat() -> dict[str, list[dict[str, object]]]:
    # two companies, one a 2-stage chain wired by an edge
    return {
        "processes": [
            {
                "process_id": "bf",
                "company": "SteelCo",
                "group": "mill",
                "baseline_technology": "BF",
                "capacity": 100,
            },
            {
                "process_id": "bof",
                "company": "SteelCo",
                "group": "mill",
                "baseline_technology": "BOF",
                "capacity": 100,
            },
            {
                "process_id": "gen",
                "company": "PowerCo",
                "baseline_technology": "GEN",
                "capacity": 100,
            },
        ],
        "edges": [{"from_process": "bf", "to_process": "bof", "flow_id": "iron"}],
        "technologies": [
            {"technology_id": "BF", "io": []},
            {"technology_id": "BOF", "io": []},
            {"technology_id": "GEN", "io": []},
        ],
        "io": [
            {"technology_id": "BF", "target": "coal", "role": "input", "coefficient": 1},
            {"technology_id": "BF", "target": "iron", "role": "output", "coefficient": 1},
            {"technology_id": "BOF", "target": "iron", "role": "input", "coefficient": 1},
            {
                "technology_id": "BOF",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
            {
                "technology_id": "GEN",
                "target": "electricity",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "flows": [
            {"flow_id": "coal", "kind": "material", "price": 100},
            {"flow_id": "iron", "kind": "material"},
            {"flow_id": "steel", "kind": "product"},
            {"flow_id": "electricity", "kind": "energy"},
        ],
        "periods": [{"year": 2025, "duration_years": 1}],
        "demand": [{"company": "SteelCo", "flow_id": "steel", "year": 2025, "amount": 50}],
    }


def test_to_hierarchy_builds_companies_facilities_machines() -> None:
    h = to_hierarchy(_flat(), root_label="Test")
    assert "processes" not in h and "edges" not in h
    by_id = {n["node_id"]: n for n in h["nodes"]}
    assert by_id["vc"]["kind"] == "group" and by_id["vc"]["parent_id"] is None
    assert by_id["SteelCo"]["parent_id"] == "vc" and by_id["SteelCo"]["level"] == "company"
    assert by_id["SteelCo/mill"]["parent_id"] == "SteelCo"  # facility group
    assert by_id["bf"]["parent_id"] == "SteelCo/mill" and by_id["bf"]["kind"] == "asset"
    assert {m["asset_id"] for m in h["assets"]} == {"bf", "bof", "gen"}
    # the edge became a connection
    assert h["links"] == [{"from_node": "bf", "to_node": "bof", "flow_id": "iron"}]


def test_converted_hierarchy_solves() -> None:
    h = to_hierarchy(_flat())
    res = run_model(
        h,
        ScenarioConfig.from_dict(
            {"economics": {"base_year": 2025}, "optimisation_scope": "system"}
        ),
    )
    assert res["status"] == "optimal" and not res["outputs"]["demand_slack"]


def test_to_hierarchy_is_noop_when_already_hierarchy() -> None:
    wb = {"nodes": [{"node_id": "x", "kind": "group"}], "assets": []}
    assert to_hierarchy(wb) is wb


def test_to_hierarchy_never_collides_asset_with_its_own_group() -> None:
    # Regression: when a process' company is named after the process itself
    # (each process its own singleton "company"), the old code emitted a group
    # AND a asset with the same id and parented the asset to itself — a
    # self-parent cycle that froze every downstream tree walk in the UI.
    flat = {
        "processes": [
            {"process_id": "ABS", "company": "ABS", "baseline_technology": "T", "capacity": 1},
            {"process_id": "PVC", "company": "PVC", "baseline_technology": "T", "capacity": 1},
        ],
    }
    nodes = to_hierarchy(flat)["nodes"]
    ids = [n["node_id"] for n in nodes]
    assert len(ids) == len(set(ids)), "node ids must be unique"
    assert all(n["parent_id"] != n["node_id"] for n in nodes), "no node is its own parent"
    # the degenerate same-named company is collapsed: assets sit under the root
    by_id = {n["node_id"]: n for n in nodes}
    assert by_id["ABS"]["kind"] == "asset" and by_id["ABS"]["parent_id"] == "vc"


def test_dedupe_nodes_breaks_duplicate_ids_and_self_parents() -> None:
    from pathwise.data.convert import _dedupe_nodes

    raw = [
        {"node_id": "vc", "parent_id": None, "kind": "group"},
        {"node_id": "a", "parent_id": "vc", "kind": "group"},
        {"node_id": "a", "parent_id": "a", "kind": "asset"},  # dup id + self-parent
    ]
    out = _dedupe_nodes(raw, "vc")
    assert [n["node_id"] for n in out] == ["vc", "a"]  # duplicate dropped (first wins)
    assert out[1]["parent_id"] == "vc"  # the dropped row's self-parent never survives
