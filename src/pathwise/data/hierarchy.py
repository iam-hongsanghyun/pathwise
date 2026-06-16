"""Recursive group hierarchy — a node tree layered above the flat engine.

A *model* can optionally carry a tree of **nodes** of arbitrary, user-defined
depth. Each node is either a ``group`` (a composite — its children are other
nodes, and it exposes boundary **ports**) or a ``machine`` (a leaf that runs one
technology with its own capacity). **Connections** wire sibling nodes by a
commodity and may carry a **time gap** (``lag_years``); they generalise the flat
``edges`` sheet. The fixed chain "value chain → sector → company → facility →
machine" is just one example — ``level`` is free text and depth is unbounded, so
nothing here is sector-specific.

This module is **pure and read-only**: it parses the optional ``nodes`` /
``machines`` / ``connections`` / ``ports`` sheets into an immutable
:class:`Hierarchy` and answers tree queries (subtree membership, leaf machines,
designed levels, derived ports). The optimisation engine consumes it elsewhere;
when these sheets are absent the model stays flat (``load_hierarchy`` returns
``None``) and behaves exactly as before.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pathwise.data.sheets import CONNECTIONS, MACHINES, NODES, PORTS

Workbook = dict[str, list[dict[str, Any]]]


class NodeKind(StrEnum):
    """What a node is."""

    GROUP = "group"  # composite: has children + boundary ports
    MACHINE = "machine"  # leaf: runs one technology


@dataclass(frozen=True, slots=True)
class Node:
    """One node of the tree.

    Attributes:
        node_id: Unique id across the whole tree.
        parent_id: Parent node id, or ``None`` for a root.
        kind: ``group`` or ``machine``.
        level: User-defined level name (e.g. ``"company"``) — free text; the only
            privileged level is the implicit leaf ``machine``.
        label: Display name.
        order: Sibling ordering hint for the UI.
    """

    node_id: str
    parent_id: str | None
    kind: NodeKind
    level: str = ""
    label: str = ""
    order: float = 0.0


@dataclass(frozen=True, slots=True)
class Machine:
    """Leaf detail: the sub-unit that runs a technology (mirrors a process row)."""

    machine_id: str
    baseline_technology: str
    capacity: float = 0.0
    introduced_year: int | None = None


@dataclass(frozen=True, slots=True)
class Connection:
    """A directed commodity flow between two sibling nodes (generalises an edge).

    Attributes:
        from_node: Producer node id.
        to_node: Consumer node id.
        commodity_id: The routed stream.
        lag_years: Time gap on the link [yr] — used when the connection crosses
            an optimisation boundary (becomes a coupling-link lag).
        max_flow: Optional per-period cap.
    """

    from_node: str
    to_node: str
    commodity_id: str
    lag_years: int = 0
    max_flow: float | None = None


@dataclass(frozen=True, slots=True)
class Port:
    """A boundary stream a group exposes to its siblings.

    Attributes:
        node_id: The group exposing the port.
        commodity_id: The stream.
        direction: ``"in"`` (the group consumes it) or ``"out"`` (it produces it).
        bind_node: The descendant the port resolves to inside the group.
    """

    node_id: str
    commodity_id: str
    direction: str
    bind_node: str | None = None


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # drop NaN


def _int(v: Any) -> int | None:
    f = _num(v)
    return None if f is None else int(f)


def _str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


@dataclass(slots=True)
class Hierarchy:
    """An immutable node tree plus its connections and ports."""

    nodes: dict[str, Node]
    machines: dict[str, Machine]
    connections: list[Connection]
    ports: list[Port]
    _children: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kids: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for n in self.nodes.values():
            if n.parent_id is not None and n.parent_id in kids:
                kids[n.parent_id].append(n.node_id)
        for parent in kids:
            kids[parent].sort(key=lambda c: (self.nodes[c].order, c))
        self._children = kids

    # ── tree queries ─────────────────────────────────────────────────────────

    def children(self, node_id: str) -> list[str]:
        """Direct children of ``node_id`` (sibling-ordered)."""
        return list(self._children.get(node_id, ()))

    def roots(self) -> list[str]:
        """Nodes with no parent (a tree has one; a forest has several)."""
        return sorted(nid for nid, n in self.nodes.items() if n.parent_id is None)

    def root(self) -> str:
        """The single root; raises if there is not exactly one."""
        rs = self.roots()
        if len(rs) != 1:
            raise ValueError(f"expected exactly one root, found {len(rs)}: {rs}")
        return rs[0]

    def ancestors(self, node_id: str) -> list[str]:
        """``node_id``'s parents up to the root (nearest first)."""
        out: list[str] = []
        seen = {node_id}
        cur = self.nodes[node_id].parent_id if node_id in self.nodes else None
        while cur is not None and cur in self.nodes and cur not in seen:
            out.append(cur)
            seen.add(cur)
            cur = self.nodes[cur].parent_id
        return out

    def descendants(self, node_id: str) -> set[str]:
        """All nodes strictly below ``node_id`` (transitive)."""
        out: set[str] = set()
        q = deque(self._children.get(node_id, ()))
        while q:
            c = q.popleft()
            if c in out:
                continue
            out.add(c)
            q.extend(self._children.get(c, ()))
        return out

    def leaf_machines(self, node_id: str) -> list[str]:
        """Machine-kind nodes in ``node_id``'s subtree (including itself)."""
        scope = {node_id} | self.descendants(node_id)
        return sorted(
            n for n in scope if n in self.nodes and self.nodes[n].kind == NodeKind.MACHINE
        )

    def in_scope(self, scope: str, machine_id: str) -> bool:
        """Whether ``machine_id`` falls under ``scope`` (``"all"`` ⇒ always)."""
        if scope == "all" or scope == machine_id:
            return True
        return scope in self.ancestors(machine_id)

    def depth(self, node_id: str) -> int:
        """Root = 0; each step down adds 1."""
        return len(self.ancestors(node_id))

    def levels(self) -> list[str]:
        """Distinct designed level names, ordered root→leaf by typical depth."""
        by_level: dict[str, int] = {}
        for nid, n in self.nodes.items():
            name = n.level or n.kind.value
            d = self.depth(nid)
            by_level[name] = min(by_level.get(name, d), d)
        return [name for name, _ in sorted(by_level.items(), key=lambda kv: (kv[1], kv[0]))]

    def nodes_at_level(self, level: str) -> list[str]:
        """Node ids whose ``level`` (or leaf kind) matches ``level``."""
        return sorted(nid for nid, n in self.nodes.items() if (n.level or n.kind.value) == level)

    def derive_ports(self) -> list[Port]:
        """Boundary ports implied by connections crossing a group boundary.

        For each connection, every group that contains exactly one of its two
        endpoints exposes a port (``out`` for the producer side, ``in`` for the
        consumer side). Explicitly authored :attr:`ports` are kept as-is and take
        precedence on ``(node_id, commodity_id, direction)``.
        """
        explicit = {(p.node_id, p.commodity_id, p.direction) for p in self.ports}
        derived: dict[tuple[str, str, str], Port] = {}
        for c in self.connections:
            up = {c.from_node} | set(self.ancestors(c.from_node))
            down = {c.to_node} | set(self.ancestors(c.to_node))
            for g in up - down:  # groups containing the producer but not the consumer
                key = (g, c.commodity_id, "out")
                if key not in explicit:
                    derived.setdefault(key, Port(g, c.commodity_id, "out", c.from_node))
            for g in down - up:  # groups containing the consumer but not the producer
                key = (g, c.commodity_id, "in")
                if key not in explicit:
                    derived.setdefault(key, Port(g, c.commodity_id, "in", c.to_node))
        return list(self.ports) + list(derived.values())

    def check(self) -> list[str]:
        """Integrity errors (empty ⇒ valid): dangling parents, cycles, bad refs."""
        errors: list[str] = []
        for n in self.nodes.values():
            if n.parent_id is not None and n.parent_id not in self.nodes:
                errors.append(f"node '{n.node_id}' has unknown parent '{n.parent_id}'")
        # cycle / disconnection: every node must reach a root via parents
        for nid in self.nodes:
            seen: set[str] = set()
            cur: str | None = nid
            while cur is not None:
                if cur in seen:
                    errors.append(f"node '{nid}' is in a parent cycle")
                    break
                seen.add(cur)
                parent = self.nodes[cur].parent_id if cur in self.nodes else None
                cur = parent
        for m in self.machines:
            if m not in self.nodes:
                errors.append(f"machine '{m}' has no matching node row")
            elif self.nodes[m].kind != NodeKind.MACHINE:
                errors.append(f"machine '{m}' is declared as a group node")
        for nid, n in self.nodes.items():
            if n.kind == NodeKind.MACHINE and nid not in self.machines:
                errors.append(f"machine node '{nid}' has no row in the machines sheet")
        for c in self.connections:
            for end in (c.from_node, c.to_node):
                if end not in self.nodes:
                    errors.append(f"connection references unknown node '{end}'")
        return errors


def load_hierarchy(workbook: Workbook) -> Hierarchy | None:
    """Parse the optional node-tree sheets, or ``None`` for a flat model."""
    node_rows = [r for r in workbook.get(NODES, []) if _str(r.get("node_id"))]
    if not node_rows:
        return None

    nodes: dict[str, Node] = {}
    for r in node_rows:
        nid = _str(r.get("node_id"))
        if nid is None:
            continue
        kind_s = (_str(r.get("kind")) or "group").lower()
        kind = NodeKind(kind_s) if kind_s in {k.value for k in NodeKind} else NodeKind.GROUP
        nodes[nid] = Node(
            node_id=nid,
            parent_id=_str(r.get("parent_id")),
            kind=kind,
            level=_str(r.get("level")) or "",
            label=_str(r.get("label")) or nid,
            order=_num(r.get("order")) or 0.0,
        )

    machines: dict[str, Machine] = {}
    for r in workbook.get(MACHINES, []):
        mid = _str(r.get("machine_id"))
        if mid is None:
            continue
        machines[mid] = Machine(
            machine_id=mid,
            baseline_technology=_str(r.get("baseline_technology")) or "",
            capacity=_num(r.get("capacity")) or 0.0,
            introduced_year=_int(r.get("introduced_year")),
        )

    connections: list[Connection] = []
    for r in workbook.get(CONNECTIONS, []):
        f, t, c = _str(r.get("from_node")), _str(r.get("to_node")), _str(r.get("commodity_id"))
        if f and t and c:
            connections.append(
                Connection(
                    from_node=f,
                    to_node=t,
                    commodity_id=c,
                    lag_years=_int(r.get("lag_years")) or 0,
                    max_flow=_num(r.get("max_flow")),
                )
            )

    ports: list[Port] = []
    for r in workbook.get(PORTS, []):
        nid, c = _str(r.get("node_id")), _str(r.get("commodity_id"))
        direction = (_str(r.get("direction")) or "in").lower()
        if nid and c and direction in {"in", "out"}:
            ports.append(Port(nid, c, direction, _str(r.get("bind_node"))))

    return Hierarchy(nodes=nodes, machines=machines, connections=connections, ports=ports)
