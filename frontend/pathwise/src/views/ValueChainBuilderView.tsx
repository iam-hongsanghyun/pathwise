// Value-Chain builder — assemble the model as a recursive group hierarchy.
//
// Subgroup chips on top (add/delete at the current level); drill by clicking a
// group on the canvas. A component palette on the left drops FRESH copies of
// library components into the current group (companies never share facilities).
// Couplings wire siblings (with a time lag). Pick an optimisation level and Run:
// the root/system level solves jointly; a sub-level partitions into a coupled
// cascade.

import { useEffect, useMemo, useState } from "react";
import { GroupCanvas } from "../features/topology/GroupCanvas";
import {
  instantiateComponent,
  type LibrarySummary,
  type ComponentLibrary,
  getComponentLibrary,
  listComponentLibraries,
} from "../lib/api/components";
import { getFullModel } from "../lib/api/session";
import { runToCompletion } from "../lib/api/run";
import { childrenOf, parseNodes, type GroupNode } from "../lib/groupGraph";
import { Breadcrumb } from "../layout/Breadcrumb";
import type { Cell, RunResult, Row, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  sessionId: string | null;
  adoptServerModel: (wb: Workbook) => void;
  /** Flush pending local edits to the backend session (so instantiate sees them). */
  flush: () => Promise<void>;
  /** Hand a standard (joint) result to the app shell (→ Analytics view). */
  onJointResult: (r: RunResult) => void;
}

const s = (v: unknown): string => (v == null ? "" : String(v));

/** Cascade (per-level) result shape — distinct from the joint RunResult. */
interface CascadeResult {
  status: string;
  stages: Record<string, { objective?: number | null; status?: string }>;
  couplings: { from: string; to: string; commodity: string; signal: string }[];
  iterations: number;
}
const isCascade = (r: unknown): r is CascadeResult =>
  !!r && typeof r === "object" && "stages" in (r as Record<string, unknown>);

export function ValueChainBuilderView({
  workbook,
  setWorkbook,
  sessionId,
  adoptServerModel,
  flush,
  onJointResult,
}: Props) {
  const [path, setPath] = useState<string[]>([]);
  const [libs, setLibs] = useState<LibrarySummary[]>([]);
  const [openLibId, setOpenLibId] = useState<string | null>(null);
  const [openLib, setOpenLib] = useState<ComponentLibrary | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Run controls
  const [scope, setScope] = useState<string>("system");
  const [baseYear, setBaseYear] = useState<number>(2025);
  const [running, setRunning] = useState<string | null>(null);
  const [cascade, setCascade] = useState<CascadeResult | null>(null);

  useEffect(() => {
    listComponentLibraries()
      .then(setLibs)
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!openLibId) {
      setOpenLib(null);
      return;
    }
    getComponentLibrary(openLibId)
      .then(setOpenLib)
      .catch((e) => setError(String(e)));
  }, [openLibId]);

  const nodes = useMemo(() => parseNodes(workbook), [workbook]);
  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const currentGroupId = path.length ? path[path.length - 1] : null;
  const pathNodes = useMemo(
    () => path.flatMap((id) => (nodeById.has(id) ? [nodeById.get(id)!] : [])),
    [path, nodeById],
  );
  const levelChildren = useMemo(() => childrenOf(nodes, currentGroupId), [nodes, currentGroupId]);
  const subgroups = levelChildren.filter((c) => c.kind === "group");

  // Every designed level present in the tree → the optimisation-level options.
  const levels = useMemo(() => {
    const set = new Set<string>(["system"]);
    for (const n of nodes) if (n.kind === "group" && n.level) set.add(n.level);
    return [...set];
  }, [nodes]);

  // ── Workbook mutations (App debounce-syncs them) ────────────────────────────
  const setSheet = (wb: Workbook, sheet: string, rows: Row[]): Workbook => ({ ...wb, [sheet]: rows });

  function addSubgroup() {
    const label = window.prompt("Subgroup name (e.g. 'Steel sector', 'Steel Co'):", "")?.trim();
    if (!label) return;
    const level =
      window.prompt("Level for this subgroup (free text, e.g. sector, company, facility):", currentGroupId ? "company" : "value_chain")?.trim() || "";
    const taken = new Set(nodes.map((n) => n.id));
    const base = (currentGroupId ? `${currentGroupId}/` : "") + label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
    let id = base || "group";
    let i = 2;
    while (taken.has(id)) id = `${base}_${i++}`;
    const row: Row = { node_id: id, parent_id: currentGroupId, kind: "group", level, label };
    setWorkbook(setSheet(workbook, "nodes", [...(workbook.nodes ?? []), row]));
  }

  function deleteNode(id: string) {
    if (!window.confirm(`Delete '${nodeById.get(id)?.label ?? id}' and everything inside it?`)) return;
    // Collect the subtree (id + all descendants).
    const doomed = new Set<string>([id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const n of nodes) {
        if (n.parentId && doomed.has(n.parentId) && !doomed.has(n.id)) {
          doomed.add(n.id);
          grew = true;
        }
      }
    }
    let wb = setSheet(workbook, "nodes", (workbook.nodes ?? []).filter((r) => !doomed.has(s(r.node_id))));
    wb = setSheet(wb, "machines", (wb.machines ?? []).filter((r) => !doomed.has(s(r.machine_id))));
    wb = setSheet(
      wb,
      "connections",
      (wb.connections ?? []).filter((r) => !doomed.has(s(r.from_node)) && !doomed.has(s(r.to_node))),
    );
    wb = setSheet(wb, "measures", (wb.measures ?? []).filter((r) => !doomed.has(s(r.facility))));
    setWorkbook(wb);
    if (path.includes(id)) setPath(path.slice(0, path.indexOf(id)));
  }

  function renameNode(id: string) {
    const cur = nodeById.get(id);
    const label = window.prompt("Rename:", cur?.label ?? id)?.trim();
    if (!label) return;
    setWorkbook(setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (s(r.node_id) === id ? { ...r, label } : r))));
  }

  async function dropComponent(library: string, component: string) {
    if (!sessionId || !currentGroupId) return;
    setBusy(`${library}/${component}`);
    setError(null);
    try {
      await flush(); // ensure the parent node exists server-side
      await instantiateComponent(sessionId, { library, component, parent_id: currentGroupId });
      adoptServerModel(await getFullModel(sessionId));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  // ── Connections (couplings) at the current level ────────────────────────────
  const levelConnections = useMemo(() => {
    const ids = new Set(levelChildren.map((c) => c.id));
    return (workbook.connections ?? [])
      .map((r, idx) => ({ idx, r }))
      .filter(({ r }) => ids.has(s(r.from_node)) && ids.has(s(r.to_node)));
  }, [workbook, levelChildren]);

  function addConnection(from: string, to: string, commodity: string, lag: number) {
    if (!from || !to || from === to || !commodity) return;
    const row: Row = { from_node: from, to_node: to, commodity_id: commodity, lag_years: lag };
    setWorkbook(setSheet(workbook, "connections", [...(workbook.connections ?? []), row]));
  }
  function deleteConnection(idx: number) {
    setWorkbook(setSheet(workbook, "connections", (workbook.connections ?? []).filter((_, i) => i !== idx)));
  }

  // ── Demand targets ──────────────────────────────────────────────────────────
  const demandRows = workbook.demand ?? [];
  const productIds = useMemo(() => {
    const out = new Set<string>();
    for (const r of workbook.io ?? []) if (s(r.role) === "output" && r.is_product) out.add(s(r.target));
    for (const c of workbook.commodities ?? []) if (s(c.kind) === "product") out.add(s(c.commodity_id));
    return [...out];
  }, [workbook]);
  function addDemand() {
    const row: Row = { company: "all", commodity_id: productIds[0] ?? "", year: baseYear, amount: 100 };
    setWorkbook(setSheet(workbook, "demand", [...demandRows, row]));
  }
  function setDemand(i: number, patch: Record<string, Cell>) {
    setWorkbook(setSheet(workbook, "demand", demandRows.map((r, j) => (j === i ? { ...r, ...patch } : r))));
  }
  function delDemand(i: number) {
    setWorkbook(setSheet(workbook, "demand", demandRows.filter((_, j) => j !== i)));
  }

  // ── Run ─────────────────────────────────────────────────────────────────────
  async function run() {
    if (!sessionId) return;
    setError(null);
    setCascade(null);
    setRunning("submitting");
    try {
      // Ensure at least one period exists.
      if (!(workbook.periods ?? []).length) {
        setWorkbook(setSheet(workbook, "periods", [{ year: baseYear, duration_years: 1 }]));
      }
      await flush();
      const scenario = {
        economics: { base_year: baseYear },
        optimisation_scope: scope,
        coupling: { signals: ["price", "carbon_intensity"], iterations: 3, damping: 0.5 },
      };
      const result = await runToCompletion(sessionId, scenario, { domain: "process", backend: "linopy" }, setRunning);
      if (isCascade(result)) setCascade(result);
      else onJointResult(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(null);
    }
  }

  const hasHierarchy = (workbook.nodes ?? []).length > 0;

  return (
    <div className="view-full builder" style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {/* Toolbar: breadcrumb + run controls */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 14px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
        <Breadcrumb path={pathNodes} onJump={(i) => setPath(i === -1 ? [] : path.slice(0, i + 1))} />
        <span style={{ flex: 1 }} />
        <label style={{ fontSize: "0.78rem", display: "flex", gap: 4, alignItems: "center" }}>
          <span className="muted">base year</span>
          <input type="number" value={baseYear} onChange={(e) => setBaseYear(Number(e.target.value) || 2025)} style={{ width: 70, ...inp }} />
        </label>
        <label style={{ fontSize: "0.78rem", display: "flex", gap: 4, alignItems: "center" }}>
          <span className="muted">optimise at</span>
          <select value={scope} onChange={(e) => setScope(e.target.value)} style={inp} title="root/system = joint solve; a sub-level = coupled per-level cascade">
            {levels.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <button className="run-button" onClick={run} disabled={running != null || !sessionId}>
          {running ? `▶ ${running}…` : "▶ Run"}
        </button>
      </div>

      {error && (
        <div className="error" style={{ padding: "4px 12px" }} onClick={() => setError(null)}>
          {error} <span className="muted">(dismiss)</span>
        </div>
      )}

      {/* Subgroup chips at the current level */}
      <div style={{ display: "flex", gap: 6, padding: "6px 14px", flexWrap: "wrap", alignItems: "center", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
        <span className="muted" style={{ fontSize: "0.74rem", marginRight: 4 }}>subgroups:</span>
        {subgroups.map((g) => (
          <span key={g.id} className="vc-chip">
            <button className="vc-chip-label" onClick={() => setPath([...path, g.id])} title="open">
              {g.label}
            </button>
            <button className="vc-chip-x" onClick={() => deleteNode(g.id)} title="delete">
              ✕
            </button>
          </span>
        ))}
        <button className="ghost" onClick={addSubgroup}>
          ＋ subgroup
        </button>
      </div>

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* Left rail: component palette + connections + demand */}
        <aside className="rail" style={{ width: 264, overflow: "auto", borderRight: "1px solid var(--border)", padding: "0 0 16px" }}>
          <div className="rail-section">
            <div className="rail-head">Components</div>
            <div className="rail-empty" style={{ fontSize: "0.72rem" }}>
              {currentGroupId ? "click to drop a fresh copy here" : "open a subgroup to drop components"}
            </div>
            {libs.map((l) => (
              <div key={l.id}>
                <button className="rail-subhead" style={{ width: "100%", textAlign: "left", background: "none", border: "none", cursor: "pointer", padding: "4px 8px" }} onClick={() => setOpenLibId(openLibId === l.id ? null : l.id)}>
                  {openLibId === l.id ? "▾" : "▸"} {l.label}
                </button>
                {openLibId === l.id && openLib && (
                  <div style={{ paddingLeft: 8 }}>
                    {[...openLib.groups.map((g) => ({ name: g.name, label: g.label || g.name, kind: "group" })), ...openLib.machines.map((m) => ({ name: m.name, label: m.label || m.name, kind: "machine" }))].map((c) => (
                      <button
                        key={c.kind + c.name}
                        className="rail-item"
                        disabled={!currentGroupId || busy != null}
                        onClick={() => dropComponent(l.id, c.name)}
                        title={currentGroupId ? `drop into ${nodeById.get(currentGroupId)?.label}` : "open a subgroup first"}
                        style={{ width: "100%", textAlign: "left", opacity: currentGroupId ? 1 : 0.5 }}
                      >
                        {busy === `${l.id}/${c.name}` ? "…" : c.kind === "group" ? "▦" : "▪"} {c.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Connections at this level */}
          {levelChildren.length >= 2 && (
            <ConnectionPanel
              children={levelChildren}
              commodities={(workbook.commodities ?? []).map((c) => s(c.commodity_id))}
              connections={levelConnections.map(({ idx, r }) => ({ idx, from: s(r.from_node), to: s(r.to_node), commodity: s(r.commodity_id), lag: Number(r.lag_years) || 0 }))}
              onAdd={addConnection}
              onDelete={deleteConnection}
            />
          )}

          {/* Demand targets */}
          <div className="rail-section">
            <div className="rail-head-row">
              <span className="rail-head">Targets (demand)</span>
              <button className="rail-add" onClick={addDemand} title="add demand">
                ＋
              </button>
            </div>
            {demandRows.map((r, i) => (
              <div key={i} style={{ display: "flex", gap: 4, padding: "2px 8px", alignItems: "center" }}>
                <select value={s(r.commodity_id)} onChange={(e) => setDemand(i, { commodity_id: e.target.value })} style={{ ...inp, flex: 1 }}>
                  <option value="">—</option>
                  {productIds.map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
                <input type="number" value={Number(r.amount) || 0} onChange={(e) => setDemand(i, { amount: Number(e.target.value) || 0 })} style={{ ...inp, width: 70 }} />
                <button className="ghost" onClick={() => delDemand(i)}>
                  ✕
                </button>
              </div>
            ))}
            {demandRows.length === 0 && <div className="rail-empty">no targets — add what the chain must produce</div>}
          </div>
        </aside>

        {/* Main: canvas (or empty state) + cascade summary */}
        <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          {!hasHierarchy ? (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12 }}>
              <p className="muted" style={{ maxWidth: 360, textAlign: "center" }}>
                Empty model. Start by adding a subgroup (a value chain, a sector, a company…), then open it and drop facilities from the component libraries.
              </p>
              <button className="run-button" onClick={addSubgroup}>
                ＋ Add first subgroup
              </button>
            </div>
          ) : (
            <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
              <GroupCanvas wb={workbook} groupId={currentGroupId} onDrill={(id) => setPath([...path, id])} onSelect={(id) => renameNode(id)} />
            </div>
          )}

          {cascade && (
            <div style={{ borderTop: "1px solid var(--border)", padding: "8px 14px", maxHeight: 200, overflow: "auto" }}>
              <b>Per-level result</b> <span className="muted">· {cascade.status} · {cascade.iterations} iteration(s)</span>
              <table className="grid" style={{ fontSize: "0.76rem", marginTop: 4 }}>
                <thead>
                  <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                    <th>stage</th>
                    <th>status</th>
                    <th>objective</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(cascade.stages).map(([id, r]) => (
                    <tr key={id}>
                      <td>{nodeById.get(id)?.label ?? id}</td>
                      <td>{r.status ?? "—"}</td>
                      <td>{r.objective != null ? Math.round(r.objective).toLocaleString() : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {cascade.couplings.length > 0 && (
                <div className="muted" style={{ marginTop: 4, fontSize: "0.74rem" }}>
                  couplings: {cascade.couplings.map((c) => `${nodeById.get(c.from)?.label ?? c.from}→${nodeById.get(c.to)?.label ?? c.to} (${c.commodity}/${c.signal})`).join(", ")}
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

const inp: React.CSSProperties = {
  padding: "3px 6px",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-button)",
  background: "var(--surface)",
  font: "inherit",
  fontSize: "0.78rem",
};

// ── Connection (coupling) panel ──────────────────────────────────────────────
function ConnectionPanel({
  children,
  commodities,
  connections,
  onAdd,
  onDelete,
}: {
  children: GroupNode[];
  commodities: string[];
  connections: { idx: number; from: string; to: string; commodity: string; lag: number }[];
  onAdd: (from: string, to: string, commodity: string, lag: number) => void;
  onDelete: (idx: number) => void;
}) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [commodity, setCommodity] = useState("");
  const [lag, setLag] = useState(0);
  const labelOf = (id: string) => children.find((c) => c.id === id)?.label ?? id;
  return (
    <div className="rail-section">
      <div className="rail-head">Connections</div>
      {connections.map((c) => (
        <div key={c.idx} style={{ display: "flex", gap: 4, padding: "2px 8px", alignItems: "center", fontSize: "0.74rem" }}>
          <span style={{ flex: 1 }}>
            {labelOf(c.from)} → {labelOf(c.to)} <span className="muted">({c.commodity}{c.lag ? `, lag ${c.lag}y` : ""})</span>
          </span>
          <button className="ghost" onClick={() => onDelete(c.idx)}>
            ✕
          </button>
        </div>
      ))}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, padding: "4px 8px" }}>
        <select value={from} onChange={(e) => setFrom(e.target.value)} style={inp}>
          <option value="">from…</option>
          {children.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
        <select value={to} onChange={(e) => setTo(e.target.value)} style={inp}>
          <option value="">to…</option>
          {children.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
        <select value={commodity} onChange={(e) => setCommodity(e.target.value)} style={inp}>
          <option value="">stream…</option>
          {commodities.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        <div style={{ display: "flex", gap: 4 }}>
          <input type="number" value={lag} onChange={(e) => setLag(Number(e.target.value) || 0)} style={{ ...inp, width: 48 }} title="lag (yr)" />
          <button
            className="ghost"
            onClick={() => {
              onAdd(from, to, commodity, lag);
              setFrom("");
              setTo("");
              setCommodity("");
              setLag(0);
            }}
          >
            ＋ link
          </button>
        </div>
      </div>
    </div>
  );
}
