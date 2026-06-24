// Fleet designer — map-first, sharing the Value-chain's `nodes` tree (interlinked).
// THREE panes: LEFT rail = fleets only (a flexible alliance→company→fleet tree),
// CENTER = the world map (ports + routes), RIGHT rail = the facility structure
// (ports/facilities). Editing is via FloatingPanel pop-ups (the value-chain
// approach). It reuses the `builder` rail layout + app tokens — no bespoke design.

import { useEffect, useMemo, useState } from "react";
import { useDialogs } from "../features/controls/Dialog";
import { FloatingPanel } from "../layout/FloatingPanel";
import { Resizer } from "../layout/Resizer";
import { SearchSelect } from "../features/controls/SearchSelect";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import type { TreeAction, TreeMoveEvent, TreeNode } from "../features/tree/types";
import { parseNodes } from "../lib/groupGraph";
import { MODES, makeProjection } from "../features/fleet/basemap";
import { FleetMap, type MapPort, type MapRoute } from "../features/fleet/FleetMap";
import { buildCoordMap, facilityTreeNodes, fleetId, fleetTreeNodes } from "../features/fleet/fleetGraph";
import type { Row, Workbook } from "../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const num = (v: unknown): number => (v == null || v === "" ? 0 : Number(v) || 0);
const blank = (v: string): number | string => (v === "" ? "" : Number(v));
const has = (v: unknown): boolean => v != null && v !== "";
let _ctr = 0;
const genId = (p: string): string => `${p}_${Date.now().toString(36)}${(_ctr++).toString(36)}`;

type Edit = { kind: "fleet" | "node" | "route"; id: string } | null;

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
  const [leftW, setLeftW] = useState(240);
  const [rightW, setRightW] = useState(240);
  const [edit, setEdit] = useState<Edit>(null);
  const [pendingFrom, setPendingFrom] = useState<string | null>(null);
  const [newMode, setNewMode] = useState("sea");

  const projection = useMemo(() => makeProjection(), []);
  const nodes = useMemo(() => parseNodes(workbook), [workbook]);
  const nodeById = useMemo(() => new Map(nodes.map((nd) => [nd.id, nd])), [nodes]);
  const fleets = useMemo(() => (workbook.fleet ?? []) as Row[], [workbook]);
  const routes = useMemo(() => (workbook.routes ?? []) as Row[], [workbook]);
  const fleetRoutes = useMemo(() => (workbook.fleet_routes ?? []) as Row[], [workbook]);
  const commodities = useMemo(() => (workbook.commodities ?? []).map((r) => s(r.commodity_id)).filter(Boolean), [workbook]);
  const coord = useMemo(() => buildCoordMap(workbook), [workbook]);
  const fleetByNode = useMemo(() => new Map(fleets.map((f) => [fleetId(f), f])), [fleets]);
  const fleetIds = useMemo(() => new Set(fleetByNode.keys()), [fleetByNode]);

  const leftTree = useMemo(() => fleetTreeNodes(nodes, fleetIds, fleetByNode), [nodes, fleetIds, fleetByNode]);
  const rightTree = useMemo(() => facilityTreeNodes(nodes, fleetIds, coord), [nodes, fleetIds, coord]);

  const ports = useMemo<MapPort[]>(
    () => [...coord.entries()].map(([id, c]) => ({ id, label: nodeById.get(id)?.label ?? id, ...c })),
    [coord, nodeById],
  );
  const mapRoutes = useMemo<MapRoute[]>(
    () =>
      routes
        .map((r) => {
          const from = coord.get(s(r.from_node));
          const to = coord.get(s(r.to_node));
          return from && to ? { process: s(r.process), from, to, blocked: s(r.blocked) === "true", alt: has(r.alternative_of) } : null;
        })
        .filter((r): r is MapRoute => r !== null),
    [routes, coord],
  );

  // Esc clears a pending connect.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setPendingFrom(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ── workbook writes ──────────────────────────────────────────────────────────
  const setSheet = (wb: Workbook, sheet: string, rows: Row[]): Workbook => ({ ...wb, [sheet]: rows });
  const patchNode = (id: string, p: Row) => setWorkbook(setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (s(r.node_id) === id ? { ...r, ...p } : r))));
  const patchFleet = (id: string, p: Row) => setWorkbook(setSheet(workbook, "fleet", fleets.map((r) => (fleetId(r) === id ? { ...r, ...p } : r))));
  const patchRoute = (proc: string, p: Row) => setWorkbook(setSheet(workbook, "routes", routes.map((r) => (s(r.process) === proc ? { ...r, ...p } : r))));

  const descendantsOf = (id: string): Set<string> => {
    const out = new Set<string>([id]);
    let added = true;
    while (added) { added = false; for (const nd of nodes) if (nd.parentId && out.has(nd.parentId) && !out.has(nd.id)) { out.add(nd.id); added = true; } }
    return out;
  };

  // ── structure mutations (shared `nodes`/`fleet` sheets) ──────────────────────
  async function addGroup(parentId: string | null) {
    const label = (await prompt({ title: "Add group", label: "name", placeholder: "e.g. Alliance, Carrier Co." }))?.trim();
    if (!label) return;
    const level = (await prompt({ title: "Level", label: "level", defaultValue: parentId ? "company" : "alliance", placeholder: "alliance / company / … (your own)" }))?.trim() || "";
    const id = genId("n");
    setWorkbook(setSheet(workbook, "nodes", [...(workbook.nodes ?? []), { node_id: id, parent_id: parentId, kind: "group", level, label }]));
    if (parentId) setExpL((p) => new Set(p).add(parentId));
  }
  async function addFleet(parentId: string) {
    const label = (await prompt({ title: "Add fleet", label: "name", placeholder: "e.g. Panamax bulkers" }))?.trim();
    if (!label) return;
    const id = genId("flt");
    // A fleet node is kind=group (a benign container) so the hierarchy validator
    // doesn't demand a machines row; the fleet tree renders it as a leaf via its
    // `fleet` row, not its node kind.
    let wb = setSheet(workbook, "nodes", [...(workbook.nodes ?? []), { node_id: id, parent_id: parentId, kind: "group", level: "fleet", label }]);
    wb = setSheet(wb, "fleet", [...fleets, { fleet_id: id, company: parentId, mode: "sea", count: 1 }]);
    setWorkbook(wb);
    setExpL((p) => new Set(p).add(parentId));
    setSelId(id);
    setEdit({ kind: "fleet", id });
  }
  async function addFacilityGroup(parentId: string | null) {
    const label = (await prompt({ title: "Add group", label: "name", placeholder: "e.g. Korea, Ports" }))?.trim();
    if (!label) return;
    const id = genId("n");
    setWorkbook(setSheet(workbook, "nodes", [...(workbook.nodes ?? []), { node_id: id, parent_id: parentId, kind: "group", level: "", label }]));
    if (parentId) setExpR((p) => new Set(p).add(parentId));
  }
  async function addPort(parentId: string | null) {
    const label = (await prompt({ title: "Add port", label: "name", placeholder: "e.g. Busan, Rotterdam" }))?.trim();
    if (!label) return;
    const id = genId("port");
    setWorkbook(setSheet(workbook, "nodes", [...(workbook.nodes ?? []), { node_id: id, parent_id: parentId, kind: "machine", level: "port", label, lon: 0, lat: 20 }]));
    if (parentId) setExpR((p) => new Set(p).add(parentId));
    setSelId(id);
    setEdit({ kind: "node", id });
  }
  async function renameNode(id: string) {
    const next = (await prompt({ title: "Rename", label: "name", defaultValue: nodeById.get(id)?.label ?? id }))?.trim();
    if (next) patchNode(id, { label: next });
  }
  async function duplicateFleet(id: string, times: number) {
    const src = fleetByNode.get(id);
    const nd = nodeById.get(id);
    if (!src || !nd) return;
    const newNodes: Row[] = [];
    const newFleets: Row[] = [];
    for (let i = 1; i <= times; i++) {
      const nid = genId("flt");
      newNodes.push({ node_id: nid, parent_id: nd.parentId, kind: "group", level: "fleet", label: times === 1 ? `${nd.label} copy` : `${nd.label} #${i}` });
      newFleets.push({ ...src, fleet_id: nid, archetype: "" });
    }
    let wb = setSheet(workbook, "nodes", [...(workbook.nodes ?? []), ...newNodes]);
    wb = setSheet(wb, "fleet", [...fleets, ...newFleets]);
    setWorkbook(wb);
  }
  async function deleteNode(id: string) {
    const doomed = descendantsOf(id);
    if (!(await confirm({ title: "Delete", message: `Delete '${nodeById.get(id)?.label ?? id}' and everything under it?`, danger: true, confirmLabel: "Delete" }))) return;
    const keptRoutes = routes.filter((r) => !doomed.has(s(r.from_node)) && !doomed.has(s(r.to_node)));
    const keptProcs = new Set(keptRoutes.map((r) => s(r.process)));
    let wb = setSheet(workbook, "nodes", (workbook.nodes ?? []).filter((r) => !doomed.has(s(r.node_id))));
    wb = setSheet(wb, "fleet", fleets.filter((r) => !doomed.has(fleetId(r))));
    wb = setSheet(wb, "routes", keptRoutes);
    wb = setSheet(wb, "fleet_routes", fleetRoutes.filter((r) => keptProcs.has(s(r.process)) && !doomed.has(fleetId(r))));
    setWorkbook(wb);
    if (selId && doomed.has(selId)) { setSelId(null); setEdit(null); }
  }
  function onMove(e: TreeMoveEvent) {
    const newParent = e.position === "inside" ? e.targetId : nodeById.get(e.beforeSiblingId ?? "")?.parentId ?? null;
    if (e.dragId === newParent) return;
    let wb = setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (s(r.node_id) === e.dragId ? { ...r, parent_id: newParent } : r)));
    if (fleetByNode.has(e.dragId)) wb = setSheet(wb, "fleet", fleets.map((r) => (fleetId(r) === e.dragId ? { ...r, company: newParent ?? "" } : r)));
    setWorkbook(wb);
  }

  // ── map: connect two ports into a route ──────────────────────────────────────
  function connect(from: string, to: string) {
    if (from === to) return;
    const proc = `${from}__${to}`;
    if (!routes.some((r) => s(r.process) === proc))
      setWorkbook(setSheet(workbook, "routes", [...routes, { process: proc, from_node: from, to_node: to, mode: newMode }]));
    setSelId(proc);
    setEdit({ kind: "route", id: proc });
  }
  function onClickPort(id: string) {
    if (pendingFrom && pendingFrom !== id) { connect(pendingFrom, id); setPendingFrom(null); }
    else { setPendingFrom(id); setSelId(id); setEdit({ kind: "node", id }); }
  }

  // Block a corridor: detach its single fleet assignment (stash to restore) so the
  // optimiser genuinely cannot use it; `blocked` alone is inert backend-side.
  function toggleBlock(proc: string, on: boolean) {
    let wb = workbook;
    if (on) {
      const row = fleetRoutes.find((r) => s(r.process) === proc);
      wb = setSheet(wb, "routes", routes.map((r) => (s(r.process) === proc ? { ...r, blocked: "true", blocked_fleet: row ? JSON.stringify(row) : "" } : r)));
      if (row) wb = setSheet(wb, "fleet_routes", fleetRoutes.filter((r) => r !== row));
    } else {
      const r0 = routes.find((r) => s(r.process) === proc);
      const stash = r0 && has(r0.blocked_fleet) ? (JSON.parse(s(r0.blocked_fleet)) as Row) : null;
      wb = setSheet(wb, "routes", routes.map((r) => (s(r.process) === proc ? { ...r, blocked: "", blocked_fleet: "" } : r)));
      if (stash) wb = setSheet(wb, "fleet_routes", [...fleetRoutes, stash]);
    }
    setWorkbook(wb);
  }

  // ── tree actions ─────────────────────────────────────────────────────────────
  const leftActions = (n: TreeNode): TreeAction[] =>
    n.kind === "machine"
      ? [{ id: "edit", label: "Edit" }, { id: "dup", label: "Duplicate" }, { id: "dupN", label: "Duplicate ×N…" }, { id: "rename", label: "Rename" }, { id: "delete", label: "Delete", danger: true }]
      : [{ id: "add-fleet", label: "Add fleet" }, { id: "add-group", label: "Add group inside" }, { id: "rename", label: "Rename", separatorBefore: true }, { id: "delete", label: "Delete", danger: true }];
  const onLeftAction = (a: string, n: TreeNode) => {
    if (a === "add-fleet") void addFleet(n.id);
    else if (a === "add-group") void addGroup(n.id);
    else if (a === "rename") void renameNode(n.id);
    else if (a === "delete") void deleteNode(n.id);
    else if (a === "edit") setEdit({ kind: "fleet", id: n.id });
    else if (a === "dup") void duplicateFleet(n.id, 1);
    else if (a === "dupN") void (async () => { const x = await prompt({ title: "Duplicate ×N", label: "how many copies", defaultValue: "10" }); const t = Math.max(1, Math.round(Number(x) || 0)); if (t) duplicateFleet(n.id, t); })();
  };
  const rightActions = (n: TreeNode): TreeAction[] =>
    n.kind === "machine"
      ? [{ id: "edit", label: "Edit" }, { id: "rename", label: "Rename" }, { id: "delete", label: "Delete", danger: true }]
      : [{ id: "add-port", label: "Add port" }, { id: "add-group", label: "Add group inside" }, { id: "rename", label: "Rename", separatorBefore: true }, { id: "delete", label: "Delete", danger: true }];
  const onRightAction = (a: string, n: TreeNode) => {
    if (a === "add-port") void addPort(n.id);
    else if (a === "add-group") void addFacilityGroup(n.id);
    else if (a === "rename") void renameNode(n.id);
    else if (a === "delete") void deleteNode(n.id);
    else if (a === "edit") setEdit({ kind: "node", id: n.id });
  };

  const editRoute = edit?.kind === "route" ? routes.find((r) => s(r.process) === edit.id) : undefined;

  return (
    <div className="view-full builder">
      <div className="builder-body">
        <aside className="builder-rail" style={{ width: leftW }}>
          <div className="rail-head-row">
            <span className="rail-head">Fleets</span>
            <button className="rail-add" title="add an alliance / company group" onClick={() => void addGroup(null)}>＋</button>
          </div>
          <div className="rail-scroll">
            <TreeExplorer nodes={leftTree} selectedId={selId} expandedIds={expL}
              onToggle={(id, e) => setExpL((p) => { const m = new Set(p); e ? m.add(id) : m.delete(id); return m; })}
              onSelect={(id) => { setSelId(id); if (fleetIds.has(id)) setEdit({ kind: "fleet", id }); }}
              actionsFor={leftActions} onContextAction={onLeftAction} onMove={onMove}
              emptyHint="Empty — ＋ to add an alliance / company, then add fleets inside." />
          </div>
          <div className="rail-foot">Right-click a group to add a company or fleet · drag to re-org</div>
        </aside>
        <Resizer side="left" width={leftW} setWidth={setLeftW} min={200} max={420} />

        <main className="builder-canvas">
          <div className="view-head">
            <div className="eyebrow">fleet</div>
            <span className="view-status">{pendingFrom ? "click a destination port to connect (Esc cancels)" : "click two ports to lay a route · drag a port to move it"}</span>
            <span style={{ flex: 1 }} />
            <label className="muted" style={{ display: "flex", gap: 6, alignItems: "center", fontSize: "0.74rem" }}>
              new route
              <div style={{ width: 130 }}><SearchSelect value={newMode} onChange={setNewMode} options={MODES} /></div>
            </label>
          </div>
          <div style={{ flex: 1, minHeight: 0, display: "flex", padding: "10px 14px" }}>
            <FleetMap projection={projection} ports={ports} routes={mapRoutes} selId={selId} pendingFrom={pendingFrom}
              onMovePort={(id, lon, lat) => patchNode(id, { lon, lat })}
              onClickPort={onClickPort}
              onSelectRoute={(proc) => { setSelId(proc); setEdit({ kind: "route", id: proc }); }}
              onBackground={() => setPendingFrom(null)} />
          </div>
          {ports.length === 0 && <p className="view-lead" style={{ padding: "0 14px" }}>No ports yet — right-click a group in the <b>Facilities</b> rail → Add port, then drag it onto its place.</p>}
        </main>

        <Resizer side="right" width={rightW} setWidth={setRightW} min={200} max={420} />
        <aside className="builder-rail is-right" style={{ width: rightW }}>
          <div className="rail-head-row">
            <span className="rail-head">Facilities</span>
            <button className="rail-add" title="add a facility group" onClick={() => void addFacilityGroup(null)}>＋</button>
          </div>
          <div className="rail-scroll">
            <TreeExplorer nodes={rightTree} selectedId={selId} expandedIds={expR}
              onToggle={(id, e) => setExpR((p) => { const m = new Set(p); e ? m.add(id) : m.delete(id); return m; })}
              onSelect={(id) => { setSelId(id); setEdit({ kind: "node", id }); }}
              actionsFor={rightActions} onContextAction={onRightAction} onMove={onMove}
              emptyHint="Empty — ＋ to add a facility group, then a port." />
          </div>
          <div className="rail-foot">Ports &amp; facilities — drag a port on the map to place it</div>
        </aside>
      </div>

      {edit?.kind === "fleet" && fleetByNode.get(edit.id) && (
        <FleetPanel fleet={fleetByNode.get(edit.id)!} label={nodeById.get(edit.id)?.label ?? edit.id} commodities={commodities}
          onRename={(v) => patchNode(edit.id, { label: v })} onChange={(p) => patchFleet(edit.id, p)} onClose={() => setEdit(null)} />
      )}
      {edit?.kind === "node" && nodeById.get(edit.id) && (
        <NodePanel id={edit.id} label={nodeById.get(edit.id)!.label} level={nodeById.get(edit.id)!.level} coord={coord.get(edit.id)}
          onRename={(v) => patchNode(edit.id, { label: v })} onLevel={(v) => patchNode(edit.id, { level: v })} onCoord={(p) => patchNode(edit.id, p)} onClose={() => setEdit(null)} />
      )}
      {editRoute && (
        <RoutePanel route={editRoute} routes={routes} ports={ports} fleets={fleets} fleetRoutes={fleetRoutes}
          labelOf={(id) => nodeById.get(id)?.label ?? id}
          onChange={(p) => patchRoute(edit!.id, p)} onToggleBlock={(on) => toggleBlock(edit!.id, on)}
          setFleetRoutes={(rows) => setWorkbook(setSheet(workbook, "fleet_routes", rows))}
          onDelete={() => { setWorkbook(setSheet(setSheet(workbook, "routes", routes.filter((r) => s(r.process) !== edit!.id)), "fleet_routes", fleetRoutes.filter((r) => s(r.process) !== edit!.id))); setEdit(null); }}
          onClose={() => setEdit(null)} />
      )}
      {dialogNode}
    </div>
  );
}

// ── Pop-up editors (FloatingPanel — the value-chain approach) ─────────────────
const FIELDS: [string, string][] = [
  ["mode", "mode"], ["cargo", "cargo (stream)"], ["fuel", "fuel (stream)"], ["efficiency", "efficiency (fuel/cargo/dist)"],
  ["count", "units"], ["ship_size", "cargo / voyage"], ["speed", "speed (dist/day)"], ["turnaround_days", "turnaround (days)"],
  ["operating_days", "operating days/yr"], ["capacity", "flat capacity/unit"], ["build_year", "build year"], ["close_year", "close year"], ["lifespan", "lifespan (yr)"],
];

function FleetPanel({ fleet, label, commodities, onRename, onChange, onClose }: { fleet: Row; label: string; commodities: string[]; onRename: (v: string) => void; onChange: (p: Row) => void; onClose: () => void }) {
  return (
    <FloatingPanel title="fleet" width={360} onClose={onClose}>
      <div style={{ padding: "12px 14px" }}>
        <input className="title-input" value={label} onChange={(e) => onRename(e.target.value)} />
        {FIELDS.map(([key, lbl]) => (
          <label className="field-row" key={key} style={{ marginTop: 6 }}>
            <span className="muted">{lbl}</span>
            {key === "mode" ? (
              <div style={{ flex: 1 }}><SearchSelect value={s(fleet.mode) || "sea"} onChange={(v) => onChange({ mode: v })} options={MODES} /></div>
            ) : key === "cargo" || key === "fuel" ? (
              <div style={{ flex: 1 }}><SearchSelect value={s(fleet[key])} onChange={(v) => onChange({ [key]: v })} options={commodities.map((c) => ({ value: c }))} /></div>
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
        <p className="rail-empty" style={{ marginTop: 8 }}>{isPort ? "Drag the marker on the map, or click it then another port to lay a route." : "Give this node a longitude/latitude to place it on the map as a port."}</p>
        <input type="hidden" value={id} readOnly />
      </div>
    </FloatingPanel>
  );
}

function RoutePanel({ route, routes, ports, fleets, fleetRoutes, labelOf, onChange, onToggleBlock, setFleetRoutes, onDelete, onClose }: {
  route: Row; routes: Row[]; ports: MapPort[]; fleets: Row[]; fleetRoutes: Row[]; labelOf: (id: string) => string;
  onChange: (p: Row) => void; onToggleBlock: (on: boolean) => void; setFleetRoutes: (rows: Row[]) => void; onDelete: () => void; onClose: () => void;
}) {
  const proc = s(route.process);
  const blocked = s(route.blocked) === "true";
  const others = routes.filter((r) => s(r.process) !== proc);
  const assign = fleetRoutes.find((r) => s(r.process) === proc);
  const cur = assign ? fleetId(assign) : "";
  const fixed = !!assign && num(assign.min_units) > 0 && has(assign.max_units) && num(assign.min_units) === num(assign.max_units);
  const setFleet = (fid: string) => setFleetRoutes(fid ? [...fleetRoutes.filter((r) => s(r.process) !== proc), { process: proc, fleet_id: fid }] : fleetRoutes.filter((r) => s(r.process) !== proc));
  const setFix = (mode: string) => assign && setFleetRoutes(fleetRoutes.map((r) => (s(r.process) === proc ? (mode === "fixed" ? { ...r, min_units: num(r.max_units) || 1, max_units: num(r.max_units) || 1 } : { ...r, min_units: "", max_units: "" }) : r)));
  const row = (lbl: string, el: React.ReactNode) => (<label className="field-row" style={{ marginTop: 6 }}><span className="muted">{lbl}</span><div style={{ flex: 1 }}>{el}</div></label>);
  return (
    <FloatingPanel title="route" width={360} onClose={onClose}>
      <div style={{ padding: "12px 14px" }}>
        <div style={{ fontWeight: 600, fontSize: "0.9rem", marginBottom: 4 }}>{labelOf(s(route.from_node))} → {labelOf(s(route.to_node))}</div>
        {row("from", <SearchSelect value={s(route.from_node)} onChange={(v) => onChange({ from_node: v })} options={ports.map((p) => ({ value: p.id, label: p.label }))} />)}
        {row("to", <SearchSelect value={s(route.to_node)} onChange={(v) => onChange({ to_node: v })} options={ports.map((p) => ({ value: p.id, label: p.label }))} />)}
        {row("mode", <SearchSelect value={s(route.mode) || "sea"} onChange={(v) => onChange({ mode: v })} options={MODES} />)}
        {row("distance", <input className="field-input" style={{ width: "100%" }} type="number" placeholder="auto · great-circle preview" value={s(route.distance)} onChange={(e) => onChange({ distance: blank(e.target.value) })} />)}
        {row("alternative of", <SearchSelect value={s(route.alternative_of)} onChange={(v) => onChange({ alternative_of: v })} options={[{ value: "", label: "— (primary)" }, ...others.map((r) => ({ value: s(r.process), label: `${labelOf(s(r.from_node))}→${labelOf(s(r.to_node))}` }))]} />)}
        <label className="field-row" style={{ marginTop: 10 }}>
          <input type="checkbox" checked={blocked} onChange={(e) => onToggleBlock(e.target.checked)} />
          <span>Block this corridor (scenario)</span>
        </label>
        {!blocked && (
          <div className="rail-section" style={{ marginTop: 8 }}>
            <div className="rail-head">Fleet on this route</div>
            {row("fleet", <SearchSelect value={cur} onChange={setFleet} options={[{ value: "", label: "— none" }, ...fleets.map((f) => ({ value: fleetId(f), label: labelOf(fleetId(f)) }))]} />)}
            {assign && row("assignment", <SearchSelect value={fixed ? "fixed" : "flexible"} onChange={setFix} options={[{ value: "flexible", label: "Flexible (poolable)" }, { value: "fixed", label: "Fixed (locked here)" }]} />)}
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
          <button className="ghost" style={{ color: "var(--danger)" }} onClick={onDelete}>Delete route</button>
        </div>
      </div>
    </FloatingPanel>
  );
}
