"""Flatten a process model into the node-hierarchy framework — generic.

A pre-hierarchy workbook describes facilities in a flat ``processes`` sheet wired
by ``edges``, scoped by ``company`` / ``group`` strings. :func:`to_hierarchy`
turns that into the ``nodes`` / ``assets`` / ``links`` tree the builder
and per-level solver use: a network root → company groups → facility groups
→ one asset per process; edges become links. No sector knowledge — it
reads only the generic scope columns.
"""

from __future__ import annotations

from pathwise.data.sheets import ASSETS, EDGES, LINKS, NODE_LAYOUT, NODES, PROCESSES
from pathwise.data.workbook import Workbook


def _s(v: object) -> str:
    return "" if v is None else str(v)


def _dedupe_nodes(nodes: list[dict[str, object]], root_id: str) -> list[dict[str, object]]:
    """Drop duplicate node ids (first wins) and break self-parent edges.

    A node listed twice, or one that names itself as its own ``parent_id``, makes
    any ancestor/descendant walk loop forever; this guarantees a well-formed tree
    no matter how malformed the source rows are.
    """
    out: list[dict[str, object]] = []
    used: set[str] = set()
    for nd in nodes:
        nid = _s(nd.get("node_id"))
        if not nid or nid in used:
            continue
        used.add(nid)
        if _s(nd.get("parent_id")) == nid:  # self-parent → reattach to root
            nd = {**nd, "parent_id": None if nid == root_id else root_id}
        out.append(nd)
    return out


def to_hierarchy(
    workbook: Workbook, *, root_id: str = "vc", root_label: str = "Value chain"
) -> Workbook:
    """Return ``workbook`` with a node hierarchy synthesised from ``processes``.

    A no-op if it already has ``nodes`` (already a hierarchy) or no ``processes``.
    The catalogue/scenario sheets are kept verbatim; ``processes`` / ``edges`` /
    ``node_layout`` are replaced by ``nodes`` / ``assets`` / ``links``.
    """
    if workbook.get(NODES):
        return workbook
    procs = workbook.get(PROCESSES, [])
    if not procs:
        return workbook

    nodes: list[dict[str, object]] = [
        {
            "node_id": root_id,
            "parent_id": None,
            "kind": "group",
            "level": "value_chain",
            "label": root_label,
        }
    ]
    seen = {root_id}

    def ensure(node_id: str, parent: str, level: str, label: str) -> None:
        if node_id not in seen:
            nodes.append(
                {
                    "node_id": node_id,
                    "parent_id": parent,
                    "kind": "group",
                    "level": level,
                    "label": label,
                }
            )
            seen.add(node_id)

    # A asset's node id IS its process id; group ids must stay disjoint from
    # those, or a process whose company/group is named after itself would parent
    # the asset to a same-named group (a self-parent cycle). So a grouping
    # level whose id collides with any asset id is skipped.
    pids = {_s(p.get("process_id")) for p in procs if _s(p.get("process_id"))}

    assets: list[dict[str, object]] = []
    for p in procs:
        pid = _s(p.get("process_id"))
        if not pid:
            continue
        company = _s(p.get("company")).strip()
        group = _s(p.get("group")).strip()
        parent = root_id
        if company and company != "all" and company not in pids:
            ensure(company, root_id, "company", company)
            parent = company
        if group and group not in ("", company, "all"):
            fid = f"{company}/{group}" if parent != root_id else group
            if fid not in pids:
                ensure(fid, parent, "facility", group)
                parent = fid
        nodes.append(
            {
                "node_id": pid,
                "parent_id": parent,
                "kind": "asset",
                "level": "asset",
                "label": pid,
            }
        )
        seen.add(pid)
        m: dict[str, object] = {
            "asset_id": pid,
            "baseline_technology": p.get("baseline_technology"),
            "capacity": p.get("capacity"),
        }
        if p.get("introduced_year") is not None:
            m["introduced_year"] = p.get("introduced_year")
        if p.get("decommission_year") is not None:
            m["decommission_year"] = p.get("decommission_year")
        if p.get("max_renewals") is not None:
            m["max_renewals"] = p.get("max_renewals")
        assets.append(m)

    links: list[dict[str, object]] = []
    for e in workbook.get(EDGES, []):
        f, t, c = _s(e.get("from_process")), _s(e.get("to_process")), _s(e.get("flow_id"))
        if f and t and c:
            row: dict[str, object] = {"from_node": f, "to_node": t, "flow_id": c}
            if e.get("lag_years") is not None:
                row["lag_years"] = e.get("lag_years")
            links.append(row)

    out = {k: v for k, v in workbook.items() if k not in (PROCESSES, EDGES, NODE_LAYOUT)}
    out[NODES] = _dedupe_nodes(nodes, root_id)
    out[ASSETS] = assets
    out[LINKS] = links
    return out
