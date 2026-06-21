// Pure layout for the multi-level result map: turn the node hierarchy
// (country → company → facility → machine) into absolutely-positioned boxes for
// three render modes — nested containers, swimlanes-by-level, and an expandable
// (collapsible) nested view. No React, no I/O; mirrors the .topo-* sizing.

import { childrenOf, levelConnections, parseNodes, type GroupNode } from "./groupGraph";
import type { Workbook } from "../types";

export type MapMode = "nested" | "swimlane" | "expandable";

/** A positioned box for any node (group container or machine leaf). */
export interface LaidNode {
  id: string;
  parentId: string | null;
  kind: "group" | "machine";
  level: string;
  label: string;
  depth: number;
  x: number;
  y: number;
  w: number;
  h: number;
  /** A group drawn collapsed (expandable mode) — render as a leaf-like box. */
  collapsed: boolean;
}

/** A machine→machine flow to draw, resolved to the deepest VISIBLE endpoints.
 *  `origFrom`/`origTo` keep the real connection endpoints so the per-year
 *  overlay (keyed by the actual machine ids) can be looked up even when the
 *  drawn endpoints are collapsed group boxes. */
export interface LaidEdge {
  id: string;
  from: string;
  to: string;
  origFrom: string;
  origTo: string;
  commodity: string;
}

export interface Laid {
  nodes: LaidNode[];
  edges: LaidEdge[];
  width: number;
  height: number;
}

// ── Geometry constants ────────────────────────────────────────────────────────
const LEAF_W = 168;
const LEAF_H = 56;
const GAP_X = 40; // between columns inside a container
const GAP_Y = 20; // between stacked siblings
const PAD = 16; // inner padding of a container
const HEADER = 24; // container title strip

const s = (v: unknown, d = ""): string => (v == null ? d : String(v));
const num = (v: unknown, d = 0): number => (v == null || v === "" ? d : Number(v));

// ── Shared helpers ────────────────────────────────────────────────────────────

/** Longest-path column index per id over the given (from→to) edges (cycle-safe). */
function columnsOf(ids: string[], edges: { from: string; to: string }[]): Map<string, number> {
  const preds = new Map<string, string[]>();
  for (const id of ids) preds.set(id, []);
  for (const e of edges) preds.get(e.to)?.push(e.from);
  const cache = new Map<string, number>();
  const depth = (id: string, seen: Set<string>): number => {
    const c = cache.get(id);
    if (c !== undefined) return c;
    if (seen.has(id)) return 0;
    seen.add(id);
    let d = 0;
    for (const p of preds.get(id) ?? []) d = Math.max(d, depth(p, new Set(seen)) + 1);
    cache.set(id, d);
    return d;
  };
  const out = new Map<string, number>();
  for (const id of ids) out.set(id, depth(id, new Set()));
  return out;
}

/** Map every node id to the nearest visible ancestor (itself if visible). Used
 *  to route machine-level flows to collapsed-group boxes in expandable mode. */
function visibleAncestor(
  nodes: GroupNode[],
  visible: Set<string>,
): (id: string) => string | null {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return (id: string) => {
    let cur: GroupNode | undefined = byId.get(id);
    while (cur) {
      if (visible.has(cur.id)) return cur.id;
      cur = cur.parentId ? byId.get(cur.parentId) : undefined;
    }
    return null;
  };
}

// ── Nested / expandable layout ────────────────────────────────────────────────

interface NestOpts {
  /** Expandable mode: only these group ids show their children; others collapse.
   *  Undefined → fully expanded (plain nested mode). */
  expanded?: Set<string>;
}

/** Recursive variable-size box packing: each expanded group is a container whose
 *  children are arranged left→right by flow-depth and stacked within a column. */
export function layoutNested(wb: Workbook, opts: NestOpts = {}): Laid {
  const nodes = parseNodes(wb);
  const byParent = new Map<string | null, GroupNode[]>();
  for (const n of nodes) {
    const k = n.parentId;
    if (!byParent.has(k)) byParent.set(k, []);
    byParent.get(k)!.push(n);
  }
  const roots = childrenOf(nodes, null);

  const isOpen = (n: GroupNode): boolean =>
    n.kind === "group" &&
    childrenOf(nodes, n.id).length > 0 &&
    (opts.expanded ? opts.expanded.has(n.id) : true);

  const sizeCache = new Map<string, { w: number; h: number }>();
  const size = (n: GroupNode): { w: number; h: number } => {
    const hit = sizeCache.get(n.id);
    if (hit) return hit;
    let box: { w: number; h: number };
    if (!isOpen(n)) {
      box = { w: LEAF_W, h: LEAF_H };
    } else {
      const kids = childrenOf(nodes, n.id);
      const edges = levelConnections(wb, n.id);
      const col = columnsOf(kids.map((k) => k.id), edges);
      const byCol = new Map<number, GroupNode[]>();
      for (const k of kids) {
        const c = col.get(k.id) ?? 0;
        if (!byCol.has(c)) byCol.set(c, []);
        byCol.get(c)!.push(k);
      }
      let contentW = 0;
      let contentH = 0;
      const cols = [...byCol.keys()].sort((a, b) => a - b);
      cols.forEach((c, i) => {
        const members = byCol.get(c)!;
        const colW = Math.max(...members.map((m) => size(m).w));
        const colH = members.reduce((acc, m) => acc + size(m).h, 0) + GAP_Y * (members.length - 1);
        contentW += colW + (i > 0 ? GAP_X : 0);
        contentH = Math.max(contentH, colH);
      });
      box = { w: contentW + 2 * PAD, h: contentH + HEADER + 2 * PAD };
    }
    sizeCache.set(n.id, box);
    return box;
  };

  const out: LaidNode[] = [];
  const place = (n: GroupNode, x: number, y: number, depth: number): void => {
    const { w, h } = size(n);
    const open = isOpen(n);
    out.push({
      id: n.id,
      parentId: n.parentId,
      kind: n.kind,
      level: n.level,
      label: n.label,
      depth,
      x,
      y,
      w,
      h,
      collapsed: n.kind === "group" && !open,
    });
    if (!open) return;
    const kids = childrenOf(nodes, n.id);
    const edges = levelConnections(wb, n.id);
    const col = columnsOf(kids.map((k) => k.id), edges);
    const byCol = new Map<number, GroupNode[]>();
    for (const k of kids) {
      const c = col.get(k.id) ?? 0;
      if (!byCol.has(c)) byCol.set(c, []);
      byCol.get(c)!.push(k);
    }
    const cols = [...byCol.keys()].sort((a, b) => a - b);
    let colX = x + PAD;
    for (const c of cols) {
      const members = byCol.get(c)!;
      const colW = Math.max(...members.map((m) => size(m).w));
      let cy = y + HEADER + PAD;
      for (const m of members) {
        const ms = size(m);
        place(m, colX + (colW - ms.w) / 2, cy, depth + 1);
        cy += ms.h + GAP_Y;
      }
      colX += colW + GAP_X;
    }
  };

  // Lay the roots out as columns of a virtual top container.
  let rx = PAD;
  let maxH = 0;
  for (const r of roots) {
    place(r, rx, PAD, 0);
    const sz = size(r);
    rx += sz.w + GAP_X;
    maxH = Math.max(maxH, sz.h);
  }

  return {
    nodes: out,
    edges: resolveEdges(wb, nodes, out, opts.expanded),
    width: rx,
    height: maxH + 2 * PAD,
  };
}

// ── Swimlanes-by-level ────────────────────────────────────────────────────────

/** Horizontal bands by depth; nodes ordered by a stable pre-order so subtrees
 *  cluster. Parent→child belonging is drawn by the renderer as connectors. */
export function layoutSwimlane(wb: Workbook): Laid {
  const nodes = parseNodes(wb);
  const BAND_H = 132;
  const CELL_W = LEAF_W + 28;
  // Pre-order traversal → a left-to-right ordering that keeps subtrees together.
  const order: { node: GroupNode; depth: number }[] = [];
  const walk = (parentId: string | null, depth: number): void => {
    for (const c of childrenOf(nodes, parentId)) {
      order.push({ node: c, depth });
      walk(c.id, depth + 1);
    }
  };
  walk(null, 0);

  // Within each depth band, assign sequential x in pre-order.
  const idxByDepth = new Map<number, number>();
  const out: LaidNode[] = [];
  for (const { node, depth } of order) {
    const i = idxByDepth.get(depth) ?? 0;
    idxByDepth.set(depth, i + 1);
    out.push({
      id: node.id,
      parentId: node.parentId,
      kind: node.kind,
      level: node.level,
      label: node.label,
      depth,
      x: PAD + i * CELL_W,
      y: PAD + depth * BAND_H,
      w: LEAF_W,
      h: LEAF_H,
      collapsed: false,
    });
  }
  const maxDepth = Math.max(0, ...out.map((n) => n.depth));
  const width = PAD + Math.max(1, ...[...idxByDepth.values()]) * CELL_W;
  return {
    nodes: out,
    edges: resolveEdges(wb, nodes, out, undefined),
    width,
    height: PAD + (maxDepth + 1) * BAND_H,
  };
}

// ── Edge resolution (machine flows → visible endpoints) ───────────────────────

function resolveEdges(
  wb: Workbook,
  nodes: GroupNode[],
  laid: LaidNode[],
  expanded: Set<string> | undefined,
): LaidEdge[] {
  const visible = new Set(laid.map((n) => n.id));
  const toVisible = visibleAncestor(nodes, visible);
  void expanded;
  const out: LaidEdge[] = [];
  const seen = new Set<string>();
  (wb.connections ?? []).forEach((row, i) => {
    const origFrom = s(row.from_node);
    const origTo = s(row.to_node);
    const from = toVisible(origFrom);
    const to = toVisible(origTo);
    if (!from || !to || from === to) return;
    const commodity = s(row.commodity_id, "—");
    const key = `${from}→${to}:${commodity}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ id: `e${i}`, from, to, origFrom, origTo, commodity });
  });
  return out;
}

/** Groups to expand BY DEFAULT when a model first loads.
 *
 *  Expands the tree breadth-first, one whole level at a time, while the visible
 *  node count stays within `budget`. Small models (green steel, steel) fall under
 *  budget and fully expand — unchanged behaviour. Large ones (the 248-machine
 *  petrochemical chain) stop a level or two down, so the canvas never tries to
 *  paint hundreds of machine boxes and their source-stream fan-out lines at once
 *  (which froze the browser). The ▦ Expand-all button still forces the full tree.
 *
 *  All-or-nothing per level keeps the result predictable: you never see one
 *  branch drilled deeper than its siblings on first load. */
export function defaultExpanded(wb: Workbook, budget = 120): Set<string> {
  const nodes = parseNodes(wb);
  const kids = new Map<string, GroupNode[]>();
  for (const n of nodes) {
    if (n.parentId === null) continue;
    (kids.get(n.parentId) ?? kids.set(n.parentId, []).get(n.parentId)!).push(n);
  }
  const hasChildren = (id: string) => (kids.get(id)?.length ?? 0) > 0;
  const roots = nodes.filter((n) => n.parentId === null);
  const expanded = new Set<string>();
  let visible = roots.length;
  let frontier = roots; // currently-shown nodes whose children are still hidden
  while (frontier.length) {
    const groups = frontier.filter((n) => n.kind === "group" && hasChildren(n.id));
    const added = groups.reduce((a, g) => a + (kids.get(g.id)?.length ?? 0), 0);
    if (groups.length === 0 || visible + added > budget) break;
    for (const g of groups) expanded.add(g.id);
    visible += added;
    frontier = groups.flatMap((g) => kids.get(g.id) ?? []);
  }
  return expanded;
}

/** Convenience: lay out for any mode. */
export function layoutFor(wb: Workbook, mode: MapMode, expanded?: Set<string>): Laid {
  if (mode === "swimlane") return layoutSwimlane(wb);
  if (mode === "expandable") return layoutNested(wb, { expanded });
  return layoutNested(wb);
}

/** One editable edge per `connections` row, resolved to the deepest VISIBLE
 *  endpoints (so a collapsed group still receives its descendants' links). Keeps
 *  `rowIndex`/`lag` so the editor can address and delete the exact row — unlike
 *  the read-only `Laid.edges`, which dedupes for display. */
export interface EditEdge {
  /** The connections-sheet row, or -1 when this is an AGGREGATE of several rows
   *  (many machine→machine links collapsed onto one level→level arrow). */
  rowIndex: number;
  from: string;
  to: string;
  commodity: string;
  lag: number;
  /** Per-provider annual flow bounds (null = unset). */
  maxFlow: number | null;
  minFlow: number | null;
  /** How many underlying connections this arrow represents (1 = a single link). */
  count: number;
}

/** A source stream: a commodity consumed by a facility but produced by none
 *  (a raw material / external input — iron ore, coal). `consumers` are the
 *  machine-node ids whose baseline technology consumes it. */
export interface SourceStream {
  id: string;
  consumers: string[];
}

/** Detect source streams: commodities that are a technology INPUT somewhere (or
 *  flagged purchasable) but never a technology OUTPUT — i.e. they must be
 *  supplied from outside the modelled chain. */
export function sourceStreams(wb: Workbook): SourceStream[] {
  const io = wb.io ?? [];
  const inputs = new Set<string>();
  const outputs = new Set<string>();
  const techInputs = new Map<string, string[]>();
  for (const r of io) {
    const target = s(r.target);
    if (!target) continue;
    if (s(r.role, "input") === "output") {
      outputs.add(target);
    } else {
      inputs.add(target);
      const tech = s(r.technology_id);
      let arr = techInputs.get(tech);
      if (!arr) techInputs.set(tech, (arr = []));
      arr.push(target);
    }
  }
  const isTrue = (v: unknown) => v === true || v === "true" || v === "TRUE" || v === 1;
  const candidates = new Set<string>(inputs);
  for (const c of wb.commodities ?? []) {
    const id = s(c.commodity_id);
    if (id && isTrue(c.purchasable)) candidates.add(id);
  }
  // Emissions (impacts) are not raw-material streams even if they appear as a
  // recipe input for accounting — exclude them from the sources band.
  const impacts = new Set((wb.impacts ?? []).map((r) => s(r.impact_id)).filter(Boolean));
  const sources = [...candidates].filter((c) => !outputs.has(c) && !impacts.has(c)).sort();

  // A machine can consume a stream via ANY feasible technology — its baseline or
  // a transition target (e.g. scrap is consumed only after switching to EAF).
  const transTargets = new Map<string, string[]>();
  for (const tr of wb.transitions ?? []) {
    const from = s(tr.from_technology);
    const to = s(tr.to_technology);
    if (!from || !to) continue;
    let arr = transTargets.get(from);
    if (!arr) transTargets.set(from, (arr = []));
    arr.push(to);
  }
  // machine/process id → baseline technology (machines for hierarchy models).
  const baseline = new Map<string, string>();
  for (const m of wb.machines ?? []) {
    const id = s(m.machine_id);
    if (id) baseline.set(id, s(m.baseline_technology));
  }
  for (const p of wb.processes ?? []) {
    const id = s(p.process_id);
    if (id && !baseline.has(id)) baseline.set(id, s(p.baseline_technology));
  }
  return sources.map((c) => {
    const consumers: string[] = [];
    for (const [id, tech] of baseline) {
      const techs = [tech, ...(transTargets.get(tech) ?? [])];
      if (techs.some((tk) => (techInputs.get(tk) ?? []).includes(c))) consumers.push(id);
    }
    return { id: c, consumers };
  });
}

/** Overlay manual positions on an auto-layout: move each leaf (machine or collapsed
 *  group) to its stored (x, y), then re-fit every expanded group box to the bounding
 *  box of its children (bottom-up). So moving a child redraws its ancestors' boxes. */
export function applyManualLayout(laid: Laid, positions: Map<string, { x: number; y: number }>): Laid {
  if (!positions.size) return laid;
  const nodes = laid.nodes.map((n) => ({ ...n }));
  for (const n of nodes) {
    const p = positions.get(n.id);
    if (p && (n.kind === "machine" || n.collapsed)) {
      n.x = p.x;
      n.y = p.y;
    }
  }
  const kidsByParent = new Map<string, LaidNode[]>();
  for (const n of nodes) {
    if (!n.parentId) continue;
    const b = kidsByParent.get(n.parentId);
    if (b) b.push(n);
    else kidsByParent.set(n.parentId, [n]);
  }
  // Deepest groups first, so a parent re-fits around children already re-fitted.
  for (const g of nodes.filter((n) => n.kind === "group" && !n.collapsed).sort((a, b) => b.depth - a.depth)) {
    const kids = kidsByParent.get(g.id);
    if (!kids || !kids.length) continue;
    const minX = Math.min(...kids.map((k) => k.x));
    const minY = Math.min(...kids.map((k) => k.y));
    const maxX = Math.max(...kids.map((k) => k.x + k.w));
    const maxY = Math.max(...kids.map((k) => k.y + k.h));
    g.x = minX - PAD;
    g.y = minY - HEADER - PAD;
    g.w = maxX - minX + 2 * PAD;
    g.h = maxY - minY + HEADER + 2 * PAD;
  }
  const minX = Math.min(0, ...nodes.map((n) => n.x));
  const minY = Math.min(0, ...nodes.map((n) => n.y));
  return {
    ...laid,
    nodes,
    width: Math.max(...nodes.map((n) => n.x + n.w)) - minX + PAD,
    height: Math.max(...nodes.map((n) => n.y + n.h)) - minY + PAD,
  };
}

export function editEdges(wb: Workbook, laid: LaidNode[], flowLevel: string | null = null): EditEdge[] {
  const nodes = parseNodes(wb);
  const visible = new Set(laid.map((n) => n.id));
  const toVisible = visibleAncestor(nodes, visible);
  const flow = (v: unknown): number | null =>
    v == null || String(v).trim() === "" ? null : Number(v);
  // Flow-aggregation level (independent of expand/collapse): roll an endpoint up to
  // its ancestor whose `level` === flowLevel, else leave it (it's already at/above
  // that level). null ⇒ "Component" (the machine itself).
  const levelOf = new Map(nodes.map((n) => [n.id, n.level]));
  const parentOf = new Map(nodes.map((n) => [n.id, n.parentId]));
  const atLevel = (id: string): string => {
    if (!flowLevel) return id;
    let cur: string | null = id;
    const seen = new Set<string>();
    while (cur && !seen.has(cur)) {
      if (levelOf.get(cur) === flowLevel) return cur;
      seen.add(cur);
      cur = parentOf.get(cur) ?? null;
    }
    return id;
  };
  // Map every connection onto the chosen flow level, then the nearest VISIBLE
  // endpoints, then aggregate by (from, to, commodity): at Component level each
  // arrow is one editable link; rolled up, the links between two boxes fold into a
  // single level→level arrow (display-only, with a count).
  const groups = new Map<string, EditEdge[]>();
  (wb.connections ?? []).forEach((row, rowIndex) => {
    const from = toVisible(atLevel(s(row.from_node)));
    const to = toVisible(atLevel(s(row.to_node)));
    if (!from || !to || from === to) return;
    const commodity = s(row.commodity_id, "—");
    const e: EditEdge = {
      rowIndex,
      from,
      to,
      commodity,
      lag: num(row.lag_years),
      maxFlow: flow(row.max_flow),
      minFlow: flow(row.min_flow),
      count: 1,
    };
    const key = `${from}|${to}|${commodity}`;
    const bucket = groups.get(key);
    if (bucket) bucket.push(e);
    else groups.set(key, [e]);
  });
  const out: EditEdge[] = [];
  for (const bucket of groups.values()) {
    if (bucket.length === 1) out.push(bucket[0]); // a single link — stays editable
    else out.push({ ...bucket[0], rowIndex: -1, lag: 0, maxFlow: null, minFlow: null, count: bucket.length });
  }
  return out;
}
