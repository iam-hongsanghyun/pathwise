// Helpers for the Fleet designer. The transport layer is SEPARATE from the facility
// / network `nodes` tree: fleets live in their own registry — `fleet_groups`
// (the alliance→company→… ownership tree) + `fleet` rows (group = a fleet_groups
// id). The RIGHT rail just mirrors the facility `nodes` so a user can pull ports
// onto the map. Adding a fleet NEVER touches `nodes`.

import type { GroupNode } from "../../lib/groupGraph";
import type { TreeNode } from "../tree/types";
import type { Row, Workbook } from "../../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const has = (v: unknown): boolean => v != null && v !== "";

/** Fleet id of a `fleet` row — `fleet_id` (canonical) or `archetype` (legacy). */
export const fleetId = (r: Row): string => s(r.fleet_id) || s(r.archetype);

/** Node id → {lon,lat} for every facility node carrying coordinates (a port). */
export function buildCoordMap(wb: Workbook): Map<string, { lon: number; lat: number }> {
  const m = new Map<string, { lon: number; lat: number }>();
  for (const r of wb.nodes ?? [])
    if (has(r.lon) && has(r.lat)) m.set(s(r.node_id), { lon: Number(r.lon), lat: Number(r.lat) });
  return m;
}

export interface FleetGroup {
  id: string;
  parentId: string | null;
  label: string;
  level: string;
}

/** The fleet-ownership groups (the transport layer's own hierarchy). */
export function parseFleetGroups(wb: Workbook): FleetGroup[] {
  const seen = new Set<string>();
  const out: FleetGroup[] = [];
  for (const r of wb.fleet_groups ?? []) {
    const id = s(r.group_id);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const parentId = s(r.parent_id) || null;
    out.push({ id, parentId: parentId === id ? null : parentId, label: s(r.label) || id, level: s(r.level) });
  }
  return out;
}

/** LEFT rail: the fleet registry — ownership groups (nested) with fleets as leaves. */
export function fleetRegistryTree(groups: FleetGroup[], fleets: Row[]): TreeNode[] {
  const hasChild = (gid: string) => groups.some((g) => g.parentId === gid) || fleets.some((f) => s(f.group) === gid);
  const out: TreeNode[] = [];
  for (const g of groups)
    out.push({ id: g.id, parentId: g.parentId, kind: "group", label: g.label, level: g.level || undefined, hasChildren: hasChild(g.id), droppable: true });
  for (const f of fleets) {
    const id = fleetId(f);
    out.push({ id, parentId: s(f.group) || null, kind: "asset", label: s(f.label) || id, level: `fleet · ${s(f.mode) || "—"}`, hasChildren: false });
  }
  return out;
}

/** RIGHT rail: the facility `nodes` hierarchy (ports flagged) — a reference to pull
 *  ports/assets onto the map. */
export function facilityTree(nodes: GroupNode[], coord: Map<string, { lon: number; lat: number }>): TreeNode[] {
  const childCount = new Map<string | null, number>();
  for (const nd of nodes) childCount.set(nd.parentId, (childCount.get(nd.parentId) ?? 0) + 1);
  return nodes.map((nd) => ({
    id: nd.id,
    parentId: nd.parentId,
    kind: nd.kind === "asset" ? "asset" : "group",
    label: nd.label,
    level: coord.has(nd.id) ? "port" : nd.level || undefined,
    hasChildren: (childCount.get(nd.id) ?? 0) > 0,
    droppable: nd.kind !== "asset",
  }));
}

// ── Routes = physicalised network flow links ──────────────────────
// A network `link` (from_node → to_node carrying a flow) is a VIRTUAL
// stream flow — "teleportation": free + instant. It becomes a PHYSICAL route once its
// two endpoints carry a location AND it is given physical info (mode/fleet). The TOP
// of the right rail lists these grouped by stream; the BOTTOM lets a user drag an
// endpoint onto the map to give it a location.

/** dataTransfer MIME used when dragging a Facility endpoint onto the map to place it. */
export const NODE_DRAG_TYPE = "application/x-pathwise-node";

const slug = (v: string): string => v.replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");

/** Stable `routes`/`fleet_routes` process key for a (from, to, flow) link. */
export const routeProc = (from: string, to: string, flow: string): string =>
  `r_${slug(from)}__${slug(to)}__${slug(flow)}`;

/** A directed stream flow between two nodes (from the hierarchy `links` or the
 *  flat `edges`), deduped by (from, to, flow). */
export interface StreamLink {
  from: string;
  to: string;
  flow: string;
}
export function parseLinks(wb: Workbook): StreamLink[] {
  const out: StreamLink[] = [];
  const seen = new Set<string>();
  const add = (from: string, to: string, flow: string) => {
    if (!from || !to || from === to) return;
    const k = `${from}|${to}|${flow}`;
    if (seen.has(k)) return;
    seen.add(k);
    out.push({ from, to, flow });
  };
  for (const r of wb.links ?? []) add(s(r.from_node), s(r.to_node), s(r.flow_id));
  for (const r of wb.edges ?? []) add(s(r.from_process), s(r.to_process), s(r.flow_id));
  return out;
}

/** One route leaf: a physicalised route row, or a located link ready to become one. */
export interface RouteLeaf {
  proc: string;
  from: string;
  to: string;
  flow: string;
  mode: string;
  /** true = a real `routes` row exists; false = a located link candidate. */
  physical: boolean;
}

/** All route leaves: every existing `routes` row, plus every located `link` that
 *  doesn't yet have one (a candidate the user can physicalise). */
export function buildRouteLeaves(
  links: StreamLink[],
  routesRows: Row[],
  coord: Map<string, { lon: number; lat: number }>,
): RouteLeaf[] {
  const leaves: RouteLeaf[] = [];
  const byProc = new Set<string>();
  // Dedup a link candidate against an existing route row that already covers
  // the same (from, to, flow) — even if that row's process id doesn't follow
  // the routeProc convention (e.g. an imported example using its own ids).
  const byTriple = new Set<string>();
  const triple = (from: string, to: string, flow: string) => `${from}\x1f${to}\x1f${flow}`;
  for (const r of routesRows) {
    const proc = s(r.process);
    if (!proc || byProc.has(proc)) continue;
    byProc.add(proc);
    const from = s(r.from_node);
    const to = s(r.to_node);
    const flow = s(r.flow);
    byTriple.add(triple(from, to, flow));
    leaves.push({ proc, from, to, flow, mode: s(r.mode) || "sea", physical: true });
  }
  for (const c of links) {
    if (!coord.has(c.from) || !coord.has(c.to)) continue;
    if (byTriple.has(triple(c.from, c.to, c.flow))) continue;
    const proc = routeProc(c.from, c.to, c.flow);
    if (byProc.has(proc)) continue;
    byProc.add(proc);
    leaves.push({ proc, from: c.from, to: c.to, flow: c.flow, mode: "", physical: false });
  }
  return leaves;
}

/** TOP rail tree: streams (flow) → located link leaves. */
export function routeTree(leaves: RouteLeaf[], labelOf: (id: string) => string): TreeNode[] {
  const groups = new Map<string, RouteLeaf[]>();
  for (const l of leaves) {
    const key = l.flow || "";
    (groups.get(key) ?? groups.set(key, []).get(key)!).push(l);
  }
  const out: TreeNode[] = [];
  for (const [flow, ls] of [...groups.entries()].sort((a, b) => (a[0] || "~").localeCompare(b[0] || "~"))) {
    const gid = `stream::${flow}`;
    out.push({ id: gid, parentId: null, kind: "group", label: flow || "Direct routes", level: `flow · ${ls.length}`, hasChildren: true, droppable: false });
    for (const l of ls)
      out.push({ id: l.proc, parentId: gid, kind: "asset", label: `${labelOf(l.from)} → ${labelOf(l.to)}`, level: l.physical ? l.mode || "route" : "physicalise →", hasChildren: false });
  }
  return out;
}

/** BOTTOM rail: distinct link endpoints to place on the map (unplaced first). */
export interface Endpoint {
  id: string;
  label: string;
  located: boolean;
}
export function endpointList(
  links: StreamLink[],
  labelOf: (id: string) => string,
  coord: Map<string, { lon: number; lat: number }>,
): Endpoint[] {
  const ids = new Set<string>();
  for (const c of links) {
    ids.add(c.from);
    ids.add(c.to);
  }
  return [...ids]
    .map((id) => ({ id, label: labelOf(id), located: coord.has(id) }))
    .sort((a, b) => Number(a.located) - Number(b.located) || a.label.localeCompare(b.label));
}
