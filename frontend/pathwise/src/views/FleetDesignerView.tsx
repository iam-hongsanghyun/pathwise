// Fleet designer — a NEW transport layer, SEPARATE from facility / network.
// LEFT sidebar = AccordionSidebar with four sections:
//   1. Fleets  — fleet registry (fleet_groups + fleet; NEVER nodes)
//   2. Routes  — network flow links whose two endpoints are located
//   3. Facility — drag an endpoint onto the map to give it a location
//   4. Chokepoint risk — maritime chokepoint probability + per-voyage toll editor
// CENTER = the world map. Pop-ups (FloatingPanel) edit a fleet / port / route.

import { useEffect, useMemo, useState } from "react";
import { useDialogs } from "../features/controls/Dialog";
import { FloatingPanel } from "../layout/FloatingPanel";
import { AccordionSidebar } from "../layout/AccordionSidebar";
import { SearchSelect } from "../features/controls/SearchSelect";
import { InfoTooltip } from "../features/controls/InfoTooltip";
import { TemporalValue, type TemporalVal } from "../features/controls/TemporalValue";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import type { TreeAction, TreeMoveEvent, TreeNode } from "../features/tree/types";
import { parseNodes } from "../lib/groupGraph";
import { MODES } from "../features/fleet/basemap";
import { FleetMap, type MapPort, type MapRoute } from "../features/fleet/FleetMap";
import {
  buildCoordMap,
  buildRouteLeaves,
  facilityTree,
  fleetId,
  fleetRegistryTree,
  parseLinks,
  parseFleetGroups,
  routeProc,
  routeTree,
  slugId,
  type RouteLeaf,
} from "../features/fleet/fleetGraph";
import { routeExposure, routePath, type CorridorExposure } from "../lib/api/routing";
import { modelCurrency } from "../lib/caps";
import { impactIds } from "../lib/scope";
import { FlatTablePanel } from "../features/table/FlatTablePanel";
import { flattenFleetGroup } from "../features/table/flatten.fleet";
import type { Row, Workbook } from "../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const blank = (v: string): number | string => (v === "" ? "" : Number(v));
let _ctr = 0;
const genId = (p: string): string => `${p}_${Date.now().toString(36)}${(_ctr++).toString(36)}`;

// Great-circle length [km] of a [lon,lat] polyline (longitude deltas normalised to
// ±180 so an antimeridian crossing measures the short way, not the long way round).
const R_EARTH = 6371;
function polyKm(line: [number, number][]): number {
  const rad = (x: number) => (x * Math.PI) / 180;
  let total = 0;
  for (let i = 1; i < line.length; i++) {
    const a = line[i - 1];
    const b = line[i];
    let dLon = b[0] - a[0];
    if (dLon > 180) dLon -= 360;
    if (dLon < -180) dLon += 360;
    const dLat = b[1] - a[1];
    const s1 = Math.sin(rad(dLat) / 2);
    const s2 = Math.sin(rad(dLon) / 2);
    const aa = s1 * s1 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * s2 * s2;
    total += 2 * R_EARTH * Math.asin(Math.min(1, Math.sqrt(aa)));
  }
  return total;
}

type Edit = { kind: "fleet" | "node" | "route"; id: string } | null;

// Major maritime chokepoints (searoute passage ids → friendly labels) a user can close.
const CORRIDORS: [string, string][] = [
  ["suez", "Suez Canal"],
  ["ormuz", "Strait of Hormuz"],
  ["panama", "Panama Canal"],
  ["malacca", "Strait of Malacca"],
  ["babalmandab", "Bab-el-Mandeb"],
  ["gibraltar", "Strait of Gibraltar"],
  ["bosporus", "Bosporus"],
  ["sunda", "Sunda Strait"],
];
const CORRIDOR_LABEL = new Map(CORRIDORS);

export function FleetDesignerView({
  workbook,
  setWorkbook,
}: {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
}) {
  const { prompt, confirm, node: dialogNode } = useDialogs();
  const [selId, setSelId] = useState<string | null>(null);
  const [expL, setExpL] = useState<Set<string>>(new Set());
  const [expR, setExpR] = useState<Set<string>>(new Set());
  const [expF, setExpF] = useState<Set<string>>(new Set());
  const [leftW, setLeftW] = useState(260);
  const [leftOpen, setLeftOpen] = useState(false);
  const [tableGroup, setTableGroup] = useState<string | null>(null); // "See in a table" group
  const [tableOpen, setTableOpen] = useState(true);
  const [tableH, setTableH] = useState(260);
  const [edit, setEdit] = useState<Edit>(null);

  const nodes = useMemo(() => parseNodes(workbook), [workbook]);
  const nodeById = useMemo(() => new Map(nodes.map((nd) => [nd.id, nd])), [nodes]);
  const fleets = useMemo(() => (workbook.fleet ?? []) as Row[], [workbook]);
  const fleetGroups = useMemo(() => parseFleetGroups(workbook), [workbook]);
  const fgById = useMemo(() => new Map(fleetGroups.map((g) => [g.id, g])), [fleetGroups]);
  const routes = useMemo(() => (workbook.routes ?? []) as Row[], [workbook]);
  const fleetRoutes = useMemo(() => (workbook.fleet_routes ?? []) as Row[], [workbook]);
  const greenCorridors = useMemo(() => (workbook.green_corridors ?? []) as Row[], [workbook]);
  const flows = useMemo(() => (workbook.flows ?? []).map((r) => s(r.flow_id)).filter(Boolean), [workbook]);
  const impacts = useMemo(() => impactIds(workbook), [workbook]);
  const coord = useMemo(() => buildCoordMap(workbook), [workbook]);
  const fleetByNode = useMemo(() => new Map(fleets.map((f) => [fleetId(f), f])), [fleets]);
  // Per-corridor ANNUAL CLOSURE PROBABILITY [0,1] — the chokepoint-risk input.
  // Legacy boolean `blocked` reads as 1 (always shut) for back-compat.
  const corridorProbs = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of workbook.corridors ?? []) {
      const id = s(r.corridor);
      if (!id) continue;
      const legacy = r.blocked === true || s(r.blocked) === "true" ? 1 : 0;
      const raw = r.disruption_prob == null || s(r.disruption_prob) === "" ? legacy : Number(r.disruption_prob);
      m.set(id, Number.isFinite(raw) ? Math.max(0, Math.min(1, raw)) : legacy);
    }
    return m;
  }, [workbook]);
  // Per-corridor PER-VOYAGE TOLL [currency/voyage] — a transit fee, independent of
  // the closure probability; a route pays it for every chokepoint it traverses.
  const corridorTolls = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of workbook.corridors ?? []) {
      const id = s(r.corridor);
      const t = id && r.toll != null && s(r.toll) !== "" ? Number(r.toll) : 0;
      if (id && Number.isFinite(t) && t > 0) m.set(id, t);
    }
    return m;
  }, [workbook]);
  const currency = useMemo(() => modelCurrency(workbook), [workbook]);
  // Corridors CLOSED in the base case (prob >= 1 = "assume shut"): the displayed map
  // reroutes around these and the deterministic solve does too. Sub-100% is risk-only.
  const blockedCorridors = useMemo(
    () => [...corridorProbs.entries()].filter(([, p]) => p >= 1).map(([id]) => id),
    [corridorProbs],
  );

  const links = useMemo(() => parseLinks(workbook), [workbook]);
  const routeLeaves = useMemo(() => buildRouteLeaves(links, routes, coord), [links, routes, coord]);
  const leafByProc = useMemo(() => new Map(routeLeaves.map((l) => [l.proc, l])), [routeLeaves]);
  const leftTree = useMemo(() => fleetRegistryTree(fleetGroups, fleets), [fleetGroups, fleets]);
  const routesTree = useMemo(() => routeTree(routeLeaves, (id) => nodeById.get(id)?.label ?? id), [routeLeaves, nodeById]);
  const facilityNodes = useMemo(() => facilityTree(nodes, coord), [nodes, coord]);
  // Friendly "from → to" label for a route (process id), for the chokepoint panel.
  const routeLabelByProc = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of routes) {
      const f = nodeById.get(s(r.from_node))?.label ?? s(r.from_node);
      const t = nodeById.get(s(r.to_node))?.label ?? s(r.to_node);
      m.set(s(r.process), `${f} → ${t}`);
    }
    return m;
  }, [routes, nodeById]);
  const periods = useMemo(() => [...new Set((workbook.periods ?? []).map((r) => Number(r.year)).filter(Number.isFinite))].sort((a, b) => a - b), [workbook]);
  const baseYear = periods[0] ?? 2025;
  const tableResult = useMemo(() => (tableGroup ? flattenFleetGroup(workbook, tableGroup) : null), [tableGroup, workbook]);

  const ports = useMemo<MapPort[]>(
    () => [...coord.entries()].map(([id, c]) => ({ id, label: nodeById.get(id)?.label ?? id, ...c })),
    [coord, nodeById],
  );
  // Each map route carries a cache key (rounded endpoints + mode) so a port's sea
  // polyline is fetched once and re-used; the polyline itself lives in `paths`.
  const [paths, setPaths] = useState<Map<string, [number, number][]>>(new Map());
  // Active chokepoint ids each route crosses (for the hover tooltip + per-voyage toll).
  const [routeChokepoints, setRouteChokepoints] = useState<Map<string, string[]>>(new Map());
  // Chokepoints worth showing a detour for: a closure probability in (0,1) — 100% is
  // already the base reroute — OR a per-voyage toll (here's the toll-free way round).
  const activeCorridorIds = useMemo(() => {
    const ids = new Set<string>();
    for (const [id, p] of corridorProbs) if (p > 0 && p < 1) ids.add(id);
    for (const id of corridorTolls.keys()) ids.add(id);
    return [...ids].sort();
  }, [corridorProbs, corridorTolls]);
  // Candidate fleets per route — pinned (fleet_routes) first, else any fleet whose
  // cargo matches the route's flow (the optimiser's candidate set).
  const fleetsByProc = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const fr of fleetRoutes) {
      const proc = s(fr.process);
      if (!proc) continue;
      (m.get(proc) ?? m.set(proc, []).get(proc)!).push(s(fleetByNode.get(s(fr.fleet))?.label) || s(fr.fleet));
    }
    return m;
  }, [fleetRoutes, fleetByNode]);
  const fleetsByCargo = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const f of fleets) {
      const cargo = s(f.cargo);
      if (!cargo) continue;
      (m.get(cargo) ?? m.set(cargo, []).get(cargo)!).push(s(f.label) || fleetId(f));
    }
    return m;
  }, [fleets]);
  const drawRoutes = useMemo(
    () =>
      routes
        .map((r) => {
          const from = coord.get(s(r.from_node));
          const to = coord.get(s(r.to_node));
          if (!from || !to) return null;
          const mode = s(r.mode) || "sea";
          const proc = s(r.process);
          const flow = s(r.flow);
          const key = `${from.lon.toFixed(2)},${from.lat.toFixed(2)}|${to.lon.toFixed(2)},${to.lat.toFixed(2)}|${mode}|${blockedCorridors.join(",")}`;
          return {
            process: proc, from, to, mode, key,
            blocked: s(r.blocked) === "true",
            fromLabel: nodeById.get(s(r.from_node))?.label ?? s(r.from_node),
            toLabel: nodeById.get(s(r.to_node))?.label ?? s(r.to_node),
            flow,
            fleets: fleetsByProc.get(proc) ?? fleetsByCargo.get(flow) ?? [],
          };
        })
        .filter((r): r is NonNullable<typeof r> => r !== null),
    [routes, coord, blockedCorridors, nodeById, fleetsByProc, fleetsByCargo],
  );
  // Located links not yet physicalised (both endpoints placed, no route row) — drawn
  // dotted + orange as a "connect me" candidate; clicking one physicalises it.
  const candidateRoutes = useMemo<MapRoute[]>(
    () =>
      routeLeaves
        .filter((l) => !l.physical && coord.has(l.from) && coord.has(l.to))
        .map((l) => ({
          process: l.proc,
          from: coord.get(l.from)!,
          to: coord.get(l.to)!,
          blocked: false,
          unconnected: true,
          fromLabel: nodeById.get(l.from)?.label ?? l.from,
          toLabel: nodeById.get(l.to)?.label ?? l.to,
          flow: l.flow,
        })),
    [routeLeaves, coord, nodeById],
  );
  const mapRoutes = useMemo<MapRoute[]>(
    () => [
      ...drawRoutes.map((r) => {
        const path = paths.get(r.key);
        const cps = routeChokepoints.get(r.process) ?? [];
        return {
          ...r,
          path,
          distanceKm: path ? polyKm(path) : undefined,
          chokepoints: cps.map((id) => CORRIDOR_LABEL.get(id) ?? id),
          tollPerVoyage: cps.reduce((sum, id) => sum + (corridorTolls.get(id) ?? 0), 0),
        };
      }),
      ...candidateRoutes,
    ],
    [drawRoutes, candidateRoutes, paths, routeChokepoints, corridorTolls],
  );
  // Sea routes (located) fed to the chokepoint-exposure analysis. Memoised so its
  // identity only changes with the geometry — the panel refetches on that, not on
  // every probability edit (probability is applied client-side).
  const exposureRoutes = useMemo(
    () => drawRoutes.filter((r) => r.mode === "sea").map((r) => ({ id: r.process, from: r.from, to: r.to, mode: "sea" })),
    [drawRoutes],
  );
  // Fetch any missing route polylines (debounced, so dragging a port doesn't spam).
  useEffect(() => {
    const t = setTimeout(() => {
      const missing = drawRoutes.filter((r) => !paths.has(r.key));
      if (missing.length === 0) return;
      void Promise.all(
        missing.map((r) =>
          routePath(r.from, r.to, r.mode, blockedCorridors).then((coords) => [r.key, coords] as const).catch(() => null)),
      ).then((pairs) => {
        const ok = pairs.filter((p): p is readonly [string, [number, number][]] => p !== null);
        if (ok.length) setPaths((prev) => { const m = new Map(prev); for (const [k, v] of ok) m.set(k, v); return m; });
      });
    }, 250);
    return () => clearTimeout(t);
  }, [drawRoutes, paths, blockedCorridors]);

  // Which active chokepoints each sea route crosses — drives the hover tooltip + the
  // per-voyage toll. (Routes draw solid; no dotted detour overlay.)
  const activeKey = activeCorridorIds.join(",");
  useEffect(() => {
    let alive = true;
    if (exposureRoutes.length === 0 || activeCorridorIds.length === 0) { setRouteChokepoints(new Map()); return; }
    const t = setTimeout(() => {
      void routeExposure(exposureRoutes, activeCorridorIds.map((id) => ({ id, prob: corridorProbs.get(id) ?? 0 })))
        .then((list) => {
          const used = new Map<string, string[]>(); // process -> active corridors it crosses
          for (const c of list) for (const r of c.routes) (used.get(r.route_id) ?? used.set(r.route_id, []).get(r.route_id)!).push(c.id);
          if (alive) setRouteChokepoints(new Map(used));
        })
        .catch(() => { if (alive) setRouteChokepoints(new Map()); });
    }, 300);
    return () => { alive = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exposureRoutes, activeKey]);

  // ── writes ───────────────────────────────────────────────────────────────────
  const setSheet = (wb: Workbook, sheet: string, rows: Row[]): Workbook => ({ ...wb, [sheet]: rows });
  const patchFleet = (id: string, p: Row) => setWorkbook(setSheet(workbook, "fleet", fleets.map((r) => (fleetId(r) === id ? { ...r, ...p } : r))));
  const patchFleetGroup = (id: string, p: Row) => setWorkbook(setSheet(workbook, "fleet_groups", (workbook.fleet_groups ?? []).map((r) => (s(r.group_id) === id ? { ...r, ...p } : r))));
  const patchNode = (id: string, p: Row) => setWorkbook(setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (s(r.node_id) === id ? { ...r, ...p } : r))));
  const patchRoute = (proc: string, p: Row) => setWorkbook(setSheet(workbook, "routes", routes.map((r) => (s(r.process) === proc ? { ...r, ...p } : r))));

  // ── Fleet registry (fleet_groups + fleet — NEVER nodes) ─────────────────────
  async function addFleetGroup(parentId: string | null) {
    const label = (await prompt({ title: "Add group", label: "name", placeholder: "e.g. Alliance, Carrier Co." }))?.trim();
    if (!label) return;
    const level = (await prompt({ title: "Level", label: "level", defaultValue: parentId ? "company" : "alliance", placeholder: "alliance / company / … (your own)" }))?.trim() || "";
    const id = genId("fg");
    setWorkbook(setSheet(workbook, "fleet_groups", [...(workbook.fleet_groups ?? []), { group_id: id, parent_id: parentId, label, level }]));
    if (parentId) setExpL((p) => new Set(p).add(parentId));
  }
  async function addFleet(parentId: string | null) {
    const label = (await prompt({ title: "Add fleet", label: "name", placeholder: "e.g. Panamax bulkers" }))?.trim();
    if (!label) return;
    const id = genId("flt");
    setWorkbook(setSheet(workbook, "fleet", [...fleets, { fleet_id: id, label, group: parentId ?? "", company: parentId ?? "", mode: "sea", count: 1 }]));
    if (parentId) setExpL((p) => new Set(p).add(parentId));
    setSelId(id);
    setEdit({ kind: "fleet", id });
  }
  function duplicateFleet(id: string, times: number) {
    const src = fleetByNode.get(id);
    if (!src) return;
    const baseLabel = s(src.label) || id;
    const copies: Row[] = [];
    for (let i = 1; i <= times; i++)
      copies.push({ ...src, fleet_id: genId("flt"), archetype: "", label: times === 1 ? `${baseLabel} copy` : `${baseLabel} #${i}` });
    setWorkbook(setSheet(workbook, "fleet", [...fleets, ...copies]));
  }
  function fleetGroupDescendants(id: string): Set<string> {
    const out = new Set<string>([id]);
    let added = true;
    while (added) { added = false; for (const g of fleetGroups) if (g.parentId && out.has(g.parentId) && !out.has(g.id)) { out.add(g.id); added = true; } }
    return out;
  }
  async function deleteLeft(id: string) {
    if (fleetByNode.has(id)) {
      setWorkbook(setSheet(setSheet(workbook, "fleet", fleets.filter((r) => fleetId(r) !== id)), "fleet_routes", fleetRoutes.filter((r) => fleetId(r) !== id)));
      if (selId === id) { setSelId(null); setEdit(null); }
      return;
    }
    if (!(await confirm({ title: "Delete", message: `Delete '${fgById.get(id)?.label ?? id}' and the fleets under it?`, danger: true, confirmLabel: "Delete" }))) return;
    const doomedG = fleetGroupDescendants(id);
    const doomedF = new Set(fleets.filter((f) => doomedG.has(s(f.group))).map(fleetId));
    let wb = setSheet(workbook, "fleet_groups", (workbook.fleet_groups ?? []).filter((r) => !doomedG.has(s(r.group_id))));
    wb = setSheet(wb, "fleet", fleets.filter((r) => !doomedF.has(fleetId(r))));
    wb = setSheet(wb, "fleet_routes", fleetRoutes.filter((r) => !doomedF.has(fleetId(r))));
    setWorkbook(wb);
    if (selId && (doomedG.has(selId) || doomedF.has(selId))) { setSelId(null); setEdit(null); }
  }
  async function renameLeft(id: string) {
    const isFleet = fleetByNode.has(id);
    const cur = isFleet ? s(fleetByNode.get(id)?.label) || id : fgById.get(id)?.label ?? id;
    const next = (await prompt({ title: "Rename", label: "name", defaultValue: cur }))?.trim();
    if (!next) return;
    if (isFleet) patchFleet(id, { label: next });
    else patchFleetGroup(id, { label: next });
  }
  function onMoveLeft(e: TreeMoveEvent) {
    const newParent = e.position === "inside" ? e.targetId : fgById.get(e.beforeSiblingId ?? "")?.parentId ?? null;
    if (e.dragId === newParent) return;
    if (fleetByNode.has(e.dragId)) patchFleet(e.dragId, { group: newParent ?? "", company: newParent ?? "" });
    else patchFleetGroup(e.dragId, { parent_id: newParent ?? "" });
  }

  // ── Routes: physicalise a stream link + locate its endpoints ───────────
  function selectRoute(leaf: RouteLeaf) {
    if (!leaf.physical && !routes.some((r) => s(r.process) === leaf.proc))
      setWorkbook(setSheet(workbook, "routes", [...routes, { process: leaf.proc, from_node: leaf.from, to_node: leaf.to, flow: leaf.flow, mode: "sea" }]));
    setSelId(leaf.proc);
    setEdit({ kind: "route", id: leaf.proc });
  }
  // Add an ALTERNATIVE MODE on a lane: a second route row with the same
  // from/to/flow but a different mode. The engine groups same-edge routes into one
  // lane and splits its flow across the modes, picking the cheapest feasible mix.
  function addModeRoute(base: Row, mode: string) {
    const from = s(base.from_node), to = s(base.to_node), flow = s(base.flow);
    const root = routeProc(from, to, flow); // canonical (primary) lane id
    const taken = new Set(routes.map((r) => s(r.process)));
    let proc = `${root}__${slugId(mode)}`;
    for (let n = 2; taken.has(proc); n++) proc = `${root}__${slugId(mode)}_${n}`;
    setWorkbook(setSheet(workbook, "routes", [...routes, { process: proc, from_node: from, to_node: to, flow, mode }]));
    setSelId(proc);
    setEdit({ kind: "route", id: proc });
  }
  // Remove a route (a mode on a lane): drop its row + its fleet candidates. Lane-scoped
  // green corridors are left as-is (they bind the lane, which other modes may still serve).
  function removeRoute(proc: string) {
    setWorkbook(
      setSheet(
        setSheet(workbook, "routes", routes.filter((r) => s(r.process) !== proc)),
        "fleet_routes",
        fleetRoutes.filter((r) => s(r.process) !== proc),
      ),
    );
    if (selId === proc) { setSelId(null); setEdit(null); }
  }
  const routeActions = (n: TreeNode): TreeAction[] =>
    n.kind === "asset" && routes.some((r) => s(r.process) === n.id)
      ? [{ id: "edit", label: "Edit" }, { id: "delete", label: "Delete route", danger: true }]
      : [];
  function onRouteAction(a: string, n: TreeNode) {
    if (a === "delete") void removeRoute(n.id);
    else if (a === "edit") { const leaf = leafByProc.get(n.id); if (leaf) selectRoute(leaf); }
  }
  // A Facility endpoint dropped on the map (or its marker dragged) → set its location.
  function locateNode(id: string, lon: number, lat: number) {
    patchNode(id, { lon, lat });
    setSelId(id);
  }
  // Upsert a corridor's probability and/or per-voyage toll on the `corridors` sheet.
  function patchCorridor(name: string, patch: { prob?: number; toll?: number }) {
    const prob = patch.prob != null
      ? Math.max(0, Math.min(1, Number.isFinite(patch.prob) ? patch.prob : 0))
      : corridorProbs.get(name) ?? 0;
    const toll = patch.toll != null
      ? Math.max(0, Number.isFinite(patch.toll) ? patch.toll : 0)
      : corridorTolls.get(name) ?? 0;
    const rows = (workbook.corridors ?? []).filter((r) => s(r.corridor) !== name);
    setWorkbook(
      setSheet(
        workbook,
        "corridors",
        prob > 0 || toll > 0
          ? [...rows, { corridor: name, disruption_prob: prob || "", toll: toll || "", blocked: prob >= 1 ? "true" : "" }]
          : rows,
      ),
    );
  }
  const setCorridorProb = (name: string, prob: number) => patchCorridor(name, { prob });
  const setCorridorToll = (name: string, toll: number) => patchCorridor(name, { toll });
  function toggleBlock(proc: string, on: boolean) {
    setWorkbook(setSheet(workbook, "routes", routes.map((r) => (s(r.process) === proc ? { ...r, blocked: on ? "true" : "" } : r))));
  }

  // ── Tree actions ─────────────────────────────────────────────────────────────
  const leftActions = (n: TreeNode): TreeAction[] =>
    n.kind === "asset"
      ? [{ id: "edit", label: "Edit" }, { id: "dup", label: "Duplicate" }, { id: "dupN", label: "Duplicate ×N…" }, { id: "rename", label: "Rename" }, { id: "delete", label: "Delete", danger: true }]
      : [{ id: "add-fleet", label: "Add fleet" }, { id: "add-group", label: "Add group inside" }, { id: "see-table", label: "See in a table", separatorBefore: true }, { id: "rename", label: "Rename", separatorBefore: true }, { id: "delete", label: "Delete", danger: true }];
  const onLeftAction = (a: string, n: TreeNode) => {
    if (a === "add-fleet") void addFleet(n.id);
    else if (a === "add-group") void addFleetGroup(n.id);
    else if (a === "rename") void renameLeft(n.id);
    else if (a === "delete") void deleteLeft(n.id);
    else if (a === "edit") setEdit({ kind: "fleet", id: n.id });
    else if (a === "dup") duplicateFleet(n.id, 1);
    else if (a === "dupN") void (async () => { const x = await prompt({ title: "Duplicate ×N", label: "how many copies", defaultValue: "10" }); const t = Math.max(1, Math.round(Number(x) || 0)); if (t) duplicateFleet(n.id, t); })();
    else if (a === "see-table") { setTableGroup(n.id); setTableOpen(true); }
  };
  const editRoute = edit?.kind === "route" ? routes.find((r) => s(r.process) === edit.id) : undefined;
  // Corridors carrying a sub-100% closure probability (the risk inputs; 100% = shut).
  const corridorAtRisk = useMemo(() => [...corridorProbs.values()].filter((p) => p > 0 && p < 1).length, [corridorProbs]);

  return (
    <div className="view-full builder">
      <div className="builder-body">
        <AccordionSidebar
          open={leftOpen}
          setOpen={setLeftOpen}
          width={leftW}
          setWidth={setLeftW}
          min={200}
          max={480}
          collapsedExtras={
            <button className="rail-add" title="add an alliance / company group" onClick={() => void addFleetGroup(null)}>＋</button>
          }
          sections={[
            {
              id: "fleets",
              title: "Fleets",
              defaultOpen: false,
              headAction: (
                <button className="rail-add" title="add an alliance / company group" onClick={() => void addFleetGroup(null)}>＋</button>
              ),
              body: (
                <TreeExplorer
                  nodes={leftTree}
                  selectedId={selId}
                  expandedIds={expL}
                  onToggle={(id, e) => setExpL((p) => { const m = new Set(p); e ? m.add(id) : m.delete(id); return m; })}
                  onSelect={(id) => { setSelId(id); if (fleetByNode.has(id)) setEdit({ kind: "fleet", id }); }}
                  actionsFor={leftActions}
                  onContextAction={onLeftAction}
                  onMove={onMoveLeft}
                  emptyHint="Empty — ＋ to add an alliance / company, then add fleets inside."
                />
              ),
            },
            {
              id: "routes",
              title: "Routes",
              defaultOpen: false,
              headAction: (
                <span className="rail-hint" style={{ padding: "0 6px" }}>flow → route</span>
              ),
              body: (
                <TreeExplorer
                  nodes={routesTree}
                  selectedId={selId}
                  expandedIds={expR}
                  onToggle={(id, e) => setExpR((p) => { const m = new Set(p); e ? m.add(id) : m.delete(id); return m; })}
                  onSelect={(id) => { const leaf = leafByProc.get(id); if (leaf) selectRoute(leaf); else setExpR((p) => { const m = new Set(p); m.has(id) ? m.delete(id) : m.add(id); return m; }); }}
                  actionsFor={routeActions}
                  onContextAction={onRouteAction}
                  onMove={() => undefined}
                  emptyHint="Place both ends of a network flow to see it here as a route."
                />
              ),
            },
            {
              id: "facility",
              title: "Facility",
              defaultOpen: false,
              headAction: (
                <span className="rail-hint" style={{ padding: "0 6px" }}>{[...coord.keys()].length} placed</span>
              ),
              body: (
                <>
                  <TreeExplorer
                    nodes={facilityNodes}
                    selectedId={selId}
                    expandedIds={expF}
                    onToggle={(id, e) => setExpF((p) => { const m = new Set(p); e ? m.add(id) : m.delete(id); return m; })}
                    onSelect={(id) => { setSelId(id); setEdit({ kind: "node", id }); }}
                    actionsFor={() => []}
                    onContextAction={() => undefined}
                    onMove={() => undefined}
                    canDrop={() => false}
                    emptyHint="The facility / network structure — drag a node onto the map to place it."
                  />
                  <div className="rail-foot">Drag a facility node onto the map to give it a location.</div>
                </>
              ),
            },
            {
              id: "chokepoints",
              title: "Chokepoint risk",
              info: "Each chokepoint has an annual closure probability (sub-100% = sensitivity only; 100% reroutes every run) and a per-voyage toll. Exposure = the detour a closure forces × its probability.",
              defaultOpen: false,
              grow: true,
              headAction: (
                <span className="rail-foot" style={{ padding: "0 6px", border: "none" }}>
                  {blockedCorridors.length ? `${blockedCorridors.length} shut` : corridorAtRisk ? `${corridorAtRisk} at risk` : ""}
                </span>
              ),
              body: (
                <ChokepointDesigner
                  probs={corridorProbs}
                  tolls={corridorTolls}
                  onProb={setCorridorProb}
                  onToll={setCorridorToll}
                  routes={exposureRoutes}
                  routeLabel={(p) => routeLabelByProc.get(p) ?? p}
                  currency={currency}
                />
              ),
            },
          ]}
        />

        <main className="builder-canvas">
          <div className="view-head">
            <div className="eyebrow">fleet</div>
            <span className="view-status">drag a facility onto the map to place it · drag a marker to move it · click a route to edit</span>
          </div>
          <div style={{ flex: 1, minHeight: 0, display: "flex", padding: "10px 14px" }}>
            <FleetMap
              ports={ports}
              routes={mapRoutes}
              selId={selId}
              pendingFrom={null}
              currency={currency}
              onMovePort={(id, lon, lat) => patchNode(id, { lon, lat })}
              onClickPort={(id) => { setSelId(id); setEdit({ kind: "node", id }); }}
              onDropNode={locateNode}
              onSelectRoute={(proc) => { const leaf = leafByProc.get(proc); if (leaf) selectRoute(leaf); else { setSelId(proc); setEdit({ kind: "route", id: proc }); } }}
              onBackground={() => undefined}
            />
          </div>
          {ports.length === 0 && (
            <p className="view-lead" style={{ padding: "0 14px" }}>
              Drag a facility from the left rail onto the map to give it a location. Once both ends of a flow are placed, the flow appears under <b>Routes</b> — set a mode to make it physical (otherwise it teleports).
            </p>
          )}
          {tableResult && (
            <FlatTablePanel
              result={tableResult}
              workbook={workbook}
              setWorkbook={setWorkbook}
              baseYear={baseYear}
              periods={periods}
              height={tableH}
              setHeight={setTableH}
              open={tableOpen}
              onToggle={() => setTableOpen((o) => !o)}
              onClose={() => setTableGroup(null)}
            />
          )}
        </main>
      </div>

      {edit?.kind === "fleet" && fleetByNode.get(edit.id) && (
        <FleetPanel fleet={fleetByNode.get(edit.id)!} flows={flows}
          onRename={(v) => patchFleet(edit.id, { label: v })} onChange={(p) => patchFleet(edit.id, p)} onClose={() => setEdit(null)} />
      )}
      {edit?.kind === "node" && nodeById.get(edit.id) && (
        <NodePanel id={edit.id} label={nodeById.get(edit.id)!.label} level={nodeById.get(edit.id)!.level} coord={coord.get(edit.id)}
          onRename={(v) => patchNode(edit.id, { label: v })} onLevel={(v) => patchNode(edit.id, { level: v })} onCoord={(p) => patchNode(edit.id, p)} onClose={() => setEdit(null)} />
      )}
      {editRoute && (
        <RoutePanel route={editRoute} routes={routes} fleets={fleets} fleetRoutes={fleetRoutes}
          labelOf={(id) => nodeById.get(id)?.label ?? id} fleetLabel={(fid) => s(fleetByNode.get(fid)?.label) || fid}
          onChange={(p) => patchRoute(edit!.id, p)} onToggleBlock={(on) => toggleBlock(edit!.id, on)}
          setFleetRoutes={(rows) => setWorkbook(setSheet(workbook, "fleet_routes", rows))}
          onAddMode={(mode) => addModeRoute(editRoute, mode)}
          onSwitch={(p) => { setSelId(p); setEdit({ kind: "route", id: p }); }}
          impacts={impacts} green={greenCorridors} periods={periods} baseYear={baseYear} currency={currency}
          setGreen={(rows) => setWorkbook(setSheet(workbook, "green_corridors", rows))}
          onClose={() => setEdit(null)} />
      )}
      {dialogNode}
    </div>
  );
}

// Chokepoint designer (left-rail section): each maritime corridor carries an annual
// closure PROBABILITY and an optional per-voyage TOLL.
const _km = (km: number): string => (km >= 1000 ? `${(km / 1000).toFixed(1)}k` : Math.round(km).toString());

function ChokepointDesigner({
  probs,
  tolls,
  onProb,
  onToll,
  routes,
  routeLabel,
  currency,
}: {
  probs: Map<string, number>;
  tolls: Map<string, number>;
  onProb: (name: string, prob: number) => void;
  onToll: (name: string, toll: number) => void;
  routes: { id: string; from: { lon: number; lat: number }; to: { lon: number; lat: number }; mode?: string }[];
  routeLabel: (proc: string) => string;
  currency: string;
}) {
  const [exp, setExp] = useState<Map<string, CorridorExposure>>(new Map());
  const [loading, setLoading] = useState(false);
  const hardKey = CORRIDORS.filter(([id]) => (probs.get(id) ?? 0) >= 1).map(([id]) => id).join(",");
  useEffect(() => {
    let alive = true;
    if (routes.length === 0) { setExp(new Map()); return; }
    setLoading(true);
    routeExposure(routes, CORRIDORS.map(([id]) => ({ id, prob: probs.get(id) ?? 0 })))
      .then((list) => { if (alive) setExp(new Map(list.map((e) => [e.id, e]))); })
      .catch(() => { if (alive) setExp(new Map()); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routes, hardKey]);

  const ranked = CORRIDORS.map(([id, label]) => {
    const e = exp.get(id);
    const p = probs.get(id) ?? 0;
    return { id, label, p, toll: tolls.get(id) ?? 0, e, expected: e ? p * e.total_delta_km : 0 };
  }).sort((a, b) => {
    const sa = (a.e?.n_stranded ?? 0) > 0 ? 1 : 0;
    const sb = (b.e?.n_stranded ?? 0) > 0 ? 1 : 0;
    return sb !== sa ? sb - sa : b.expected - a.expected;
  });

  return (
    <div style={{ padding: "8px 12px" }}>
      {routes.length === 0 ? (
        <p className="rail-empty">Place both ends of a sea route on the map to see exposure.</p>
      ) : (
        <>
          <div className="corridor-cols">
            <span>chokepoint</span>
            <span>%/yr</span>
            <span>{currency}/voy</span>
          </div>
          {ranked.map(({ id, label, p, toll, e, expected }) => {
          const used = !!e && e.n_routes > 0;
          const stranded = (e?.n_stranded ?? 0) > 0;
          const detail = e?.routes
            .map((r) => `${routeLabel(r.route_id)} — ${r.detour_km == null ? "no alternative" : `+${Math.round(r.delta_pct ?? 0)}% (+${_km(r.delta_km ?? 0)} km)`}`)
            .join("\n");
          // The exposure description now lives behind a (ⓘ) on the right of the row.
          const expoText = !used
            ? "No route uses this chokepoint."
            : stranded
              ? `⚠ ${e!.n_stranded} route${e!.n_stranded > 1 ? "s" : ""} stranded — no way around${e!.n_routes > e!.n_stranded ? ` · ${e!.n_routes - e!.n_stranded} reroute` : ""}\n\n${detail}`
              : `${e!.n_routes} route${e!.n_routes > 1 ? "s" : ""} · +${_km(e!.total_delta_km)} km if shut${p > 0 ? ` · ~${_km(expected)} km/yr expected` : ""}\n\n${detail}`;
          return (
            <div key={id} className={`corridor-row${stranded ? " is-stranded" : ""}`}>
              <div className="corridor-main">
                <span className="corridor-name">{label}</span>
                <input className="field-input corridor-num" type="number" min={0} max={100} step={0.5}
                  title="annual closure probability (%/yr)"
                  value={p ? Number((p * 100).toFixed(2)) : ""} placeholder="0"
                  onChange={(ev) => onProb(id, ev.target.value === "" ? 0 : Number(ev.target.value) / 100)} />
                <input className="field-input corridor-num" type="number" min={0} step={1000}
                  title={`per-voyage toll (${currency}/voyage)`}
                  value={toll || ""} placeholder="0"
                  onChange={(ev) => onToll(id, ev.target.value === "" ? 0 : Number(ev.target.value))} />
                <span style={{ display: "inline-flex", alignItems: "center", color: stranded ? "var(--danger)" : undefined }}>
                  {stranded ? "⚠" : ""}<InfoTooltip text={expoText} />
                </span>
              </div>
            </div>
          );
        })}
        </>
      )}
      {loading && <p className="muted" style={{ fontSize: "0.72rem", marginTop: 8 }}>computing exposure…</p>}
    </div>
  );
}

// ── Pop-up editors (FloatingPanel) ────────────────────────────────────────────
const FIELDS: [string, string][] = [
  ["mode", "mode"], ["cargo", "cargo (flow)"], ["fuel", "fuel (flow)"], ["efficiency", "efficiency (fuel/cargo/dist)"],
  ["count", "units"], ["ship_size", "cargo / voyage"], ["speed", "speed (dist/day)"], ["turnaround_days", "turnaround (days)"],
  ["operating_days", "operating days/yr"], ["capacity", "flat capacity/unit"], ["build_year", "build year"], ["close_year", "close year"], ["lifespan", "lifespan (yr)"],
];
const FIELD_INFO: Record<string, string> = {
  mode: "Transport mode. Sea routes follow real sea lanes (searoute, via Suez/Panama); road/rail use great-circle × a detour factor.",
  cargo: "The flow this fleet carries — what it delivers along its routes.",
  fuel: "The flow the fleet burns. Combined with efficiency × route distance it drives fuel cost and emissions (priced via the fuel's own price + impact factors — no hardcoded CO₂).",
  efficiency: "Fuel consumed per unit cargo per unit distance. A longer route therefore burns proportionally more fuel.",
  count: "How many carriers are in this fleet — the pool the optimiser allocates across its routes.",
  ship_size: "Cargo one carrier moves per voyage. With speed it sets how much a carrier can deliver per year on a route.",
  speed: "Travel speed (distance per day). Sets round-trip time, so a longer route means fewer trips ⇒ each carrier delivers less ⇒ more carriers needed.",
  turnaround_days: "Load + unload time added to each round trip.",
  operating_days: "In-service days per year (idle/maintenance excluded). Default 350.",
  capacity: "A flat per-carrier yearly throughput. Used only when ship size/speed are blank; otherwise capacity is derived from the route's distance.",
  build_year: "First year the fleet is in service. Before it, the fleet has zero carriers available.",
  close_year: "Last year in service (or leave blank and use lifespan). After it, the fleet retires.",
  lifespan: "Service life in years — with a build year, the fleet retires after build + lifespan − 1.",
};

function FleetPanel({ fleet, flows, onRename, onChange, onClose }: { fleet: Row; flows: string[]; onRename: (v: string) => void; onChange: (p: Row) => void; onClose: () => void }) {
  return (
    <FloatingPanel title="fleet" width={360} onClose={onClose}>
      <div style={{ padding: "12px 14px" }}>
        <input className="title-input" value={s(fleet.label) || fleetId(fleet)} onChange={(e) => onRename(e.target.value)} />
        {FIELDS.map(([key, lbl]) => (
          <label className="field-row" key={key} style={{ marginTop: 6 }}>
            <span className="muted">{lbl} {FIELD_INFO[key] && <InfoTooltip text={FIELD_INFO[key]} />}</span>
            {key === "mode" ? (
              <div style={{ flex: 1 }}><SearchSelect value={s(fleet.mode) || "sea"} onChange={(v) => onChange({ mode: v })} options={MODES} /></div>
            ) : key === "cargo" || key === "fuel" ? (
              <div style={{ flex: 1 }}><SearchSelect value={s(fleet[key])} onChange={(v) => onChange({ [key]: v })} options={flows.map((c) => ({ value: c }))} /></div>
            ) : (
              <input className="field-input" style={{ flex: 1 }} type="number" value={s(fleet[key])} onChange={(e) => onChange({ [key]: blank(e.target.value) })} />
            )}
          </label>
        ))}
      </div>
    </FloatingPanel>
  );
}

function NodePanel({ id, label, level, coord, onRename, onLevel, onCoord, onClose }: { id: string; label: string; level: string; coord?: { lon: number; lat: number }; onRename: (v: string) => void; onLevel: (v: string) => void; onCoord: (p: Row) => void; onClose: () => void }) {
  const isPort = !!coord;
  return (
    <FloatingPanel title={isPort ? "port" : "group"} width={320} onClose={onClose}>
      <div style={{ padding: "12px 14px" }}>
        <input className="title-input" value={label} onChange={(e) => onRename(e.target.value)} />
        <label className="field-row" style={{ marginTop: 8 }}>
          <span className="muted">level</span>
          <input className="field-input" style={{ flex: 1 }} value={level} onChange={(e) => onLevel(e.target.value)} placeholder="port / facility / region" />
        </label>
        <label className="field-row" style={{ marginTop: 6 }}>
          <span className="muted">longitude</span>
          <input className="field-input" style={{ flex: 1 }} type="number" value={coord ? coord.lon : ""} onChange={(e) => onCoord({ lon: blank(e.target.value) })} placeholder="—" />
        </label>
        <label className="field-row" style={{ marginTop: 6 }}>
          <span className="muted">latitude</span>
          <input className="field-input" style={{ flex: 1 }} type="number" value={coord ? coord.lat : ""} onChange={(e) => onCoord({ lat: blank(e.target.value) })} placeholder="—" />
        </label>
        <p className="rail-empty" style={{ marginTop: 8 }}>{isPort ? "Drag the marker on the map to move it. Once both ends of a flow are placed it appears under Routes." : "Drag this onto the map (or set a longitude/latitude) to place it."}</p>
        <input type="hidden" value={id} readOnly />
      </div>
    </FloatingPanel>
  );
}

function RoutePanel({ route, routes, fleets, fleetRoutes, labelOf, fleetLabel, onChange, onToggleBlock, setFleetRoutes, onAddMode, onSwitch, impacts, green, setGreen, periods, baseYear, currency, onClose }: {
  route: Row; routes: Row[]; fleets: Row[]; fleetRoutes: Row[]; labelOf: (id: string) => string; fleetLabel: (id: string) => string;
  onChange: (p: Row) => void; onToggleBlock: (on: boolean) => void; setFleetRoutes: (rows: Row[]) => void;
  onAddMode: (mode: string) => void; onSwitch: (proc: string) => void;
  impacts: string[]; green: Row[]; setGreen: (rows: Row[]) => void;
  periods: number[]; baseYear: number; currency: string; onClose: () => void;
}) {
  const proc = s(route.process);
  const blocked = s(route.blocked) === "true";
  const flow = s(route.flow);
  const fromN = s(route.from_node), toN = s(route.to_node);
  // Green corridors on THIS lane (from, to, flow). The cap is a TEMPORAL value: a
  // year-less row ⇒ a flat cap; per-year rows ⇒ a {year: limit} trajectory. Soft caps
  // carry a penalty (price per unit of exceedance). One control per capped impact.
  const laneIs = (r: Row, impact: string) =>
    s(r.from_node) === fromN && s(r.to_node) === toN && s(r.flow) === flow && s(r.impact) === impact;
  const laneRows = green.filter(
    (r) => s(r.from_node) === fromN && s(r.to_node) === toN && s(r.flow) === flow,
  );
  const cappedImpacts = [...new Set(laneRows.map((r) => s(r.impact)))];
  const addableImpacts = impacts.filter((i) => !cappedImpacts.includes(i));
  const rowsFor = (impact: string) => laneRows.filter((r) => s(r.impact) === impact);
  const limitOf = (impact: string): TemporalVal => {
    const rows = rowsFor(impact);
    const yearly: Record<string, number> = {};
    let flat = 0;
    for (const r of rows) {
      const lim = Number(r.limit) || 0;
      if (s(r.year)) yearly[s(r.year)] = lim;
      else flat = lim;
    }
    return Object.keys(yearly).length ? yearly : flat;
  };
  const softOf = (impact: string) => {
    const r = rowsFor(impact)[0];
    return !r || (s(r.soft) !== "false" && s(r.soft) !== "");
  };
  const penaltyOf = (impact: string) => {
    const r = rowsFor(impact).find((x) => s(x.penalty));
    return r ? Number(r.penalty) : null;
  };
  // Rewrite all (lane, impact) rows from a temporal limit + soft + penalty.
  const commitGreen = (impact: string, lim: TemporalVal | null, soft: boolean, penalty: number | null) => {
    const others = green.filter((r) => !laneIs(r, impact));
    const base: Row = { from_node: fromN, to_node: toN, flow, impact, soft: soft ? "true" : "false" };
    if (soft && penalty != null && penalty > 0) base.penalty = penalty;
    const rows: Row[] =
      lim == null
        ? [{ ...base, limit: 0 }]
        : typeof lim === "number"
          ? [{ ...base, limit: lim }]
          : Object.entries(lim).map(([y, v]) => ({ ...base, year: Number(y), limit: v }));
    setGreen([...others, ...rows]);
  };
  const addGreen = (impact: string) => commitGreen(impact, 0, true, null);
  const removeGreen = (impact: string) => setGreen(green.filter((r) => !laneIs(r, impact)));
  // Sibling routes on the SAME lane (from, to, flow) — the modal alternatives the
  // optimiser splits the lane's flow across. Modes already on the lane can't be re-added.
  const siblings = routes.filter(
    (r) => s(r.from_node) === s(route.from_node) && s(r.to_node) === s(route.to_node) && s(r.flow) === flow,
  );
  const usedModes = new Set(siblings.map((r) => s(r.mode) || "sea"));
  const addableModes = MODES.filter((m) => !usedModes.has(m.value));
  const routeMode = s(route.mode) || "sea";
  const candidates = fleetRoutes.filter((r) => s(r.process) === proc);
  const candIds = new Set(candidates.map((r) => fleetId(r)));
  // A fleet's mode MUST match the route's mode — a rail route only offers trains, a sea
  // route only ships. Keeps candidates physically consistent with the lane.
  const addable = fleets.filter((f) => !candIds.has(fleetId(f)) && (s(f.mode) || "sea") === routeMode);
  const addCandidate = (fid: string) => { if (fid && !candIds.has(fid)) setFleetRoutes([...fleetRoutes, { process: proc, fleet_id: fid }]); };
  const removeCandidate = (fid: string) => setFleetRoutes(fleetRoutes.filter((r) => !(s(r.process) === proc && fleetId(r) === fid)));
  const row = (lbl: string, el: React.ReactNode, info?: string) => (<label className="field-row" style={{ marginTop: 6 }}><span className="muted">{lbl} {info && <InfoTooltip text={info} />}</span><div style={{ flex: 1 }}>{el}</div></label>);
  return (
    <FloatingPanel title="route" width={360} onClose={onClose}>
      <div style={{ padding: "12px 14px" }}>
        <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>{labelOf(s(route.from_node))} ↔ {labelOf(s(route.to_node))}</div>
        <div className="muted" style={{ fontSize: "0.74rem", marginBottom: 6 }}>
          {flow ? <>flow <b style={{ color: "var(--text)" }}>{flow}</b> · made physical (otherwise it teleports)</> : "direct transport process"}
        </div>
        {row("mode", <SearchSelect value={s(route.mode) || "sea"} onChange={(v) => onChange({ mode: v })} options={MODES} />, "Sea follows real sea lanes (searoute, via Suez/Panama); road/rail use great-circle × a detour factor. Sets the route's distance basis.")}
        {row("distance", <input className="field-input" style={{ width: "100%" }} type="number" placeholder="auto · from the ports" value={s(route.distance)} onChange={(e) => onChange({ distance: blank(e.target.value) })} />, "Leave blank to derive it from the two ports (sea = searoute length; land = great-circle × factor). Override to pin a known distance.")}
        {flow && (
          <div className="rail-section" style={{ marginTop: 10 }}>
            <div className="rail-head">Modes on this lane <InfoTooltip text="Several transport modes (sea, rail, road…) can serve the SAME lane. The optimiser splits the lane's flow across them and picks the cheapest feasible mix — so a rail route alongside a sea one is a real alternative, not just a redraw. Add a mode to give it that choice." /></div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, margin: "4px 0 2px" }}>
              {siblings.map((r) => {
                const m = s(r.mode) || "sea";
                const isThis = s(r.process) === proc;
                return (
                  <button key={s(r.process)} className="ghost" disabled={isThis}
                    style={{ fontSize: ".72rem", padding: "1px 8px", borderRadius: 10,
                      border: "1px solid var(--border)", background: isThis ? "var(--accent-soft, var(--border))" : "transparent",
                      fontWeight: isThis ? 600 : 400, opacity: isThis ? 1 : 0.85, cursor: isThis ? "default" : "pointer" }}
                    title={isThis ? "editing this mode" : `edit the ${m} route`}
                    onClick={() => !isThis && onSwitch(s(r.process))}>
                    {m}
                  </button>
                );
              })}
            </div>
            {addableModes.length > 0 &&
              row("add mode", <SearchSelect value="" onChange={(v) => v && onAddMode(v)} options={[{ value: "", label: "— add an alternative mode" }, ...addableModes]} />)}
          </div>
        )}
        <label className="field-row" style={{ marginTop: 10 }}>
          <input type="checkbox" checked={blocked} onChange={(e) => onToggleBlock(e.target.checked)} />
          <span>Block this corridor (scenario) <InfoTooltip text="Close this corridor to test a disruption (e.g. Hormuz / Suez): the route's flow is forced to 0, so the flow must reroute or go undelivered." /></span>
        </label>
        {flow && (
          <div className="rail-section" style={{ marginTop: 8 }}>
            <div className="rail-head">Green corridor <InfoTooltip text="Cap the lane's cargo-weighted transport emission intensity (emissions ÷ cargo moved) for an impact. The optimiser must shift cargo onto cleaner modes/fuels to keep the corridor under the cap — across every mode on the lane. The cap is temporal (set a flat value or vary it by year). Soft = exceedance allowed at a per-unit penalty price; hard = must hold." /></div>
            {cappedImpacts.length === 0 ? (
              <p className="rail-empty" style={{ margin: "2px 0 4px" }}>No cap — transport runs at least cost.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, margin: "4px 0" }}>
                {cappedImpacts.map((imp) => {
                  const soft = softOf(imp);
                  const penalty = penaltyOf(imp);
                  return (
                    <div key={imp} style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <span style={{ minWidth: 40, fontSize: ".74rem", color: "var(--text)" }}>{imp}</span>
                      <TemporalValue value={limitOf(imp)} onChange={(v) => commitGreen(imp, v ?? 0, soft, penalty)}
                        label={`green cap · ${imp}`} unit={`/${flow}`} perYear={false}
                        baseYear={baseYear} periods={periods} variant="text" placeholder="cap…" />
                      <label style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: ".72rem" }} title="soft = exceedance allowed at a penalty; unchecked = hard (must hold)">
                        <input type="checkbox" checked={soft} onChange={(e) => commitGreen(imp, limitOf(imp), e.target.checked, penalty)} />
                        soft
                      </label>
                      {soft && (
                        <input className="field-input" type="number" style={{ width: 72 }} placeholder="penalty"
                          title={`exceedance price (${currency} per unit over the cap)`}
                          value={penalty ?? ""}
                          onChange={(e) => commitGreen(imp, limitOf(imp), true, e.target.value === "" ? null : Number(e.target.value))} />
                      )}
                      <button className="rail-add" title="remove cap" onClick={() => removeGreen(imp)}>✕</button>
                    </div>
                  );
                })}
              </div>
            )}
            {addableImpacts.length > 0 &&
              row("cap impact", <SearchSelect value="" onChange={(v) => v && addGreen(v)} options={[{ value: "", label: "— add an emission cap" }, ...addableImpacts.map((i) => ({ value: i }))]} />)}
          </div>
        )}
        {!blocked && flow && (
          <div className="rail-section" style={{ marginTop: 8 }}>
            <div className="rail-head">Candidate fleets <InfoTooltip text="Fleets that MAY carry this flow — the optimiser picks which one(s) run the route (some, not all). Only fleets of this route's mode are eligible. Leave empty to let it choose from every same-mode fleet carrying this flow." /></div>
            {candidates.length === 0 ? (
              <p className="rail-empty" style={{ margin: "2px 0 4px" }}>Empty — the optimiser may use any {routeMode} fleet carrying "{flow}".</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", margin: "4px 0" }}>
                {candidates.map((r) => {
                  const fid = fleetId(r);
                  return (
                    <div key={fid} className="fleet-ep" style={{ cursor: "default" }}>
                      <span className="fleet-ep-label" style={{ color: "var(--text)" }}>{fleetLabel(fid)}</span>
                      <button className="rail-add" title="remove candidate" onClick={() => removeCandidate(fid)}>✕</button>
                    </div>
                  );
                })}
              </div>
            )}
            {addable.length > 0 && row("add fleet", <SearchSelect value="" onChange={addCandidate} options={[{ value: "", label: "— add a candidate" }, ...addable.map((f) => ({ value: fleetId(f), label: fleetLabel(fleetId(f)) }))]} />)}
          </div>
        )}
      </div>
    </FloatingPanel>
  );
}
