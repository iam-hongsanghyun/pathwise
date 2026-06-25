// Pure layout for the multi-level result map: turn the node hierarchy
// (country → company → facility → asset) into absolutely-positioned boxes for
// three render modes — nested containers, swimlanes-by-level, and an expandable
// (collapsible) nested view. No React, no I/O; mirrors the .topo-* sizing.

import { childrenOf, levelConnections, parseNodes, type GroupNode } from "./groupGraph";
import type { Workbook } from "../types";

export type MapMode = "nested" | "swimlane" | "expandable";

/** Flow direction of the auto-layout: "h" = left→right (depth grows in x,
 *  siblings stack in y); "v" = top→bottom (depth grows in y, siblings spread
 *  in x). The title strip stays at the TOP of every box in both. */
export type Orientation = "h" | "v";

/** A positioned box for any node (group container or asset leaf). */
export interface LaidNode {
  id: string;
  parentId: string | null;
  kind: "group" | "asset";
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

/** A asset→asset flow to draw, resolved to the deepest VISIBLE endpoints.
 *  `origFrom`/`origTo` keep the real connection endpoints so the per-year
 *  overlay (keyed by the actual asset ids) can be looked up even when the
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
const GAP_X = 96; // between columns inside a container (room for the port-side flow labels)
const GAP_Y = 60; // between stacked siblings (room for the port-side flow labels)
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
 *  to route asset-level flows to collapsed-group boxes in expandable mode. */
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
  /** Flow direction (default "h"). */
  orientation?: Orientation;
}

/** Recursive variable-size box packing: each expanded group is a container whose
 *  children are arranged by flow-depth along the primary axis (x for "h", y for
 *  "v") and spread along the secondary axis within a depth bucket. */
export function layoutNested(wb: Workbook, opts: NestOpts = {}): Laid {
  const horiz = (opts.orientation ?? "h") === "h";
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
      // `along` = total extent along the depth axis; `across` = max across it.
      const buckets = [...byCol.keys()].sort((a, b) => a - b).map((c) => byCol.get(c)!);
      let along = 0;
      let across = 0;
      buckets.forEach((members, i) => {
        if (horiz) {
          const colW = Math.max(...members.map((m) => size(m).w));
          const colH = members.reduce((acc, m) => acc + size(m).h, 0) + GAP_Y * (members.length - 1);
          along += colW + (i > 0 ? GAP_X : 0);
          across = Math.max(across, colH);
        } else {
          const rowH = Math.max(...members.map((m) => size(m).h));
          const rowW = members.reduce((acc, m) => acc + size(m).w, 0) + GAP_X * (members.length - 1);
          along += rowH + (i > 0 ? GAP_Y : 0);
          across = Math.max(across, rowW);
        }
      });
      box = horiz
        ? { w: along + 2 * PAD, h: across + HEADER + 2 * PAD }
        : { w: across + 2 * PAD, h: along + HEADER + 2 * PAD };
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
    const buckets = [...byCol.keys()].sort((a, b) => a - b).map((c) => byCol.get(c)!);
    if (horiz) {
      // Depth buckets are columns advancing in x; members stack down each column.
      let colX = x + PAD;
      for (const members of buckets) {
        const colW = Math.max(...members.map((m) => size(m).w));
        let cy = y + HEADER + PAD;
        for (const m of members) {
          const ms = size(m);
          place(m, colX + (colW - ms.w) / 2, cy, depth + 1);
          cy += ms.h + GAP_Y;
        }
        colX += colW + GAP_X;
      }
    } else {
      // Depth buckets are rows advancing in y; members spread right across each row.
      let rowY = y + HEADER + PAD;
      for (const members of buckets) {
        const rowH = Math.max(...members.map((m) => size(m).h));
        let cx = x + PAD;
        for (const m of members) {
          const ms = size(m);
          place(m, cx, rowY + (rowH - ms.h) / 2, depth + 1);
          cx += ms.w + GAP_X;
        }
        rowY += rowH + GAP_Y;
      }
    }
  };

  // Lay the roots out along the primary axis of a virtual top container.
  if (horiz) {
    let rx = PAD;
    let maxH = 0;
    for (const r of roots) {
      place(r, rx, PAD, 0);
      const sz = size(r);
      rx += sz.w + GAP_X;
      maxH = Math.max(maxH, sz.h);
    }
    return { nodes: out, edges: resolveEdges(wb, nodes, out), width: rx, height: maxH + 2 * PAD };
  }
  let ry = PAD;
  let maxW = 0;
  for (const r of roots) {
    place(r, PAD, ry, 0);
    const sz = size(r);
    ry += sz.h + GAP_Y;
    maxW = Math.max(maxW, sz.w);
  }
  return { nodes: out, edges: resolveEdges(wb, nodes, out), width: maxW + 2 * PAD, height: ry };
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
    edges: resolveEdges(wb, nodes, out),
    width,
    height: PAD + (maxDepth + 1) * BAND_H,
  };
}

// ── Edge resolution (asset flows → visible endpoints) ───────────────────────

function resolveEdges(wb: Workbook, nodes: GroupNode[], laid: LaidNode[]): LaidEdge[] {
  const visible = new Set(laid.map((n) => n.id));
  const toVisible = visibleAncestor(nodes, visible);
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
 *  budget and fully expand — unchanged behaviour. Large ones (the 248-asset
 *  petrochemical chain) stop a level or two down, so the canvas never tries to
 *  paint hundreds of asset boxes and their source-stream fan-out lines at once
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

/** Convenience: lay out for any mode. `orientation` ("h" default / "v") sets the
 *  flow direction for the nested layouts (swimlane is always banded by depth). */
export function layoutFor(
  wb: Workbook,
  mode: MapMode,
  expanded?: Set<string>,
  orientation: Orientation = "h",
): Laid {
  if (mode === "swimlane") return layoutSwimlane(wb);
  if (mode === "expandable") return layoutNested(wb, { expanded, orientation });
  return layoutNested(wb, { orientation });
}

/** One editable edge per `connections` row, resolved to the deepest VISIBLE
 *  endpoints (so a collapsed group still receives its descendants' links). Keeps
 *  `rowIndex`/`lag` so the editor can address and delete the exact row — unlike
 *  the read-only `Laid.edges`, which dedupes for display. */
export interface EditEdge {
  /** The connections-sheet row, or -1 when this is an AGGREGATE of several rows
   *  (many asset→asset links, or several commodities, folded onto one arrow). */
  rowIndex: number;
  from: string;
  to: string;
  /** Primary commodity (the first, for the single-link edit form). */
  commodity: string;
  /** Every distinct commodity carried between these two endpoints (one arrow now
   *  aggregates ALL commodities for a from→to pair). */
  commodities: string[];
  lag: number;
  /** Per-provider annual flow bounds (null = unset). */
  maxFlow: number | null;
  minFlow: number | null;
  /** How many underlying connections this arrow represents (1 = a single link). */
  count: number;
}

/** A source stream: a commodity consumed by a facility but produced by none
 *  (a raw material / external input — iron ore, coal). `consumers` are the
 *  asset-node ids whose baseline technology consumes it. */
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

  // A asset can consume a stream via ANY feasible technology — its baseline or
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
  // asset/process id → baseline technology (assets for hierarchy models).
  const baseline = new Map<string, string>();
  for (const m of wb.assets ?? []) {
    const id = s(m.asset_id);
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

export function editEdges(wb: Workbook, laid: LaidNode[], flowLevel: string | null = null): EditEdge[] {
  const nodes = parseNodes(wb);
  const visible = new Set(laid.map((n) => n.id));
  const toVisible = visibleAncestor(nodes, visible);
  const flow = (v: unknown): number | null =>
    v == null || String(v).trim() === "" ? null : Number(v);
  // Flow-aggregation level (independent of expand/collapse): roll an endpoint up to
  // its ancestor whose `level` === flowLevel, else leave it (it's already at/above
  // that level). null ⇒ "Component" (the asset itself).
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
  // Ancestor chain [id, parent, …, root].
  const chainUp = (id: string): string[] => {
    const out: string[] = [];
    let cur: string | null = id;
    const seen = new Set<string>();
    while (cur && !seen.has(cur)) {
      out.push(cur);
      seen.add(cur);
      cur = parentOf.get(cur) ?? null;
    }
    return out;
  };
  // The two endpoints rolled up to the level where they first DIVERGE: the
  // children of their lowest common ancestor that contain each side. So a flow
  // between two assets in different companies is drawn company→company; between
  // two companies in different countries, country→country. Returns null when one
  // is an ancestor of the other or the trees are disjoint.
  const divergingEndpoints = (from: string, to: string): [string, string] | null => {
    if (from === to) return null;
    const af = chainUp(from);
    const at = chainUp(to);
    const setT = new Set(at);
    let lca: string | null = null;
    for (const a of af) if (setT.has(a)) { lca = a; break; }
    if (!lca || lca === from || lca === to) return null;
    const childOnSide = (chain: string[]): string | null => {
      let prev: string | null = null;
      for (const a of chain) { if (a === lca) return prev; prev = a; }
      return null;
    };
    const cf = childOnSide(af);
    const ct = childOnSide(at);
    return cf && ct ? [cf, ct] : null;
  };
  // Resolve one connection's drawn endpoints for the current flow level:
  //   • a level  → that level if the two sides sit in DIFFERENT level-groups;
  //                otherwise (an intra-group link) fall back to the diverging
  //                level so it is still shown rather than dropped. The top
  //                "Value Chain" level therefore draws every link at its natural
  //                diverging point (children of the lowest common ancestor);
  //   • null     → the assets themselves (Component).
  const endpointsFor = (rawFrom: string, rawTo: string): [string | null, string | null] => {
    if (flowLevel) {
      const fx = atLevel(rawFrom);
      const tx = atLevel(rawTo);
      if (fx !== tx) return [toVisible(fx), toVisible(tx)];
      const dv = divergingEndpoints(rawFrom, rawTo);
      return dv ? [toVisible(dv[0]), toVisible(dv[1])] : [null, null];
    }
    return [toVisible(rawFrom), toVisible(rawTo)];
  };
  // Map every connection onto its drawn endpoints, then aggregate by (from, to)
  // — ALL commodities between the same two boxes fold onto ONE arrow that lists
  // each flow's name. A single underlying link stays editable; anything folded
  // (several links, or several commodities) becomes a display-only arrow.
  const groups = new Map<string, EditEdge[]>();
  (wb.connections ?? []).forEach((row, rowIndex) => {
    const [from, to] = endpointsFor(s(row.from_node), s(row.to_node));
    if (!from || !to || from === to) return;
    const commodity = s(row.commodity_id, "—");
    const e: EditEdge = {
      rowIndex,
      from,
      to,
      commodity,
      commodities: [commodity],
      lag: num(row.lag_years),
      maxFlow: flow(row.max_flow),
      minFlow: flow(row.min_flow),
      count: 1,
    };
    const key = `${from}|${to}`;
    const bucket = groups.get(key);
    if (bucket) bucket.push(e);
    else groups.set(key, [e]);
  });
  const out: EditEdge[] = [];
  for (const bucket of groups.values()) {
    const commodities = [...new Set(bucket.map((e) => e.commodity))];
    if (bucket.length === 1) {
      out.push({ ...bucket[0], commodities }); // a single link — stays editable
    } else {
      out.push({ ...bucket[0], rowIndex: -1, lag: 0, maxFlow: null, minFlow: null, count: bucket.length, commodities });
    }
  }
  return out;
}

// ── Orthogonal obstacle-avoiding routing ──────────────────────────────────────

export interface Pt {
  x: number;
  y: number;
}
export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

const ROUTE_EPS = 0.5;

/** Does the axis-aligned segment (ax,ay)->(bx,by) cross any obstacle interior? */
function segHitsAny(ax: number, ay: number, bx: number, by: number, obstacles: Box[]): boolean {
  for (const o of obstacles) {
    if (Math.abs(ax - bx) < ROUTE_EPS) {
      if (ax > o.x + ROUTE_EPS && ax < o.x + o.w - ROUTE_EPS) {
        const lo = Math.min(ay, by);
        const hi = Math.max(ay, by);
        if (hi > o.y + ROUTE_EPS && lo < o.y + o.h - ROUTE_EPS) return true;
      }
    } else if (ay > o.y + ROUTE_EPS && ay < o.y + o.h - ROUTE_EPS) {
      const lo = Math.min(ax, bx);
      const hi = Math.max(ax, bx);
      if (hi > o.x + ROUTE_EPS && lo < o.x + o.w - ROUTE_EPS) return true;
    }
  }
  return false;
}

/** Drop collinear midpoints + duplicate points from a polyline. */
function simplifyCollinear(pts: Pt[]): Pt[] {
  const out: Pt[] = [];
  for (let n = 0; n < pts.length; n++) {
    const a = out[out.length - 1];
    const b = pts[n];
    if (n > 0 && n < pts.length - 1) {
      const c = pts[n + 1];
      const collinear = (a.x === b.x && b.x === c.x) || (a.y === b.y && b.y === c.y);
      if (collinear) continue;
    }
    if (!a || Math.abs(a.x - b.x) > ROUTE_EPS || Math.abs(a.y - b.y) > ROUTE_EPS) out.push(b);
  }
  return out;
}

/** Shortest orthogonal (right-angle) path from `p1` to `p2` that does not cross any
 *  obstacle rectangle, kept within `bounds`. Returns the polyline (incl. endpoints)
 *  or null if no route exists.
 *
 *  Algorithm: a Hanan grid (candidate lines just outside each obstacle edge, plus
 *  the endpoints) → A* over the grid, minimising path length with a small per-turn
 *  penalty so it prefers straight, few-bend routes. Pure (no React / DOM).
 *
 *  Algorithm:
 *    $$\min_{\pi}\; \sum_i \lVert v_{i+1}-v_i\rVert_1 + \lambda\, t(\pi)$$
 *    where $t(\pi)$ counts direction changes and $\lambda$ is `turnPenalty`.
 *  ASCII: minimise total Manhattan length + turnPenalty × (number of bends).
 */
export function routeOrthogonal(
  p1: Pt,
  p2: Pt,
  obstacles: Box[],
  bounds: Box,
  opts: { margin?: number; turnPenalty?: number; extraXs?: number[]; extraYs?: number[] } = {},
): Pt[] | null {
  const M = opts.margin ?? 8;
  const TP = opts.turnPenalty ?? 18;
  const EPS = ROUTE_EPS;
  const bx0 = bounds.x + 2;
  const bx1 = bounds.x + bounds.w - 2;
  const by0 = bounds.y + 2;
  const by1 = bounds.y + bounds.h - 2;
  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
  // Candidate coordinate lines: endpoints + a margin line each side of every box.
  const xsSet = new Set<number>([p1.x, p2.x]);
  const ysSet = new Set<number>([p1.y, p2.y]);
  for (const o of obstacles) {
    xsSet.add(clamp(o.x - M, bx0, bx1));
    xsSet.add(clamp(o.x + o.w + M, bx0, bx1));
    ysSet.add(clamp(o.y - M, by0, by1));
    ysSet.add(clamp(o.y + o.h + M, by0, by1));
  }
  // Injected candidate lines (stub ends + the near inter-box gutter midline) so
  // the cross-over bend lands in the near gap, not the far container wall.
  for (const v of opts.extraXs ?? []) xsSet.add(clamp(v, bx0, bx1));
  for (const v of opts.extraYs ?? []) ysSet.add(clamp(v, by0, by1));
  const xs = [...xsSet].sort((a, b) => a - b);
  const ys = [...ysSet].sort((a, b) => a - b);
  const nx = xs.length;
  const ny = ys.length;
  const inObstacle = (x: number, y: number) =>
    obstacles.some((o) => x > o.x + EPS && x < o.x + o.w - EPS && y > o.y + EPS && y < o.y + o.h - EPS);
  const segHits = (ax: number, ay: number, bx: number, by: number) => segHitsAny(ax, ay, bx, by, obstacles);
  const ix = new Map(xs.map((v, i) => [v, i]));
  const iy = new Map(ys.map((v, i) => [v, i]));
  const si = ix.get(p1.x);
  const sj = iy.get(p1.y);
  const gi = ix.get(p2.x);
  const gj = iy.get(p2.y);
  if (si == null || sj == null || gi == null || gj == null) return null;
  // A* state = (i, j, dir): dir 0=horizontal, 1=vertical, 2=none(start).
  const key = (i: number, j: number, d: number) => (i * ny + j) * 3 + d;
  const best = new Map<number, number>();
  const came = new Map<number, number>();
  const h = (i: number, j: number) => Math.abs(xs[i] - p2.x) + Math.abs(ys[j] - p2.y);
  type Node = { i: number; j: number; d: number; g: number; f: number };
  const open: Node[] = [{ i: si, j: sj, d: 2, g: 0, f: h(si, sj) }];
  best.set(key(si, sj, 2), 0);
  const popMin = () => {
    let m = 0;
    for (let k = 1; k < open.length; k++) if (open[k].f < open[m].f) m = k;
    return open.splice(m, 1)[0];
  };
  let goal: Node | null = null;
  while (open.length) {
    const cur = popMin();
    if (cur.i === gi && cur.j === gj) { goal = cur; break; }
    if (cur.g > (best.get(key(cur.i, cur.j, cur.d)) ?? Infinity)) continue;
    const steps = [
      { di: 1, dj: 0, dir: 0 },
      { di: -1, dj: 0, dir: 0 },
      { di: 0, dj: 1, dir: 1 },
      { di: 0, dj: -1, dir: 1 },
    ];
    for (const s2 of steps) {
      const ni = cur.i + s2.di;
      const nj = cur.j + s2.dj;
      if (ni < 0 || ni >= nx || nj < 0 || nj >= ny) continue;
      const ax = xs[cur.i];
      const ay = ys[cur.j];
      const bx = xs[ni];
      const by = ys[nj];
      if (inObstacle(bx, by)) continue;
      if (segHits(ax, ay, bx, by)) continue;
      const step = Math.abs(bx - ax) + Math.abs(by - ay);
      const turn = cur.d !== 2 && cur.d !== s2.dir ? TP : 0;
      const ng = cur.g + step + turn;
      const nk = key(ni, nj, s2.dir);
      if (ng < (best.get(nk) ?? Infinity)) {
        best.set(nk, ng);
        came.set(nk, key(cur.i, cur.j, cur.d));
        open.push({ i: ni, j: nj, d: s2.dir, g: ng, f: ng + h(ni, nj) });
      }
    }
  }
  if (!goal) return null;
  // Reconstruct, then drop collinear midpoints.
  const pts: Pt[] = [];
  let k: number | undefined = key(goal.i, goal.j, goal.d);
  while (k != null) {
    const d = k % 3;
    const ij = (k - d) / 3;
    const j = ij % ny;
    const i = (ij - j) / ny;
    pts.push({ x: xs[i], y: ys[j] });
    k = came.get(k);
  }
  pts.reverse();
  return simplifyCollinear(pts);
}

/** Orthogonal route with guaranteed perpendicular exit/entry stubs. Wraps
 *  {@link routeOrthogonal}: the A* runs only between the two stub ends (e1, e2),
 *  pushed STUB px off each port along its outward normal, so the line leaves /
 *  enters perpendicular (never hugs the outline) and there is clear straight
 *  space at each port for a label. The near inter-box gutter midline is injected
 *  so the bend lands in the nearest gap, not the far container wall. */
export function routeWithStubs(
  p1: Pt,
  p2: Pt,
  obstacles: Box[],
  bounds: Box,
  orientation: Orientation,
  srcBox: Box,
  dstBox: Box,
  opts: { margin?: number; turnPenalty?: number; stub?: number; labelClearance?: number } = {},
): Pt[] | null {
  const horiz = orientation === "h";
  const M = opts.margin ?? 8;
  if (Math.abs(p1.x - p2.x) < ROUTE_EPS && Math.abs(p1.y - p2.y) < ROUTE_EPS) return [p1, p2];

  const labelClear = opts.labelClearance ?? 20;
  const floor = horiz ? Math.max(PAD, GAP_X / 2) : Math.max(12, GAP_Y / 2 + 2);
  const Sreq = Math.max(opts.stub ?? floor, M + labelClear);

  const nx = horiz ? 1 : 0;
  const ny = horiz ? 0 : 1;
  const bLoX = bounds.x + 2;
  const bHiX = bounds.x + bounds.w - 2;
  const bLoY = bounds.y + 2;
  const bHiY = bounds.y + bounds.h - 2;
  const roomAlong = (px: number, py: number, sign: number) =>
    horiz ? (sign > 0 ? bHiX - px : px - bLoX) : sign > 0 ? bHiY - py : py - bLoY;
  // Largest clear stub length in [M, want] that stays in bounds + clears obstacles.
  const clampStub = (px: number, py: number, sign: number, want: number): number => {
    let s = Math.min(want, Math.max(M, roomAlong(px, py, sign)));
    if (segHitsAny(px, py, px + nx * sign * s, py + ny * sign * s, obstacles)) {
      let found = M;
      for (let t = s; t >= M; t -= 2) {
        if (!segHitsAny(px, py, px + nx * sign * t, py + ny * sign * t, obstacles)) { found = t; break; }
      }
      s = found;
    }
    return s;
  };
  const s1 = clampStub(p1.x, p1.y, +1, Sreq);
  const s2 = clampStub(p2.x, p2.y, -1, Sreq);
  const e1: Pt = { x: p1.x + nx * s1, y: p1.y + ny * s1 };
  const e2: Pt = { x: p2.x - nx * s2, y: p2.y - ny * s2 };

  const extraXs: number[] = [];
  const extraYs: number[] = [];
  if (horiz) {
    const gx =
      srcBox.x + srcBox.w <= dstBox.x
        ? (srcBox.x + srcBox.w + dstBox.x) / 2
        : (dstBox.x + dstBox.w + srcBox.x) / 2;
    extraXs.push(gx, e1.x, e2.x);
    extraYs.push(e1.y, e2.y);
  } else {
    const gy =
      srcBox.y + srcBox.h <= dstBox.y
        ? (srcBox.y + srcBox.h + dstBox.y) / 2
        : (dstBox.y + dstBox.h + srcBox.y) / 2;
    extraYs.push(gy, e1.y, e2.y);
    extraXs.push(e1.x, e2.x);
  }

  const mid = routeOrthogonal(e1, e2, obstacles, bounds, {
    margin: M,
    turnPenalty: opts.turnPenalty ?? 18,
    extraXs,
    extraYs,
  });
  let poly: Pt[];
  if (mid && mid.length >= 2) {
    poly = [p1, e1, ...mid.slice(1, mid.length - 1), e2, p2];
  } else if (horiz) {
    const gx = extraXs[0];
    poly = [p1, e1, { x: gx, y: e1.y }, { x: gx, y: e2.y }, e2, p2];
  } else {
    const gy = extraYs[0];
    poly = [p1, e1, { x: e1.x, y: gy }, { x: e2.x, y: gy }, e2, p2];
  }
  return simplifyCollinear(poly);
}
