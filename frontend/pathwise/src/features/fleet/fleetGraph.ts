// Pure helpers for the Fleet designer — kept out of the view so the strict
// LEFT=fleets / RIGHT=facilities split is unit-testable. A FLEET is a node whose id
// has a `fleet` row; a PORT is a node carrying lon/lat. The split is by SUBTREE
// membership, NOT node kind: the left tree keeps only subtrees that contain a fleet
// (and hides ports/other machines); the right tree hides fleet leaves (groups +
// ports/facilities remain). A shared ancestor group may appear in both (it is a
// container) — but a fleet leaf never appears right and a port leaf never left.

import type { GroupNode } from "../../lib/groupGraph";
import type { TreeNode } from "../tree/types";
import type { Row, Workbook } from "../../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const has = (v: unknown): boolean => v != null && v !== "";

/** Fleet id of a `fleet` row — `fleet_id` (canonical) or `archetype` (legacy). */
export const fleetId = (r: Row): string => s(r.fleet_id) || s(r.archetype);

/** Node id → {lon,lat} for every node that carries coordinates (a port). parseNodes
 *  drops lon/lat, so read them straight from the raw `nodes` rows. */
export function buildCoordMap(wb: Workbook): Map<string, { lon: number; lat: number }> {
  const m = new Map<string, { lon: number; lat: number }>();
  for (const r of wb.nodes ?? [])
    if (has(r.lon) && has(r.lat)) m.set(s(r.node_id), { lon: Number(r.lon), lat: Number(r.lat) });
  return m;
}

/** parentId → children, preserving order. */
export function childrenIndex(nodes: GroupNode[]): Map<string | null, GroupNode[]> {
  const idx = new Map<string | null, GroupNode[]>();
  for (const nd of nodes) {
    const arr = idx.get(nd.parentId) ?? [];
    arr.push(nd);
    idx.set(nd.parentId, arr);
  }
  return idx;
}

/** True if `id` or any descendant satisfies `pred` (memoised over one call). */
function makeSubtreeContains(idx: Map<string | null, GroupNode[]>, pred: (id: string) => boolean) {
  const memo = new Map<string, boolean>();
  const visit = (id: string): boolean => {
    const cached = memo.get(id);
    if (cached !== undefined) return cached;
    memo.set(id, false); // guard against malformed cycles
    let out = pred(id);
    if (!out) for (const c of idx.get(id) ?? []) if (visit(c.id)) { out = true; break; }
    memo.set(id, out);
    return out;
  };
  return visit;
}

/** LEFT rail: only subtrees that contain a fleet; fleet leaves shown, ports + other
 *  non-fleet machines hidden. */
export function fleetTreeNodes(
  nodes: GroupNode[],
  fleetIds: Set<string>,
  fleetByNode: Map<string, Row>,
): TreeNode[] {
  const idx = childrenIndex(nodes);
  const subtreeHasFleet = makeSubtreeContains(idx, (id) => fleetIds.has(id));
  const keep = (nd: GroupNode): boolean =>
    fleetIds.has(nd.id) || (nd.kind === "group" && subtreeHasFleet(nd.id));
  const out: TreeNode[] = [];
  for (const nd of nodes) {
    if (!keep(nd)) continue;
    const isFleet = fleetIds.has(nd.id);
    out.push({
      id: nd.id,
      parentId: nd.parentId,
      kind: isFleet ? "machine" : "group",
      label: nd.label,
      level: isFleet ? `fleet · ${s(fleetByNode.get(nd.id)?.mode) || "—"}` : nd.level || undefined,
      hasChildren: (idx.get(nd.id) ?? []).some(keep),
      droppable: !isFleet,
    });
  }
  return out;
}

/** RIGHT rail: the facility structure — groups + ports/facilities; fleet leaves
 *  hidden entirely. */
export function facilityTreeNodes(
  nodes: GroupNode[],
  fleetIds: Set<string>,
  coord: Map<string, { lon: number; lat: number }>,
): TreeNode[] {
  const idx = childrenIndex(nodes);
  const keep = (nd: GroupNode): boolean => !fleetIds.has(nd.id);
  const out: TreeNode[] = [];
  for (const nd of nodes) {
    if (!keep(nd)) continue;
    const isPort = coord.has(nd.id);
    out.push({
      id: nd.id,
      parentId: nd.parentId,
      kind: nd.kind === "machine" ? "machine" : "group",
      label: nd.label,
      level: isPort ? "port" : nd.level || undefined,
      hasChildren: (idx.get(nd.id) ?? []).some(keep),
      droppable: nd.kind !== "machine",
    });
  }
  return out;
}
