// Pure graph logic for the recursive group/component hierarchy.
// No React, no I/O. Mirrors the workbook sheets: nodes, links, assets.

import type { Workbook } from "../types";

// ── Public types ──────────────────────────────────────────────────────────────

/** A node in the group hierarchy (group = composite, asset = leaf). */
export interface GroupNode {
  id: string;
  parentId: string | null;
  kind: "group" | "asset";
  /** The level string from the workbook row (informational). */
  level: string;
  label: string;
  /** Author-defined ordering within a parent; defaults to id-alpha. */
  order: number;
}

/** A directed flow between two nodes in the hierarchy. */
export interface GroupEdge {
  from: string;
  to: string;
  commodity: string;
  lag: number;
}

/** Position in the SVG canvas (units: pixels). */
export interface NodePos {
  x: number;
  y: number;
}

// ── Layout constants (mirrored from lib/graph.ts layeredLayout) ───────────────
const COL_W = 220;
const ROW_H = 108;
const ORIGIN_X = 40;
const ORIGIN_Y = 40;

// ── Helpers ──────────────────────────────────────────────────────────────────

const s = (v: unknown, d = ""): string => (v == null ? d : String(v));
const n = (v: unknown, d = 0): number => (v == null || v === "" ? d : Number(v));

// ── Parsers ───────────────────────────────────────────────────────────────────

/** Parse all nodes from the workbook's `nodes` sheet into typed GroupNodes.
 *  Rows with no `node_id` are silently skipped. */
export function parseNodes(wb: Workbook): GroupNode[] {
  // Dedupe by id (first wins) and break self-parent edges: a duplicate node id
  // or a node naming itself as parent would make the tree walks below
  // (ancestor/descendant/depth) loop forever and hang the UI on malformed data.
  const seen = new Set<string>();
  const out: GroupNode[] = [];
  for (const r of wb.nodes ?? []) {
    const id = s(r.node_id);
    if (id === "" || seen.has(id)) continue;
    seen.add(id);
    const parentId = s(r.parent_id) || null;
    out.push({
      id,
      parentId: parentId === id ? null : parentId,
      kind: s(r.kind) === "asset" ? ("asset" as const) : ("group" as const),
      level: s(r.level),
      label: s(r.label) || id,
      order: n(r.order),
    });
  }
  return out;
}

/** Return the ids of all root nodes (those with no parent). */
export function rootIds(nodes: GroupNode[]): string[] {
  return nodes.filter((nd) => nd.parentId === null).map((nd) => nd.id);
}

/** Return the direct children of a parent id (or roots when parentId is null),
 *  ordered by `order` then `id`. */
export function childrenOf(nodes: GroupNode[], parentId: string | null): GroupNode[] {
  return nodes
    .filter((nd) => nd.parentId === parentId)
    .sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
}

// ── Subtree helpers ───────────────────────────────────────────────────────────

/** Build a map from every node id to all its descendants (including itself). */
function buildSubtreeMap(nodes: GroupNode[]): Map<string, Set<string>> {
  // childrenIndex maps parentId → direct children ids
  const childrenIndex = new Map<string, string[]>();
  for (const nd of nodes) {
    if (nd.parentId !== null) {
      const arr = childrenIndex.get(nd.parentId) ?? [];
      arr.push(nd.id);
      childrenIndex.set(nd.parentId, arr);
    }
  }

  const cache = new Map<string, Set<string>>();

  const subtree = (id: string, seen: Set<string>): Set<string> => {
    const cached = cache.get(id);
    if (cached) return cached;
    if (seen.has(id)) return new Set([id]); // cycle guard
    seen.add(id);
    const result = new Set<string>([id]);
    for (const childId of childrenIndex.get(id) ?? []) {
      for (const desc of subtree(childId, new Set(seen))) result.add(desc);
    }
    cache.set(id, result);
    return result;
  };

  for (const nd of nodes) subtree(nd.id, new Set());
  return cache;
}

/** Walk up the ancestor chain of `nodeId` and return the direct child of
 *  `groupId` whose subtree contains `nodeId`. Returns null when `nodeId` is
 *  not in that subtree, or when `groupId` is null and `nodeId` is not a root. */
function ancestorChildOf(
  nodes: GroupNode[],
  groupId: string | null,
  nodeId: string,
  subtreeMap: Map<string, Set<string>>,
): string | null {
  // Find all direct children of groupId (or roots when groupId is null)
  const children = childrenOf(nodes, groupId);
  for (const child of children) {
    const sub = subtreeMap.get(child.id);
    if (sub?.has(nodeId)) return child.id;
  }
  return null;
}

// ── Level graph ──────────────────────────────────────────────────────────────

/** Compute the subgraph visible at a given level.
 *
 *  `children` = direct children of `groupId` (or top-level roots when null).
 *  `edges`    = workbook links projected to this level: only edges where
 *               both endpoints resolve to *distinct* children of `groupId`. */
export function levelGraph(
  wb: Workbook,
  groupId: string | null,
): { children: GroupNode[]; edges: GroupEdge[] } {
  const nodes = parseNodes(wb);
  const children = childrenOf(nodes, groupId);
  const childIds = new Set(children.map((c) => c.id));

  if (childIds.size === 0) return { children: [], edges: [] };

  const subtreeMap = buildSubtreeMap(nodes);

  const edges: GroupEdge[] = [];
  const seen = new Set<string>(); // dedup key

  for (const row of wb.links ?? []) {
    const fromRaw = s(row.from_node);
    const toRaw = s(row.to_node);
    if (!fromRaw || !toRaw) continue;

    const fromChild = ancestorChildOf(nodes, groupId, fromRaw, subtreeMap);
    const toChild = ancestorChildOf(nodes, groupId, toRaw, subtreeMap);
    if (!fromChild || !toChild || fromChild === toChild) continue;
    // Both endpoints are in this level and differ.

    const commodity = s(row.commodity_id, "—");
    const lag = n(row.lag_years);
    const key = `${fromChild}→${toChild}:${commodity}`;
    if (seen.has(key)) continue;
    seen.add(key);

    edges.push({ from: fromChild, to: toChild, commodity, lag });
  }

  return { children, edges };
}

// ── Layout ───────────────────────────────────────────────────────────────────

/** Compute a simple left→right flow-depth layout.
 *
 *  Each node's column = its longest incoming edge depth (via BFS/longest path
 *  in the DAG). Nodes within a column stack top-to-bottom. Cycles are guarded
 *  by a `visiting` set so the recursion terminates.
 *
 *  Spacing: COL_W=220, ROW_H=108, origin (40, 40) — mirrors lib/graph.ts. */
export function columnLayout(
  nodeIds: string[],
  edges: GroupEdge[],
): Map<string, NodePos> {
  if (nodeIds.length === 0) return new Map();

  // Incoming edges per node
  const inEdges = new Map<string, string[]>();
  for (const id of nodeIds) inEdges.set(id, []);
  for (const e of edges) {
    const arr = inEdges.get(e.to);
    if (arr) arr.push(e.from);
  }

  // Longest-path depth (column index), cycle-guarded
  const depthCache = new Map<string, number>();
  const depth = (id: string, visiting: Set<string>): number => {
    const cached = depthCache.get(id);
    if (cached !== undefined) return cached;
    if (visiting.has(id)) return 0; // cycle: place at shallowest
    visiting.add(id);
    let d = 0;
    for (const pred of inEdges.get(id) ?? []) {
      d = Math.max(d, depth(pred, new Set(visiting)) + 1);
    }
    depthCache.set(id, d);
    return d;
  };

  for (const id of nodeIds) depth(id, new Set());

  // Group by column, preserving the original order within each column
  const byCol = new Map<number, string[]>();
  for (const id of nodeIds) {
    const col = depthCache.get(id) ?? 0;
    const arr = byCol.get(col) ?? [];
    arr.push(id);
    byCol.set(col, arr);
  }

  const pos = new Map<string, NodePos>();
  for (const [col, ids] of byCol) {
    ids.forEach((id, i) => {
      pos.set(id, {
        x: ORIGIN_X + col * COL_W,
        y: ORIGIN_Y + i * ROW_H,
      });
    });
  }
  return pos;
}

// ── Editable level links ────────────────────────────────────────────────

/** One workbook link, projected to a level. Carries its row index so the
 *  editor can address/delete the exact row, and keeps `lag` (unlike `levelGraph`,
 *  which dedupes and loses it). */
export interface LevelLink {
  /** Index into `wb.links` — the addressable handle for delete. */
  rowIndex: number;
  /** Direct child of the level the source resolves to. */
  from: string;
  /** Direct child of the level the target resolves to. */
  to: string;
  commodity: string;
  lag: number;
}

/** Every `links` row whose endpoints resolve to two *distinct* children of
 *  `groupId` — one entry per row (no dedupe), so each edge is independently
 *  selectable/deletable and its lag is preserved. */
export function levelLinks(wb: Workbook, groupId: string | null): LevelLink[] {
  const nodes = parseNodes(wb);
  const children = childrenOf(nodes, groupId);
  if (children.length === 0) return [];
  const subtreeMap = buildSubtreeMap(nodes);

  const out: LevelLink[] = [];
  (wb.links ?? []).forEach((row, rowIndex) => {
    const fromRaw = s(row.from_node);
    const toRaw = s(row.to_node);
    if (!fromRaw || !toRaw) return;
    const fromChild = ancestorChildOf(nodes, groupId, fromRaw, subtreeMap);
    const toChild = ancestorChildOf(nodes, groupId, toRaw, subtreeMap);
    if (!fromChild || !toChild || fromChild === toChild) return;
    out.push({
      rowIndex,
      from: fromChild,
      to: toChild,
      commodity: s(row.commodity_id, "—"),
      lag: n(row.lag_years),
    });
  });
  return out;
}
