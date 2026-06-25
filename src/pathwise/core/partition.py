"""Partition a node hierarchy at a level into independent, coupled problems.

Choosing an optimisation level cuts the tree there: every node *at* that level
becomes the root of its own optimisation problem (a flat sub-workbook), and any
**connection crossing a cut boundary** becomes a network **coupling link**
(flow + lag + signals). The result is a :class:`NetworkSpec` plus the
per-cut workbooks — fed straight into :func:`pathwise.core.network.run_network`,
which solves and couples them. Connections *inside* a cut stay edges in that
sub-workbook (already expanded by the assembler).

The partition is pure data shuffling; the solve is the existing single-model
pipeline run per cut, with the cascade carrying the cross-cut signals.
"""

from __future__ import annotations

from typing import Any

from pathwise.data.assemble import _expand_hierarchy
from pathwise.data.hierarchy import Hierarchy
from pathwise.data.network import CouplingLink, NetworkSpec, Stage
from pathwise.data.workbook import Workbook

# Catalogue/scenario sheets shared by every cut sub-workbook (not partitioned).
_SHARED_PREFIXES = ("technologies", "flows", "impacts", "io", "markets", "storage")
_SHARED_SHEETS = {
    "periods",
    "meta",
    "transitions",
    "levers",
    "lever_blocks",
    "maccs",
    "macc_links",
    "tech_impacts",
    "flow_impacts",
    "flow_impacts_t",
}


def _cuts_for(node: str, cut_set: set[str], h: Hierarchy) -> set[str]:
    """The cut node(s) a node maps to: itself, its cut ancestor, or its cut descendants."""
    if node in cut_set:
        return {node}
    for a in h.ancestors(node):  # below the cut → the containing cut node
        if a in cut_set:
            return {a}
    return {d for d in h.descendants(node) if d in cut_set}  # above the cut → its cut descendants


def _scope_in_cut(scope: str, cut: str, h: Hierarchy) -> bool:
    """Whether a demand/cap scope (a node id) belongs to ``cut``'s subtree."""
    return scope == cut or scope in h.descendants(cut)


def _set_flow(wb: Workbook, flow: str, **fields: Any) -> None:
    """Override flow attributes in ``wb`` (copy-on-write; row added if absent)."""
    rows = wb.get("flows", [])
    new_rows = []
    found = False
    for r in rows:
        if str(r.get("flow_id")) == flow:
            new_rows.append({**r, **fields})
            found = True
        else:
            new_rows.append(r)
    if not found:
        new_rows.append({"flow_id": flow, **fields})
    wb["flows"] = new_rows


def _project(flat: Workbook, members: set[str], cut: str, h: Hierarchy) -> Workbook:
    """A flat, self-contained sub-workbook for one cut node."""
    sub: Workbook = {}
    for sheet, rows in flat.items():
        if sheet in ("nodes", "assets", "links", "ports"):
            continue  # the sub-workbook is flat (no re-expansion)
        if sheet == "processes":
            sub[sheet] = [r for r in rows if str(r.get("process_id")) in members]
        elif sheet == "edges":
            sub[sheet] = [
                r
                for r in rows
                if str(r.get("from_process")) in members and str(r.get("to_process")) in members
            ]
        elif sheet in (
            "demand",
            "impact_caps",
            "min_production",
            "min_consumption",
            "max_consumption",
            "investment_budget",
        ):
            sub[sheet] = [r for r in rows if _scope_in_cut(str(r.get("company")), cut, h)]
        else:
            sub[sheet] = list(rows)  # shared catalogue / scenario sheet
    return sub


def partition(
    workbook: Workbook,
    hierarchy: Hierarchy,
    level: str,
    *,
    signals: list[str] | None = None,
    default_lag: int = 0,
    feedback: bool = True,
    targets: list[str] | None = None,
) -> tuple[NetworkSpec, dict[str, Workbook]]:
    """Cut ``hierarchy`` at ``level`` → a coupling spec + one workbook per cut node.

    Args:
        workbook: The full model (with the node hierarchy sheets).
        hierarchy: The parsed tree.
        level: The designed level to cut at; every node there optimises alone.
        signals: Coupling signals carried by cross-cut links (default ``["price"]``).
        default_lag: Lag for a crossing connection that sets none.
        feedback: Mark cross-cut links as feedback (downstream demand → upstream),
            so an upstream cut produces what its downstream consumes.
        targets: Restrict the cut to these node ids (the chosen units); ``None``/
            empty ⇒ every node at ``level``.

    Returns:
        ``(spec, {cut_id: sub_workbook})`` ready for ``run_network``.
    """
    sig = list(signals or ["price"])
    cut_ids = _cut_ids(hierarchy, level, targets)
    cut_set = set(cut_ids)
    flat = _expand_hierarchy(workbook, hierarchy)

    asset_cut: dict[str, str] = {}
    for mid in hierarchy.assets:
        cuts = _cuts_for(mid, cut_set, hierarchy)
        if cuts:
            # Deterministic pick: iterating a set is hash-seed dependent, which made
            # the partition (and thus per-cut results) vary between runs.
            asset_cut[mid] = min(cuts)

    workbooks: dict[str, Workbook] = {}
    for cut in cut_ids:
        members = {m for m, c in asset_cut.items() if c == cut}
        workbooks[cut] = _project(flat, members, cut, hierarchy)

    links: list[CouplingLink] = []
    seen: set[tuple[str, str, str]] = set()
    for conn in hierarchy.links:
        for fc in _cuts_for(conn.from_node, cut_set, hierarchy):
            for tc in _cuts_for(conn.to_node, cut_set, hierarchy):
                if fc == tc or fc not in cut_set or tc not in cut_set:
                    continue
                key = (fc, tc, conn.flow_id)
                if key in seen:
                    continue
                seen.add(key)
                links.append(
                    CouplingLink(
                        from_stage=fc,
                        to_stage=tc,
                        flow=conn.flow_id,
                        signals=sig,
                        lag_years=conn.lag_years or default_lag,
                        feedback=feedback,
                    )
                )

    # The coupled stream is the upstream cut's product (it makes & sells it to
    # meet the fed-back demand) and a purchasable input to the downstream cut.
    for link in links:
        if link.from_stage in workbooks:
            _set_flow(workbooks[link.from_stage], link.flow, kind="product", sellable=True)
        if link.to_stage in workbooks:
            _set_flow(workbooks[link.to_stage], link.flow, purchasable=True)

    spec = NetworkSpec(
        id=f"partition@{level}",
        label=f"{level} partition",
        stages=[Stage(id=c, label=hierarchy.nodes[c].label) for c in cut_ids],
        links=links,
    )
    return spec, workbooks


def _cut_ids(hierarchy: Hierarchy, level: str, targets: list[str] | None) -> list[str]:
    """Node ids at ``level``, restricted to ``targets`` when given."""
    at_level = hierarchy.nodes_at_level(level)
    if not targets:
        return at_level
    keep = set(targets)
    return [c for c in at_level if c in keep]


def is_partitionable(hierarchy: Hierarchy, level: str, targets: list[str] | None = None) -> bool:
    """Whether cutting at ``level`` yields more than one independent problem."""
    cuts = _cut_ids(hierarchy, level, targets)
    return len(cuts) > 1 and set(cuts) != set(hierarchy.roots())


def subset_workbook(workbook: Workbook, hierarchy: Hierarchy, keep: list[str]) -> Workbook:
    """A workbook restricted to the subtrees rooted at ``keep`` (for a JOINT solve
    of a chosen set of units). Node/asset/connection/lever/scope rows outside
    the kept subtrees are dropped; shared catalogue + scenario sheets are kept.
    """
    members: set[str] = set()
    for k in keep:
        members.add(k)
        members |= hierarchy.descendants(k)
    sub: Workbook = {}
    for sheet, rows in workbook.items():
        if sheet == "nodes":
            sub[sheet] = [r for r in rows if str(r.get("node_id")) in members]
        elif sheet == "assets":
            sub[sheet] = [r for r in rows if str(r.get("asset_id")) in members]
        elif sheet == "links":
            sub[sheet] = [
                r
                for r in rows
                if str(r.get("from_node")) in members and str(r.get("to_node")) in members
            ]
        elif sheet == "ports":
            sub[sheet] = [r for r in rows if str(r.get("node_id")) in members]
        elif sheet == "levers":
            sub[sheet] = [r for r in rows if str(r.get("facility")) in members]
        elif sheet in (
            "demand",
            "markets",
            "impact_caps",
            "min_production",
            "min_consumption",
            "max_consumption",
            "investment_budget",
        ):
            sub[sheet] = [
                r
                for r in rows
                if str(r.get("company")) in members or str(r.get("company")) == "all"
            ]
        else:
            sub[sheet] = list(rows)  # shared catalogue / scenario sheet
    surviving = {str(r.get("lever_id")) for r in sub.get("levers", [])}
    if "lever_blocks" in sub:
        sub["lever_blocks"] = [
            r for r in sub["lever_blocks"] if str(r.get("lever_id")) in surviving
        ]
    return sub
