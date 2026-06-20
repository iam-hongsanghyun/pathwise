// TreeExplorer — a domain-agnostic directory tree: recursive collapsible rows,
// selection, right-click context menu, and HTML5 drag-to-reparent with a
// descendant-drop guard and a visual drop indicator. Both builder tabs use it.

import { useMemo, useRef, useState } from "react";
import { ContextMenu } from "./ContextMenu";
import type { DropPosition, TreeAction, TreeMoveEvent, TreeNode } from "./types";

interface Props {
  nodes: TreeNode[];
  selectedId: string | null;
  expandedIds: Set<string>;
  onToggle: (id: string, expanded: boolean) => void;
  onSelect: (id: string) => void;
  /** Per-node menu items (computed from node.kind by the host). [] ⇒ no menu. */
  actionsFor: (node: TreeNode) => TreeAction[];
  onContextAction: (actionId: string, node: TreeNode) => void;
  /** Reparent / reorder. The host validates against its domain & mutates state. */
  onMove: (e: TreeMoveEvent) => void;
  /** Extra drop validation on top of the built-in self/descendant guard. */
  canDrop?: (dragId: string, targetId: string | null) => boolean;
  /** Does `target` accept a drag from OUTSIDE this tree (another tree instance)?
   *  Enables cross-tree drag-copy (e.g. the Facility view's library → structure). */
  acceptsExternal?: (target: TreeNode) => boolean;
  /** A foreign drag (its `payload` = the source tree's dragId, carried via the
   *  dataTransfer string) dropped on `target`. The host performs the action. */
  onExternalDrop?: (payload: string, target: TreeNode) => void;
  emptyHint?: React.ReactNode;
}

const INDENT = 14;

export function TreeExplorer({
  nodes,
  selectedId,
  expandedIds,
  onToggle,
  onSelect,
  actionsFor,
  onContextAction,
  onMove,
  canDrop,
  acceptsExternal,
  onExternalDrop,
  emptyHint,
}: Props) {
  const dragId = useRef<string | null>(null);
  const [dropHint, setDropHint] = useState<{ id: string; position: DropPosition } | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; node: TreeNode } | null>(null);

  const byParent = useMemo(() => {
    const m = new Map<string | null, TreeNode[]>();
    nodes.forEach((nd, idx) => {
      const arr = m.get(nd.parentId) ?? [];
      arr.push(nd);
      m.set(nd.parentId, arr);
      (nd as TreeNode & { _idx?: number })._idx = idx;
    });
    for (const arr of m.values())
      arr.sort(
        (a, b) =>
          (a.order ?? 0) - (b.order ?? 0) ||
          ((a as { _idx?: number })._idx ?? 0) - ((b as { _idx?: number })._idx ?? 0),
      );
    return m;
  }, [nodes]);

  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  /** Is `maybe` an ancestor of (or equal to) `id`? Used to forbid dropping a node
   *  into its own subtree. */
  const isAncestorOrSelf = (maybe: string, id: string): boolean => {
    let cur: string | null = id;
    while (cur) {
      if (cur === maybe) return true;
      cur = nodeById.get(cur)?.parentId ?? null;
    }
    return false;
  };

  const allowDrop = (target: TreeNode, position: DropPosition): boolean => {
    const drag = dragId.current;
    if (!drag || drag === target.id) return false;
    const droppable = target.droppable ?? (target.kind !== "machine" && target.kind !== "leaf");
    if (position === "inside" && !droppable) return false;
    if (isAncestorOrSelf(drag, target.id)) return false; // can't drop into own subtree
    const newParent = position === "inside" ? target.id : target.parentId;
    if (newParent && isAncestorOrSelf(drag, newParent)) return false;
    return canDrop ? canDrop(drag, newParent) : true;
  };

  function rows(parentId: string | null, depth: number): React.ReactNode[] {
    const kids = byParent.get(parentId) ?? [];
    const out: React.ReactNode[] = [];
    for (const nd of kids) {
      const expanded = expandedIds.has(nd.id);
      const isSel = nd.id === selectedId;
      const hint = dropHint?.id === nd.id ? dropHint.position : null;
      out.push(
        <div
          key={nd.id}
          draggable={nd.draggable ?? true}
          onDragStart={(e) => {
            dragId.current = nd.id;
            e.dataTransfer.setData("text/plain", nd.id);
            e.dataTransfer.effectAllowed = "move";
          }}
          onDragEnd={() => {
            dragId.current = null;
            setDropHint(null);
          }}
          onDragOver={(e) => {
            if (!dragId.current) {
              // A drag from another tree instance — accept onto external targets.
              if (onExternalDrop && acceptsExternal?.(nd) && e.dataTransfer.types.includes("text/plain")) {
                e.preventDefault();
                e.dataTransfer.dropEffect = "copy";
                if (dropHint?.id !== nd.id || dropHint.position !== "inside")
                  setDropHint({ id: nd.id, position: "inside" });
              } else if (dropHint?.id === nd.id) {
                setDropHint(null);
              }
              return;
            }
            const rect = e.currentTarget.getBoundingClientRect();
            const rel = (e.clientY - rect.top) / rect.height;
            const position: DropPosition =
              rel < 0.25 ? "before" : rel > 0.75 ? "after" : "inside";
            if (!allowDrop(nd, position)) {
              e.dataTransfer.dropEffect = "none";
              if (dropHint?.id === nd.id) setDropHint(null);
              return;
            }
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            if (dropHint?.id !== nd.id || dropHint.position !== position)
              setDropHint({ id: nd.id, position });
          }}
          onDrop={(e) => {
            const drag = dragId.current;
            const h = dropHint;
            dragId.current = null;
            setDropHint(null);
            if (!drag) {
              // External (cross-tree) drop: read the foreign dragId from the payload.
              const payload = e.dataTransfer.getData("text/plain");
              if (onExternalDrop && payload && acceptsExternal?.(nd)) {
                e.preventDefault();
                onExternalDrop(payload, nd);
              }
              return;
            }
            if (!h || h.id !== nd.id || !allowDrop(nd, h.position)) return;
            e.preventDefault();
            onMove({
              dragId: drag,
              targetId: h.position === "inside" ? nd.id : nd.parentId,
              position: h.position,
              beforeSiblingId: nd.id,
            });
          }}
          onClick={() => onSelect(nd.id)}
          onContextMenu={(e) => {
            e.preventDefault();
            onSelect(nd.id);
            setMenu({ x: e.clientX, y: e.clientY, node: nd });
          }}
          className={`tree-row${isSel ? " is-active" : ""}`}
          style={{
            paddingLeft: 6 + depth * INDENT,
            borderTop: hint === "before" ? "2px solid var(--brand)" : "2px solid transparent",
            borderBottom: hint === "after" ? "2px solid var(--brand)" : "2px solid transparent",
            outline: hint === "inside" ? "2px solid var(--brand)" : "none",
            outlineOffset: -2,
            background: isSel ? "var(--brand-fill)" : undefined,
            opacity: nd.muted ? 0.55 : undefined,
            fontStyle: nd.muted ? "italic" : undefined,
          }}
        >
          <span
            className="tree-twisty"
            onClick={(e) => {
              e.stopPropagation();
              if (nd.hasChildren) onToggle(nd.id, !expanded);
            }}
            style={{ width: 14, flex: "none", display: "inline-block", textAlign: "center", color: "var(--muted)", cursor: nd.hasChildren ? "pointer" : "default" }}
          >
            {nd.hasChildren ? (expanded ? "▾" : "▸") : ""}
          </span>
          <span
            className="tree-glyph"
            style={{
              flex: "none",
              display: "inline-block",
              width: 16,
              textAlign: "center",
              marginRight: 5,
              opacity: 0.7,
            }}
          >
            {nd.muted ? "↳" : nd.kind === "library" ? "▣" : nd.kind === "group" ? "▾" : "▪"}
          </span>
          <span className="tree-label">{nd.label}</span>
          {nd.level && <span className="tree-level"> · {nd.level}</span>}
          {nd.badge && (
            <span
              className={`tree-badge ${nd.badge.severity}`}
              style={{ marginLeft: "auto", flex: "none" }}
              title={`${nd.badge.count} issue${nd.badge.count === 1 ? "" : "s"} here or inside`}
            />
          )}
        </div>,
      );
      if (expanded && nd.hasChildren) out.push(...rows(nd.id, depth + 1));
    }
    return out;
  }

  const top = rows(null, 0);

  return (
    <div className="tree-explorer">
      {top.length === 0 ? (
        <div className="rail-empty" style={{ padding: 10 }}>
          {emptyHint ?? "empty"}
        </div>
      ) : (
        top
      )}
      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          actions={actionsFor(menu.node)}
          onAction={(id) => onContextAction(id, menu.node)}
          onClose={() => setMenu(null)}
        />
      )}
    </div>
  );
}
