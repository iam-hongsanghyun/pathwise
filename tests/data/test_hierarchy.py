"""Recursive group hierarchy: parsing, subtree scope, levels, derived ports.

A pure read model layered above the flat engine. ``load_hierarchy`` returns
``None`` for a flat workbook (no ``nodes`` sheet); otherwise it answers tree
queries the optimisation layer will rely on (subtree membership = scope, leaf
machines, designed levels) and derives boundary ports from connections.
"""

from __future__ import annotations

from pathwise.data.hierarchy import NodeKind, load_hierarchy


def _wb() -> dict:
    # vc → {steel co, auto co}; steel co → {mill facility → [bf machine, eaf machine]}.
    return {
        "nodes": [
            {"node_id": "vc", "kind": "group", "level": "value_chain"},
            {"node_id": "steel", "parent_id": "vc", "kind": "group", "level": "company"},
            {"node_id": "auto", "parent_id": "vc", "kind": "group", "level": "company"},
            {"node_id": "mill", "parent_id": "steel", "kind": "group", "level": "facility"},
            {"node_id": "bf", "parent_id": "mill", "kind": "machine", "level": "machine"},
            {"node_id": "eaf", "parent_id": "mill", "kind": "machine", "level": "machine"},
            {"node_id": "press", "parent_id": "auto", "kind": "machine", "level": "machine"},
        ],
        "machines": [
            {"machine_id": "bf", "baseline_technology": "BF", "capacity": 100},
            {"machine_id": "eaf", "baseline_technology": "EAF", "capacity": 50},
            {"machine_id": "press", "baseline_technology": "Press", "capacity": 30},
        ],
        "connections": [
            {"from_node": "steel", "to_node": "auto", "commodity_id": "steel", "lag_years": 2},
        ],
    }


def test_flat_workbook_has_no_hierarchy() -> None:
    assert load_hierarchy({"processes": [{"process_id": "P"}]}) is None


def test_tree_parsing_and_children_order() -> None:
    h = load_hierarchy(_wb())
    assert h is not None
    assert h.root() == "vc"
    assert set(h.children("vc")) == {"steel", "auto"}
    assert h.nodes["bf"].kind == NodeKind.MACHINE


def test_subtree_scope_membership() -> None:
    h = load_hierarchy(_wb())
    assert h is not None
    # bf and eaf are under steel (and vc); press is not.
    assert h.in_scope("steel", "bf") and h.in_scope("steel", "eaf")
    assert not h.in_scope("steel", "press")
    assert h.in_scope("vc", "press")  # everything is under the root
    assert h.in_scope("all", "press")
    assert h.leaf_machines("steel") == ["bf", "eaf"]
    assert h.leaf_machines("mill") == ["bf", "eaf"]


def test_levels_ordered_root_to_leaf() -> None:
    h = load_hierarchy(_wb())
    assert h is not None
    assert h.levels() == ["value_chain", "company", "facility", "machine"]
    assert h.nodes_at_level("company") == ["auto", "steel"]


def test_derive_ports_from_boundary_crossing_connection() -> None:
    h = load_hierarchy(_wb())
    assert h is not None
    ports = h.derive_ports()
    # steel→auto on 'steel' crosses both company boundaries: steel exposes an out
    # port, auto an in port (the value-chain root contains both, so no port there).
    out_ports = {(p.node_id, p.direction) for p in ports if p.commodity_id == "steel"}
    assert ("steel", "out") in out_ports
    assert ("auto", "in") in out_ports
    assert not any(p.node_id == "vc" for p in ports)


def test_check_flags_dangling_parent_and_missing_machine_row() -> None:
    wb = _wb()
    wb["nodes"].append({"node_id": "ghost", "parent_id": "nope", "kind": "machine"})
    h = load_hierarchy(wb)
    assert h is not None
    errors = h.check()
    assert any("unknown parent" in e for e in errors)
    assert any("ghost" in e and "machines sheet" in e for e in errors)
