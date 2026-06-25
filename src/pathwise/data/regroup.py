"""Structural normalisation: wrap bare assets under a ``Technology`` kind-group.

The network rule is that every component sits under a Technology / Stream /
Measures & MACC group; older example models placed assets directly under a
company / facility. ``regroup_machines`` inserts the missing ``Technology`` group
and reparents the assets to it.

It is **engine-equivalent**: scope resolution walks the ancestor chain (which still
contains the original company / facility), and ``company_of`` keys off the
child-of-root, so inserting a deeper group changes neither. Connections key off
asset ids, which are unchanged, so wiring is preserved.
"""

from __future__ import annotations

import copy
from typing import Any

#: The kind-group level that assets (technology instances) live under.
TECHNOLOGY_LEVEL = "Technology"


def regroup_machines(workbook: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``workbook`` with every bare asset under a Technology group.

    A asset whose parent is already a ``Technology`` group is left alone. One
    group is created per parent that holds assets, shared by its assets.
    """
    nodes = workbook.get("nodes")
    if not nodes:
        return workbook
    out = copy.deepcopy(workbook)
    nodes = out["nodes"]
    by_id = {n.get("node_id"): n for n in nodes}
    group_for: dict[Any, str] = {}  # parent id → its Technology group id
    new_groups: list[dict[str, Any]] = []
    for n in nodes:
        if n.get("kind") != "asset":
            continue
        parent = n.get("parent_id")
        pnode = by_id.get(parent)
        if pnode is not None and pnode.get("level") == TECHNOLOGY_LEVEL:
            continue  # already grouped
        if parent not in group_for:
            kg_id = f"{parent}/_technology" if parent else "_technology"
            group_for[parent] = kg_id
            new_groups.append(
                {
                    "node_id": kg_id,
                    "parent_id": parent,
                    "kind": "group",
                    "level": TECHNOLOGY_LEVEL,
                    "label": TECHNOLOGY_LEVEL,
                }
            )
        n["parent_id"] = group_for[parent]
    nodes.extend(new_groups)
    return out
