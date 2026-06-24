// Helpers for the Fleet designer. The transport layer is SEPARATE from the facility
// / value-chain `nodes` tree: fleets live in their own registry — `fleet_groups`
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
    out.push({ id, parentId: s(f.group) || null, kind: "machine", label: s(f.label) || id, level: `fleet · ${s(f.mode) || "—"}`, hasChildren: false });
  }
  return out;
}

/** RIGHT rail: the facility `nodes` hierarchy (ports flagged) — a reference to pull
 *  ports/machines onto the map. */
export function facilityTree(nodes: GroupNode[], coord: Map<string, { lon: number; lat: number }>): TreeNode[] {
  const childCount = new Map<string | null, number>();
  for (const nd of nodes) childCount.set(nd.parentId, (childCount.get(nd.parentId) ?? 0) + 1);
  return nodes.map((nd) => ({
    id: nd.id,
    parentId: nd.parentId,
    kind: nd.kind === "machine" ? "machine" : "group",
    label: nd.label,
    level: coord.has(nd.id) ? "port" : nd.level || undefined,
    hasChildren: (childCount.get(nd.id) ?? 0) > 0,
    droppable: nd.kind !== "machine",
  }));
}
