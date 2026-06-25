"""Recursive group hierarchy: parsing, subtree scope, levels, derived ports.

A pure read model layered above the flat engine. ``load_hierarchy`` returns
``None`` for a flat workbook (no ``nodes`` sheet); otherwise it answers tree
queries the optimisation layer will rely on (subtree membership = scope, leaf
assets, designed levels) and derives boundary ports from connections.
"""

from __future__ import annotations

from pathwise.data.hierarchy import NodeKind, load_hierarchy


def _wb() -> dict:
    # vc → {steel co, auto co}; steel co → {mill facility → [bf asset, eaf asset]}.
    return {
        "nodes": [
            {"node_id": "vc", "kind": "group", "level": "value_chain"},
            {"node_id": "steel", "parent_id": "vc", "kind": "group", "level": "company"},
            {"node_id": "auto", "parent_id": "vc", "kind": "group", "level": "company"},
            {"node_id": "mill", "parent_id": "steel", "kind": "group", "level": "facility"},
            {"node_id": "bf", "parent_id": "mill", "kind": "asset", "level": "asset"},
            {"node_id": "eaf", "parent_id": "mill", "kind": "asset", "level": "asset"},
            {"node_id": "press", "parent_id": "auto", "kind": "asset", "level": "asset"},
        ],
        "assets": [
            {"asset_id": "bf", "baseline_technology": "BF", "capacity": 100},
            {"asset_id": "eaf", "baseline_technology": "EAF", "capacity": 50},
            {"asset_id": "press", "baseline_technology": "Press", "capacity": 30},
        ],
        "links": [
            {"from_node": "steel", "to_node": "auto", "flow_id": "steel", "lag_years": 2},
        ],
    }


def test_flat_workbook_has_no_hierarchy() -> None:
    assert load_hierarchy({"processes": [{"process_id": "P"}]}) is None


def test_tree_parsing_and_children_order() -> None:
    h = load_hierarchy(_wb())
    assert h is not None
    assert h.root() == "vc"
    assert set(h.children("vc")) == {"steel", "auto"}
    assert h.nodes["bf"].kind == NodeKind.ASSET


def test_subtree_scope_membership() -> None:
    h = load_hierarchy(_wb())
    assert h is not None
    # bf and eaf are under steel (and vc); press is not.
    assert h.in_scope("steel", "bf") and h.in_scope("steel", "eaf")
    assert not h.in_scope("steel", "press")
    assert h.in_scope("vc", "press")  # everything is under the root
    assert h.in_scope("all", "press")
    assert h.leaf_assets("steel") == ["bf", "eaf"]
    assert h.leaf_assets("mill") == ["bf", "eaf"]


def test_levels_ordered_root_to_leaf() -> None:
    h = load_hierarchy(_wb())
    assert h is not None
    assert h.levels() == ["value_chain", "company", "facility", "asset"]
    assert h.nodes_at_level("company") == ["auto", "steel"]


def test_derive_ports_from_boundary_crossing_connection() -> None:
    h = load_hierarchy(_wb())
    assert h is not None
    ports = h.derive_ports()
    # steel→auto on 'steel' crosses both company boundaries: steel exposes an out
    # port, auto an in port (the network root contains both, so no port there).
    out_ports = {(p.node_id, p.direction) for p in ports if p.flow_id == "steel"}
    assert ("steel", "out") in out_ports
    assert ("auto", "in") in out_ports
    assert not any(p.node_id == "vc" for p in ports)


def test_check_flags_dangling_parent_and_missing_asset_row() -> None:
    wb = _wb()
    wb["nodes"].append({"node_id": "ghost", "parent_id": "nope", "kind": "asset"})
    h = load_hierarchy(wb)
    assert h is not None
    errors = h.check()
    assert any("unknown parent" in e for e in errors)
    assert any("ghost" in e and "assets sheet" in e for e in errors)


def test_asset_max_renewals_parses_and_reaches_the_process() -> None:
    # The per-asset renewal cap is authored on the asset row and must survive
    # the hierarchy → flat-process expansion (``_expand_hierarchy``) — the path
    # the network/project UI uses, distinct from the flat ``processes`` sheet.
    from pathwise.data import ScenarioConfig, assemble_problem

    wb = {
        "periods": [{"year": 2025, "duration_years": 1}],
        "flows": [{"flow_id": "w", "kind": "product", "unit": "t"}],
        "impacts": [],
        "technologies": [{"technology_id": "T", "lifespan": 5}],
        "nodes": [
            {"node_id": "co", "kind": "group", "level": "company"},
            {"node_id": "P", "parent_id": "co", "kind": "asset", "level": "asset"},
        ],
        "assets": [
            {
                "asset_id": "P",
                "baseline_technology": "T",
                "capacity": 100,
                "introduced_year": 2020,
                "max_renewals": 2,
            }
        ],
        "io": [
            {
                "technology_id": "T",
                "target": "w",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            }
        ],
    }
    h = load_hierarchy(wb)
    assert h is not None and h.assets["P"].max_renewals == 2
    prob = assemble_problem(wb, ScenarioConfig.from_dict({}))
    assert {p.process_id: p.max_renewals for p in prob.processes} == {"P": 2}


def test_asset_build_and_close_year_reach_the_process() -> None:
    # The Facility view edits a asset's build/close year; both must survive the
    # hierarchy → process expansion as introduced_year / decommission_year (the
    # canonical engine columns). Regression: they used to be dropped silently.
    from pathwise.data import ScenarioConfig, assemble_problem

    wb = {
        "periods": [{"year": 2025, "duration_years": 1}],
        "flows": [{"flow_id": "w", "kind": "product", "unit": "t"}],
        "impacts": [],
        "technologies": [{"technology_id": "T", "lifespan": 30}],
        "nodes": [
            {"node_id": "co", "kind": "group", "level": "company"},
            {"node_id": "P", "parent_id": "co", "kind": "asset", "level": "asset"},
        ],
        "assets": [
            {
                "asset_id": "P",
                "baseline_technology": "T",
                "capacity": 100,
                "introduced_year": 2020,
                "decommission_year": 2030,
            }
        ],
        "io": [
            {
                "technology_id": "T",
                "target": "w",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            }
        ],
    }
    h = load_hierarchy(wb)
    assert h is not None and h.assets["P"].decommission_year == 2030
    prob = assemble_problem(wb, ScenarioConfig.from_dict({}))
    p = prob.processes[0]
    assert (p.introduced_year, p.decommission_year) == (2020, 2030)
