// Fleet designer — the transport layer on a map. The LEFT rail lists a company's
// fleets (a fleet = a pool of interchangeable carriers: mode, fuel, efficiency,
// cargo + lifecycle). The MAP plots ports (nodes with lon/lat) and the routes the
// fleets deliver along. Routes carry a distance (authored, or derived from the
// endpoints at solve) that drives both how many carriers a lane needs and the fuel
// it burns. Authoring lives here; the Optimisation tab just runs the solve.

import { useMemo, useState } from "react";
import { SearchSelect } from "../features/controls/SearchSelect";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import type { TreeAction, TreeMoveEvent, TreeNode } from "../features/tree/types";
import type { Row, Workbook } from "../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const num = (v: unknown): number => (v == null || v === "" ? 0 : Number(v) || 0);
const numOrBlank = (v: string): number | string => (v === "" ? "" : Number(v));

const MODES = [
  { value: "sea", label: "Sea (searoute)" },
  { value: "road", label: "Road (×1.4)" },
  { value: "rail", label: "Rail (×1.2)" },
  { value: "air", label: "Air" },
];

const fleetId = (r: Row): string => s(r.fleet_id) || s(r.archetype);

// Equirectangular projection of (lon, lat) onto the SVG canvas.
const MAP_W = 720;
const MAP_H = 360;
const projX = (lon: number): number => ((lon + 180) / 360) * MAP_W;
const projY = (lat: number): number => ((90 - lat) / 180) * MAP_H;

export function FleetDesignerView({
  workbook,
  setWorkbook,
}: {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
}) {
  const setSheet = (sheet: string, rows: Row[]) => setWorkbook({ ...workbook, [sheet]: rows });

  const fleets = useMemo(() => (workbook.fleet ?? []) as Row[], [workbook]);
  const routes = useMemo(() => (workbook.routes ?? []) as Row[], [workbook]);
  const fleetRoutes = useMemo(() => (workbook.fleet_routes ?? []) as Row[], [workbook]);

  const commodities = useMemo(
    () => (workbook.commodities ?? []).map((r) => s(r.commodity_id)).filter(Boolean),
    [workbook],
  );
  const procIds = useMemo(() => {
    const set = new Set<string>();
    for (const r of workbook.processes ?? []) if (s(r.process_id)) set.add(s(r.process_id));
    for (const r of workbook.machines ?? []) if (s(r.machine_id)) set.add(s(r.machine_id));
    return [...set];
  }, [workbook]);
  const companies = useMemo(() => {
    const set = new Set<string>();
    for (const r of fleets) if (s(r.company)) set.add(s(r.company));
    for (const r of workbook.processes ?? []) if (s(r.company)) set.add(s(r.company));
    return [...set];
  }, [fleets, workbook]);

  // Nodes that can be geo-placed: every node, with its current coordinates (if any).
  const allNodes = useMemo(() => {
    const out: { id: string; label: string }[] = [];
    for (const r of workbook.nodes ?? []) {
      const id = s(r.node_id);
      if (id) out.push({ id, label: s(r.label) || id });
    }
    return out;
  }, [workbook]);
  const coords = useMemo(() => {
    const m = new Map<string, { lon: number; lat: number; label: string }>();
    for (const r of workbook.nodes ?? []) {
      const id = s(r.node_id);
      if (id && r.lon != null && r.lon !== "" && r.lat != null && r.lat !== "")
        m.set(id, { lon: num(r.lon), lat: num(r.lat), label: s(r.label) || id });
    }
    return m;
  }, [workbook]);
  // Ports actually used on the map: anything with coords, plus any route endpoint.
  const portIds = useMemo(() => {
    const set = new Set<string>(coords.keys());
    for (const r of routes) {
      if (s(r.from_node)) set.add(s(r.from_node));
      if (s(r.to_node)) set.add(s(r.to_node));
    }
    return [...set];
  }, [coords, routes]);

  // ── Fleet tree (company groups → fleet leaves) + selection ─────────────────
  const [selId, setSelId] = useState<string>("");
  const sel = fleets.find((f) => fleetId(f) === selId) ?? fleets[0];
  const selIndex = sel ? fleets.indexOf(sel) : -1;

  const coKey = (c: string) => `co:${c}`;
  const treeNodes = useMemo<TreeNode[]>(() => {
    const out: TreeNode[] = [];
    const groups = new Set<string>();
    for (const f of fleets) groups.add(s(f.company));
    if (groups.size === 0) groups.add("");
    for (const c of [...groups].sort()) {
      out.push({
        id: coKey(c),
        parentId: null,
        kind: "group",
        label: c || "(no company)",
        level: "company",
        hasChildren: true,
        droppable: true,
        draggable: false,
      });
    }
    for (const f of fleets) {
      const id = fleetId(f);
      out.push({
        id: `fl:${id}`,
        parentId: coKey(s(f.company)),
        kind: "leaf",
        label: id,
        level: `${s(f.mode) || "—"} · ${s(f.cargo) || "no cargo"} · ${num(f.count)} units`,
        hasChildren: false,
        draggable: true,
      });
    }
    return out;
  }, [fleets]);

  const groupIds = useMemo(() => treeNodes.filter((n) => n.kind === "group").map((n) => n.id), [treeNodes]);
  const [expanded, setExpanded] = useState<Set<string> | null>(null);
  const exp = expanded ?? new Set(groupIds); // default: all companies expanded

  const patchFleet = (i: number, p: Row) =>
    setSheet("fleet", fleets.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const addFleet = (company?: string) => {
    const id = `fleet${fleets.length + 1}`;
    setSheet("fleet", [
      ...fleets,
      { fleet_id: id, company: company ?? sel?.company ?? companies[0] ?? "", mode: "sea", count: 1 },
    ]);
    setSelId(id);
  };
  const delFleet = (i: number) => setSheet("fleet", fleets.filter((_, j) => j !== i));

  const fleetActions = (node: TreeNode): TreeAction[] =>
    node.kind === "group"
      ? [{ id: "add", label: "＋ Add fleet here" }]
      : [{ id: "delete", label: "Delete fleet", danger: true }];
  const onFleetAction = (actionId: string, node: TreeNode) => {
    if (actionId === "add" && node.kind === "group") addFleet(node.id.slice(3));
    else if (actionId === "delete" && node.id.startsWith("fl:")) {
      const i = fleets.findIndex((f) => fleetId(f) === node.id.slice(3));
      if (i >= 0) delFleet(i);
    }
  };
  // Drag a fleet into another company group → reassign its company.
  const onFleetMove = (e: TreeMoveEvent) => {
    if (!e.dragId.startsWith("fl:")) return;
    const fid = e.dragId.slice(3);
    const company = (e.targetId ?? "").startsWith("co:") ? e.targetId!.slice(3) : "";
    const i = fleets.findIndex((f) => fleetId(f) === fid);
    if (i >= 0) patchFleet(i, { company });
  };

  const patchRoute = (i: number, p: Row) =>
    setSheet("routes", routes.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const addRoute = () =>
    setSheet("routes", [...routes, { process: procIds[0] ?? "", mode: "sea" }]);
  const delRoute = (i: number) => setSheet("routes", routes.filter((_, j) => j !== i));

  const patchAssign = (i: number, p: Row) =>
    setSheet("fleet_routes", fleetRoutes.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const addAssign = () =>
    setSheet("fleet_routes", [
      ...fleetRoutes,
      { process: procIds[0] ?? "", fleet_id: fleetId(fleets[0] ?? {}) || "fleet1" },
    ]);
  const delAssign = (i: number) =>
    setSheet("fleet_routes", fleetRoutes.filter((_, j) => j !== i));

  const setNodeCoord = (id: string, key: "lon" | "lat", v: string) =>
    setSheet(
      "nodes",
      (workbook.nodes ?? []).map((r) => (s(r.node_id) === id ? { ...r, [key]: numOrBlank(v) } : r)),
    );

  const cell: React.CSSProperties = { padding: "2px 4px" };
  const labeled = (label: string, el: React.ReactNode) => (
    <label style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: "0.72rem" }}>
      <span className="muted">{label}</span>
      {el}
    </label>
  );

  return (
    <div className="body-row" style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      {/* LEFT RAIL — the company's fleets */}
      <aside
        style={{
          width: 290,
          minWidth: 290,
          borderRight: "1px solid var(--border)",
          overflow: "auto",
          padding: "14px 14px 40px",
        }}
      >
        <div className="eyebrow">fleet</div>
        <h3 className="section-title" style={{ marginTop: 2 }}>Fleets</h3>
        <button className="ghost" style={{ margin: "4px 0 8px" }} onClick={() => addFleet()}>＋ add fleet</button>
        {fleets.length === 0 ? (
          <p className="muted" style={{ fontSize: "0.78rem" }}>No fleets — ＋ add one.</p>
        ) : (
          <TreeExplorer
            nodes={treeNodes}
            selectedId={sel ? `fl:${fleetId(sel)}` : null}
            expandedIds={exp}
            onToggle={(id, e) =>
              setExpanded(() => {
                const m = new Set(exp);
                if (e) m.add(id);
                else m.delete(id);
                return m;
              })
            }
            onSelect={(id) => {
              if (id.startsWith("fl:")) setSelId(id.slice(3));
            }}
            actionsFor={fleetActions}
            onContextAction={onFleetAction}
            onMove={onFleetMove}
            canDrop={(dragId, targetId) => dragId.startsWith("fl:") && (targetId ?? "").startsWith("co:")}
          />
        )}

        {/* Selected fleet editor */}
        {sel && selIndex >= 0 && (
          <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h4 style={{ margin: 0, fontSize: "0.82rem" }}>{fleetId(sel)}</h4>
              <button className="ghost" title="remove fleet" onClick={() => delFleet(selIndex)}>✕</button>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8 }}>
              {labeled("id", <input value={fleetId(sel)} onChange={(e) => patchFleet(selIndex, { fleet_id: e.target.value, archetype: "" })} />)}
              {labeled("company", <SearchSelect value={s(sel.company)} onChange={(v) => patchFleet(selIndex, { company: v })} options={companies.map((c) => ({ value: c }))} />)}
              {labeled("mode", <SearchSelect value={s(sel.mode) || "sea"} onChange={(v) => patchFleet(selIndex, { mode: v })} options={MODES} />)}
              {labeled("cargo (stream)", <SearchSelect value={s(sel.cargo)} onChange={(v) => patchFleet(selIndex, { cargo: v })} options={commodities.map((c) => ({ value: c }))} />)}
              {labeled("fuel (stream)", <SearchSelect value={s(sel.fuel)} onChange={(v) => patchFleet(selIndex, { fuel: v })} options={commodities.map((c) => ({ value: c }))} />)}
              {labeled("efficiency (fuel/cargo/dist)", <input type="number" value={s(sel.efficiency)} onChange={(e) => patchFleet(selIndex, { efficiency: numOrBlank(e.target.value) })} />)}
              {labeled("units (count)", <input type="number" value={s(sel.count)} onChange={(e) => patchFleet(selIndex, { count: numOrBlank(e.target.value) })} />)}
              {labeled("cargo / voyage", <input type="number" value={s(sel.ship_size)} onChange={(e) => patchFleet(selIndex, { ship_size: numOrBlank(e.target.value) })} />)}
              {labeled("speed (dist/day)", <input type="number" value={s(sel.speed)} onChange={(e) => patchFleet(selIndex, { speed: numOrBlank(e.target.value) })} />)}
              {labeled("turnaround (days)", <input type="number" value={s(sel.turnaround_days)} onChange={(e) => patchFleet(selIndex, { turnaround_days: numOrBlank(e.target.value) })} />)}
              {labeled("operating days/yr", <input type="number" value={s(sel.operating_days)} onChange={(e) => patchFleet(selIndex, { operating_days: numOrBlank(e.target.value) })} />)}
              {labeled("flat capacity/unit", <input type="number" placeholder="(from distance)" value={s(sel.capacity)} onChange={(e) => patchFleet(selIndex, { capacity: numOrBlank(e.target.value) })} />)}
              {labeled("build year", <input type="number" value={s(sel.build_year)} onChange={(e) => patchFleet(selIndex, { build_year: numOrBlank(e.target.value) })} />)}
              {labeled("close year", <input type="number" value={s(sel.close_year)} onChange={(e) => patchFleet(selIndex, { close_year: numOrBlank(e.target.value) })} />)}
              {labeled("lifespan (yr)", <input type="number" value={s(sel.lifespan)} onChange={(e) => patchFleet(selIndex, { lifespan: numOrBlank(e.target.value) })} />)}
            </div>
          </div>
        )}
      </aside>

      {/* MAIN — map + routes/ports/assignment */}
      <main className="main-area" style={{ flex: 1, overflow: "auto", padding: "16px 22px" }}>
        <div className="eyebrow">fleet designer</div>
        <h2 className="view-title">Fleet & routes</h2>
        <p className="view-lead">
          Place ports, draw the routes your fleets sail, and the optimiser decides how many carriers
          each lane needs and the fuel they burn — longer routes cost more ships and more fuel.
        </p>

        {/* Map */}
        <section style={{ marginBottom: 18 }}>
          <svg
            viewBox={`0 0 ${MAP_W} ${MAP_H}`}
            style={{ width: "100%", maxWidth: 860, border: "1px solid var(--border)", borderRadius: 8, background: "var(--surface-2)" }}
          >
            {/* graticule */}
            {[-120, -60, 0, 60, 120].map((lon) => (
              <line key={`v${lon}`} x1={projX(lon)} y1={0} x2={projX(lon)} y2={MAP_H} stroke="var(--border)" strokeWidth={0.5} />
            ))}
            {[-60, -30, 0, 30, 60].map((lat) => (
              <line key={`h${lat}`} x1={0} y1={projY(lat)} x2={MAP_W} y2={projY(lat)} stroke="var(--border)" strokeWidth={0.5} />
            ))}
            <line x1={0} y1={projY(0)} x2={MAP_W} y2={projY(0)} stroke="var(--muted)" strokeWidth={0.7} strokeDasharray="3 3" />
            {/* routes */}
            {routes.map((r, i) => {
              const a = coords.get(s(r.from_node));
              const b = coords.get(s(r.to_node));
              if (!a || !b) return null;
              const [x1, y1] = [projX(a.lon), projY(a.lat)];
              const [x2, y2] = [projX(b.lon), projY(b.lat)];
              return (
                <g key={`r${i}`}>
                  <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--accent)" strokeWidth={1.4} opacity={0.8} />
                  {r.distance != null && r.distance !== "" && (
                    <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 3} fontSize={8} fill="var(--muted)" textAnchor="middle">
                      {Math.round(num(r.distance))} km
                    </text>
                  )}
                </g>
              );
            })}
            {/* ports */}
            {[...coords.entries()].map(([id, p]) => (
              <g key={`p${id}`}>
                <circle cx={projX(p.lon)} cy={projY(p.lat)} r={3.5} fill="var(--accent)" stroke="white" strokeWidth={1} />
                <text x={projX(p.lon) + 5} y={projY(p.lat) + 3} fontSize={9} fill="var(--text)">{p.label}</text>
              </g>
            ))}
          </svg>
          {coords.size === 0 && (
            <p className="muted" style={{ fontSize: "0.76rem" }}>
              No ports placed yet — give nodes a longitude/latitude in the Ports table below.
            </p>
          )}
        </section>

        {/* Ports */}
        <section style={{ marginBottom: 18 }}>
          <h3 className="section-title">Ports (node coordinates)</h3>
          <p className="muted" style={{ fontSize: "0.74rem", margin: "0 0 6px" }}>
            Geo-locate any node so it shows on the map and routes can measure real distance.
          </p>
          <table className="grid" style={{ fontSize: "0.76rem" }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                <th style={{ minWidth: 160 }}>node</th>
                <th>longitude</th>
                <th>latitude</th>
              </tr>
            </thead>
            <tbody>
              {allNodes.map((nd) => {
                const c = coords.get(nd.id);
                return (
                  <tr key={nd.id}>
                    <td style={cell}>{nd.label}</td>
                    <td style={cell}>
                      <input type="number" style={{ width: 100 }} value={c ? c.lon : ""} placeholder="—"
                        onChange={(e) => setNodeCoord(nd.id, "lon", e.target.value)} />
                    </td>
                    <td style={cell}>
                      <input type="number" style={{ width: 100 }} value={c ? c.lat : ""} placeholder="—"
                        onChange={(e) => setNodeCoord(nd.id, "lat", e.target.value)} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>

        {/* Routes */}
        <section style={{ marginBottom: 18 }}>
          <h3 className="section-title" style={{ marginBottom: 2 }}>Routes (physical)</h3>
          <p className="muted" style={{ fontSize: "0.74rem", margin: "0 0 6px" }}>
            Each route is a transport process between two ports. Leave distance blank to derive it
            from the ports (sea via searoute, land via great-circle × a mode factor).
          </p>
          <button className="ghost" style={{ marginBottom: 8 }} onClick={addRoute}>＋ add route</button>
          {routes.length > 0 && (
            <table className="grid" style={{ width: "100%", fontSize: "0.76rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                  <th>route (process)</th><th>from</th><th>to</th><th>mode</th><th>distance (km)</th><th />
                </tr>
              </thead>
              <tbody>
                {routes.map((r, i) => (
                  <tr key={i}>
                    <td style={cell}><SearchSelect value={s(r.process)} onChange={(v) => patchRoute(i, { process: v })} options={procIds.map((o) => ({ value: o }))} /></td>
                    <td style={cell}><SearchSelect value={s(r.from_node)} onChange={(v) => patchRoute(i, { from_node: v })} options={portIds.map((o) => ({ value: o }))} /></td>
                    <td style={cell}><SearchSelect value={s(r.to_node)} onChange={(v) => patchRoute(i, { to_node: v })} options={portIds.map((o) => ({ value: o }))} /></td>
                    <td style={cell}><SearchSelect value={s(r.mode) || "sea"} onChange={(v) => patchRoute(i, { mode: v })} options={MODES} /></td>
                    <td style={cell}><input type="number" style={{ width: 100 }} placeholder="(auto)" value={s(r.distance)} onChange={(e) => patchRoute(i, { distance: numOrBlank(e.target.value) })} /></td>
                    <td><button className="ghost" title="remove" onClick={() => delRoute(i)}>✕</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* Assignment */}
        <section style={{ marginBottom: 22 }}>
          <h3 className="section-title" style={{ marginBottom: 2 }}>Fleet → route assignment</h3>
          <p className="muted" style={{ fontSize: "0.74rem", margin: "0 0 6px" }}>
            Which fleet serves each route. The optimiser assigns whole carriers across a fleet's
            routes, bounded by its in-service units; min/max pin a lane.
          </p>
          <button className="ghost" style={{ marginBottom: 8 }} onClick={addAssign}>＋ assign</button>
          {fleetRoutes.length > 0 && (
            <table className="grid" style={{ fontSize: "0.76rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                  <th>route (process)</th><th>fleet</th><th>min</th><th>max</th><th />
                </tr>
              </thead>
              <tbody>
                {fleetRoutes.map((r, i) => (
                  <tr key={i}>
                    <td style={cell}><SearchSelect value={s(r.process)} onChange={(v) => patchAssign(i, { process: v })} options={procIds.map((o) => ({ value: o }))} /></td>
                    <td style={cell}><SearchSelect value={fleetId(r)} onChange={(v) => patchAssign(i, { fleet_id: v, archetype: "" })} options={fleets.map((f) => ({ value: fleetId(f) }))} /></td>
                    <td style={cell}><input type="number" style={{ width: 64 }} placeholder="0" value={s(r.min_units)} onChange={(e) => patchAssign(i, { min_units: numOrBlank(e.target.value) })} /></td>
                    <td style={cell}><input type="number" style={{ width: 64 }} placeholder="∞" value={s(r.max_units)} onChange={(e) => patchAssign(i, { max_units: numOrBlank(e.target.value) })} /></td>
                    <td><button className="ghost" title="remove" onClick={() => delAssign(i)}>✕</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </main>
    </div>
  );
}
