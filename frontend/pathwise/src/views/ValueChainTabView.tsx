// Value Chain tab — a 3-pane builder.
//   LEFT  : the structure tree ONLY. Single click = select (shows detail on the
//           right); the twisty expands/collapses; RIGHT-CLICK carries every
//           action (add subgroup / add component / connect / add target / move
//           up·down / rename / delete).
//   CENTER: the relationship canvas for the selected group — how its children's
//           streams flow (drill by selecting a deeper group).
//   RIGHT : details of the selected item — a group's purchasing + targets, or a
//           machine's required-stream satisfaction.

import { useEffect, useMemo, useState } from "react";
import { RelationshipCanvas } from "../features/topology/RelationshipCanvas";
import { CascadeSummary, MachineInspector, PortsPanel, type CascadeResult } from "../features/valuechain/panels";
import { SearchableSelect } from "../features/controls/SearchableSelect";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import type { TreeAction, TreeMoveEvent, TreeNode } from "../features/tree/types";
import {
  type ComponentLibrary,
  getComponentLibrary,
  instantiateComponent,
  type LibrarySummary,
  listComponentLibraries,
  placeTechnology,
} from "../lib/api/components";
import { getFullModel, putModel } from "../lib/api/session";
import { runToCompletion } from "../lib/api/run";
import { parseNodes } from "../lib/groupGraph";
import type { Cell, RunResult, Row, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  sessionId: string | null;
  adoptServerModel: (wb: Workbook) => void;
  onJointResult: (r: RunResult) => void;
}

const s = (v: unknown): string => (v == null ? "" : String(v));
let _ctr = 0;
const genId = (p: string): string => `${p}_${Date.now().toString(36)}${(_ctr++).toString(36)}`;
const isCascade = (r: unknown): r is CascadeResult =>
  !!r && typeof r === "object" && "stages" in (r as Record<string, unknown>);

const inp: React.CSSProperties = {
  padding: "3px 6px",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-button)",
  background: "var(--surface)",
  font: "inherit",
  fontSize: "0.78rem",
};

export function ValueChainTabView({ workbook, setWorkbook, sessionId, adoptServerModel, onJointResult }: Props) {
  const [selId, setSelId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [scope, setScope] = useState("system");
  const [baseYear, setBaseYear] = useState(2025);
  const [running, setRunning] = useState<string | null>(null);
  const [cascade, setCascade] = useState<CascadeResult | null>(null);
  const [libs, setLibs] = useState<LibrarySummary[]>([]);
  const [picker, setPicker] = useState<{ parentId: string } | null>(null);
  const [connectFrom, setConnectFrom] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listComponentLibraries().then(setLibs).catch((e) => setError(String(e)));
  }, []);

  const nodes = useMemo(() => parseNodes(workbook), [workbook]);
  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const selNode = selId ? nodeById.get(selId) : null;
  // The canvas always shows a group's children: the selected group, or a selected
  // machine's parent (so the machine is shown in context).
  const canvasGroupId = selNode?.kind === "machine" ? selNode.parentId : selId;

  const setSheet = (wb: Workbook, sheet: string, rows: Row[]): Workbook => ({ ...wb, [sheet]: rows });

  const descendantsOf = (id: string): Set<string> => {
    const out = new Set<string>([id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const n of nodes)
        if (n.parentId && out.has(n.parentId) && !out.has(n.id)) {
          out.add(n.id);
          grew = true;
        }
    }
    return out;
  };

  // ── Structure mutations ─────────────────────────────────────────────────────
  function addSubgroup(parentId: string | null) {
    const label = window.prompt("Subgroup name (e.g. 'Korea', 'Steel Co'):", "")?.trim();
    if (!label) return;
    const level = window.prompt("Level (free text: value_chain, country, company, facility…):", parentId ? "company" : "value_chain")?.trim() || "";
    const id = genId("grp");
    setWorkbook(setSheet(workbook, "nodes", [...(workbook.nodes ?? []), { node_id: id, parent_id: parentId, kind: "group", level, label }]));
    if (parentId) setExpanded((p) => new Set(p).add(parentId));
    setSelId(id);
  }

  function deleteNode(id: string) {
    if (!window.confirm(`Delete '${nodeById.get(id)?.label ?? id}' and everything inside it?`)) return;
    const doomed = descendantsOf(id);
    const deadMeasures = new Set((workbook.measures ?? []).filter((r) => doomed.has(s(r.facility))).map((r) => s(r.measure_id)));
    let wb = setSheet(workbook, "nodes", (workbook.nodes ?? []).filter((r) => !doomed.has(s(r.node_id))));
    wb = setSheet(wb, "machines", (wb.machines ?? []).filter((r) => !doomed.has(s(r.machine_id))));
    wb = setSheet(wb, "connections", (wb.connections ?? []).filter((r) => !doomed.has(s(r.from_node)) && !doomed.has(s(r.to_node))));
    wb = setSheet(wb, "measures", (wb.measures ?? []).filter((r) => !doomed.has(s(r.facility))));
    wb = setSheet(wb, "measure_blocks", (wb.measure_blocks ?? []).filter((r) => !deadMeasures.has(s(r.measure_id))));
    wb = setSheet(wb, "markets", (wb.markets ?? []).filter((r) => !doomed.has(s(r.company))));
    wb = setSheet(wb, "demand", (wb.demand ?? []).filter((r) => !doomed.has(s(r.company))));
    wb = setSheet(wb, "ports", (wb.ports ?? []).filter((r) => !doomed.has(s(r.node_id))));
    setWorkbook(wb);
    if (selId && doomed.has(selId)) setSelId(null);
  }

  function renameNode(id: string, label?: string) {
    const next = (label ?? window.prompt("Rename:", nodeById.get(id)?.label ?? id) ?? "").trim();
    if (!next) return;
    setWorkbook(setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (s(r.node_id) === id ? { ...r, label: next } : r))));
  }

  function setLevel(id: string, level: string) {
    setWorkbook(setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (s(r.node_id) === id ? { ...r, level } : r))));
  }

  /** Reorder a node among its siblings (writes the `order` column). */
  function moveNode(id: string, dir: "up" | "down") {
    const node = nodeById.get(id);
    if (!node) return;
    const sibs = nodes.filter((n) => n.parentId === node.parentId);
    const idx = sibs.findIndex((n) => n.id === id);
    const j = dir === "up" ? idx - 1 : idx + 1;
    if (j < 0 || j >= sibs.length) return;
    const ordered = [...sibs];
    [ordered[idx], ordered[j]] = [ordered[j], ordered[idx]];
    const orderMap = new Map(ordered.map((n, i) => [n.id, i]));
    setWorkbook(setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (orderMap.has(s(r.node_id)) ? { ...r, order: orderMap.get(s(r.node_id)) ?? 0 } : r))));
  }

  function onMove(e: TreeMoveEvent) {
    const newParent = e.position === "inside" ? e.targetId : e.beforeSiblingId ? nodeById.get(e.beforeSiblingId)?.parentId ?? null : null;
    setWorkbook(setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (s(r.node_id) === e.dragId ? { ...r, parent_id: newParent } : r))));
  }

  async function dropPick(library: string, name: string, kind: "technology" | "machine" | "group", parentId: string) {
    if (!sessionId) return;
    setError(null);
    try {
      await putModel(sessionId, workbook);
      if (kind === "technology") await placeTechnology(sessionId, { library, technology: name, parent_id: parentId, capacity: 1000 });
      else await instantiateComponent(sessionId, { library, component: name, parent_id: parentId });
      adoptServerModel(await getFullModel(sessionId));
      setExpanded((p) => new Set(p).add(parentId));
    } catch (e) {
      setError(String(e));
    }
  }

  // ── Connections ─────────────────────────────────────────────────────────────
  function addConnection(from: string, to: string, commodity: string, lag: number) {
    if (!from || !to || from === to || !commodity) return;
    setWorkbook(setSheet(workbook, "connections", [...(workbook.connections ?? []), { from_node: from, to_node: to, commodity_id: commodity, lag_years: lag }]));
  }
  function deleteConnection(rowIndex: number) {
    setWorkbook(setSheet(workbook, "connections", (workbook.connections ?? []).filter((_, i) => i !== rowIndex)));
  }

  // ── Purchasing (markets scoped to a node) ───────────────────────────────────
  function addMarket(nodeId: string, commodity: string, kind: "buy" | "sell") {
    const row: Row = kind === "buy"
      ? { market_id: genId("buy"), target: commodity, company: nodeId, price: 0 }
      : { market_id: genId("sell"), target: commodity, company: nodeId, sell_price: 0 };
    setWorkbook(setSheet(workbook, "markets", [...(workbook.markets ?? []), row]));
  }
  function removeMarket(rowIndex: number) {
    setWorkbook(setSheet(workbook, "markets", (workbook.markets ?? []).filter((_, i) => i !== rowIndex)));
  }

  // ── Targets / demand (owned by a node) ──────────────────────────────────────
  const products = useMemo(() => {
    const out = new Set<string>();
    for (const r of workbook.io ?? []) if (s(r.role) === "output" && r.is_product) out.add(s(r.target));
    for (const c of workbook.commodities ?? []) if (s(c.kind) === "product") out.add(s(c.commodity_id));
    return [...out];
  }, [workbook]);
  const demandFor = (nodeId: string) =>
    (workbook.demand ?? []).map((r, idx) => ({ idx, r })).filter(({ r }) => s(r.company) === nodeId);
  function addTarget(nodeId: string) {
    setWorkbook(setSheet(workbook, "demand", [...(workbook.demand ?? []), { company: nodeId, commodity_id: products[0] ?? "", year: baseYear, amount: 100 }]));
  }
  function setDemandRow(idx: number, patch: Record<string, Cell>) {
    setWorkbook(setSheet(workbook, "demand", (workbook.demand ?? []).map((r, j) => (j === idx ? { ...r, ...patch } : r))));
  }
  function delDemandRow(idx: number) {
    setWorkbook(setSheet(workbook, "demand", (workbook.demand ?? []).filter((_, j) => j !== idx)));
  }

  // ── Market lanes for the canvas ─────────────────────────────────────────────
  const childOfGroup = (companyId: string): string | null => {
    let cur: string | null = companyId;
    while (cur !== null) {
      const parent: string | null = nodeById.get(cur)?.parentId ?? null;
      if (parent === canvasGroupId) return cur;
      if (parent === null) return null;
      cur = parent;
    }
    return null;
  };
  const externalIn = (workbook.markets ?? []).filter((r) => s(r.price) !== "").map((r) => ({ childId: childOfGroup(s(r.company)), commodity: s(r.target) })).filter((x): x is { childId: string; commodity: string } => x.childId !== null);
  const externalOut = (workbook.markets ?? []).filter((r) => s(r.sell_price) !== "").map((r) => ({ childId: childOfGroup(s(r.company)), commodity: s(r.target) })).filter((x): x is { childId: string; commodity: string } => x.childId !== null);

  const commodities = useMemo(() => (workbook.commodities ?? []).map((c) => s(c.commodity_id)), [workbook]);
  const levels = useMemo(() => {
    const set = new Set<string>(["system"]);
    for (const n of nodes) if (n.kind === "group" && n.level) set.add(n.level);
    return [...set];
  }, [nodes]);
  const hasHierarchy = (workbook.nodes ?? []).length > 0;

  // ── Run ──────────────────────────────────────────────────────────────────────
  async function run() {
    if (!sessionId) return;
    setError(null);
    setCascade(null);
    setRunning("submitting");
    try {
      const wb = (workbook.periods ?? []).length ? workbook : setSheet(workbook, "periods", [{ year: baseYear, duration_years: 1 }]);
      if (wb !== workbook) setWorkbook(wb);
      await putModel(sessionId, wb);
      const scenario = { economics: { base_year: baseYear }, optimisation_scope: scope, coupling: { signals: ["price", "carbon_intensity"], iterations: 3, damping: 0.5 } };
      const result = await runToCompletion(sessionId, scenario, { domain: "process", backend: "linopy" }, setRunning);
      if (isCascade(result)) setCascade(result);
      else onJointResult(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(null);
    }
  }

  // ── Context menu ──────────────────────────────────────────────────────────────
  function actionsFor(node: TreeNode): TreeAction[] {
    const common: TreeAction[] = [
      { id: "connect", label: "Connect to…" },
      { id: "up", label: "Move up", separatorBefore: true },
      { id: "down", label: "Move down" },
      { id: "rename", label: "Rename", separatorBefore: true },
      { id: "delete", label: "Delete", danger: true },
    ];
    if (node.kind === "machine") return common;
    return [
      { id: "add-subgroup", label: "Add subgroup" },
      { id: "add-component", label: "Add component…" },
      { id: "add-target", label: "Add target (demand)" },
      ...common,
    ];
  }
  function onContextAction(actionId: string, node: TreeNode) {
    setSelId(node.id);
    if (actionId === "add-subgroup") addSubgroup(node.id);
    else if (actionId === "add-component") setPicker({ parentId: node.id });
    else if (actionId === "add-target") addTarget(node.id);
    else if (actionId === "connect") setConnectFrom(node.id);
    else if (actionId === "up") moveNode(node.id, "up");
    else if (actionId === "down") moveNode(node.id, "down");
    else if (actionId === "rename") renameNode(node.id);
    else if (actionId === "delete") deleteNode(node.id);
  }

  const treeNodes = useMemo<TreeNode[]>(
    () => nodes.map((n) => ({ id: n.id, parentId: n.parentId, kind: n.kind, label: n.label, level: n.level || undefined, order: n.order, hasChildren: nodes.some((c) => c.parentId === n.id), droppable: n.kind === "group" })),
    [nodes],
  );

  return (
    <div className="view-full builder" style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {/* toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 14px", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
        <strong style={{ fontSize: "0.9rem" }}>Value chain</strong>
        <span style={{ flex: 1 }} />
        <label style={{ fontSize: "0.78rem", display: "flex", gap: 4, alignItems: "center" }}>
          <span className="muted">base year</span>
          <input type="number" value={baseYear} onChange={(e) => setBaseYear(Number(e.target.value) || 2025)} style={{ width: 70, ...inp }} />
        </label>
        <label style={{ fontSize: "0.78rem", display: "flex", gap: 4, alignItems: "center" }}>
          <span className="muted">optimise at</span>
          <select value={scope} onChange={(e) => setScope(e.target.value)} style={inp} title="root/system = joint; a sub-level = coupled per-level cascade">
            {levels.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </label>
        <button className="run-button" onClick={run} disabled={running != null || !sessionId}>{running ? `▶ ${running}…` : "▶ Run"}</button>
      </div>

      {error && <div className="error" style={{ padding: "4px 12px" }} onClick={() => setError(null)}>{error} <span className="muted">(dismiss)</span></div>}

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* LEFT: structure only */}
        <aside style={{ width: 240, overflow: "auto", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", flexShrink: 0 }}>
          <div className="rail-head-row" style={{ padding: "6px 10px" }}>
            <span className="rail-head">Structure</span>
            <button className="rail-add" title="add top-level subgroup" onClick={() => addSubgroup(null)}>＋</button>
          </div>
          <TreeExplorer
            nodes={treeNodes}
            selectedId={selId}
            expandedIds={expanded}
            onToggle={(id, exp) => setExpanded((p) => { const m = new Set(p); if (exp) m.add(id); else m.delete(id); return m; })}
            onSelect={setSelId}
            actionsFor={actionsFor}
            onContextAction={onContextAction}
            onMove={onMove}
            emptyHint="Empty — click ＋ (or right-click) to add a value chain / sector."
          />
          <div className="muted" style={{ fontSize: "0.7rem", padding: "8px 10px", borderTop: "1px solid var(--border)" }}>
            Right-click an item for actions · drag to move
          </div>
        </aside>

        {/* CENTER: relationship canvas */}
        <main style={{ flex: 1, minWidth: 220, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          {!hasHierarchy ? (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12 }}>
              <p className="muted" style={{ maxWidth: 380, textAlign: "center" }}>Empty model. Click ＋ on the left to add a value chain, then right-click it to add subgroups or components.</p>
              <button className="run-button" onClick={() => addSubgroup(null)}>＋ Add value chain</button>
            </div>
          ) : (
            <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
              <div style={{ padding: "4px 14px", fontSize: "0.78rem", color: "var(--muted)", borderBottom: "1px solid var(--border)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title="drag a child's right dot to another's left dot to link, or right-click a node → Connect">
                {canvasGroupId ? `Inside ${nodeById.get(canvasGroupId)?.label ?? canvasGroupId} — how its children connect` : "Top level — how the value chains connect"}
              </div>
              <RelationshipCanvas
                wb={workbook}
                groupId={canvasGroupId}
                selectedChildId={selNode?.kind === "machine" ? selId : null}
                onSelectChild={setSelId}
                onAddConnection={addConnection}
                onDeleteConnection={deleteConnection}
                commodities={commodities}
                externalIn={externalIn}
                externalOut={externalOut}
              />
            </div>
          )}
          {cascade && <CascadeSummary cascade={cascade} label={(id) => nodeById.get(id)?.label ?? id} />}
        </main>

        {/* RIGHT: detail of the selected item */}
        <aside style={{ width: 300, overflow: "auto", borderLeft: "1px solid var(--border)", flexShrink: 0 }}>
          {!selNode ? (
            <div className="muted" style={{ padding: 16, fontSize: "0.82rem" }}>Select an item on the left to see its details. Right-click for actions.</div>
          ) : selNode.kind === "machine" ? (
            <MachineInspector wb={workbook} machineId={selId!} onCapacity={(v) => setWorkbook(setSheet(workbook, "machines", (workbook.machines ?? []).map((r) => (s(r.machine_id) === selId ? { ...r, capacity: v } : r))))} />
          ) : (
            <div style={{ padding: "14px 16px" }}>
              <div className="eyebrow">group</div>
              <input value={selNode.label} onChange={(e) => renameNode(selId!, e.target.value)} style={{ ...inp, fontSize: "1rem", fontWeight: 600, width: "100%", margin: "4px 0 8px", border: "none", padding: 0 }} />
              <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: "0.78rem", marginBottom: 14 }}>
                <span className="muted">level</span>
                <input value={selNode.level} onChange={(e) => setLevel(selId!, e.target.value)} style={{ ...inp, flex: 1 }} placeholder="value_chain / company / facility" />
              </label>

              <PortsPanel wb={workbook} nodeId={selId!} commodities={commodities} onAdd={(c, k) => addMarket(selId!, c, k)} onRemove={removeMarket} />

              <div className="rail-section">
                <div className="rail-head-row">
                  <span className="rail-head">Targets (this node)</span>
                  <button className="rail-add" onClick={() => addTarget(selId!)}>＋</button>
                </div>
                {demandFor(selId!).map(({ idx, r }) => (
                  <div key={idx} style={{ display: "flex", gap: 4, padding: "2px 8px", alignItems: "center" }}>
                    <select value={s(r.commodity_id)} onChange={(e) => setDemandRow(idx, { commodity_id: e.target.value })} style={{ ...inp, flex: 1 }}>
                      <option value="">stream…</option>
                      {products.map((p) => <option key={p}>{p}</option>)}
                    </select>
                    <input type="number" value={Number(r.amount) || 0} onChange={(e) => setDemandRow(idx, { amount: Number(e.target.value) || 0 })} style={{ ...inp, width: 70 }} />
                    <button className="ghost" onClick={() => delDemandRow(idx)}>✕</button>
                  </div>
                ))}
                {demandFor(selId!).length === 0 && <div className="rail-empty">no targets here — what must this node deliver?</div>}
              </div>
            </div>
          )}
        </aside>
      </div>

      {picker && <ComponentPicker libs={libs} onPick={(lib, name, kind) => { void dropPick(lib, name, kind, picker.parentId); setPicker(null); }} onClose={() => setPicker(null)} />}
      {connectFrom && (
        <ConnectDialog
          fromLabel={nodeById.get(connectFrom)?.label ?? connectFrom}
          targets={nodes.filter((n) => n.id !== connectFrom).map((n) => ({ id: n.id, label: `${n.label}${n.level ? ` · ${n.level}` : ""}` }))}
          commodities={commodities}
          onConfirm={(to, commodity, lag) => { addConnection(connectFrom, to, commodity, lag); setConnectFrom(null); }}
          onClose={() => setConnectFrom(null)}
        />
      )}
    </div>
  );
}

// ── Library → component/technology picker ─────────────────────────────────────
// Place a Component — a single machine or a composite group (e.g. CCGT = GT+ST) —
// or a raw technology (as a single machine).
function ComponentPicker({ libs, onPick, onClose }: { libs: LibrarySummary[]; onPick: (library: string, name: string, kind: "technology" | "machine" | "group") => void; onClose: () => void }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [body, setBody] = useState<ComponentLibrary | null>(null);
  useEffect(() => {
    if (!openId) { setBody(null); return; }
    getComponentLibrary(openId).then(setBody).catch(() => setBody(null));
  }, [openId]);
  return (
    <Modal onClose={onClose} title="Add a component">
      {libs.length === 0 && <p className="muted">No component libraries — build one in the Component tab.</p>}
      {libs.map((l) => (
        <div key={l.id} style={{ marginBottom: 4 }}>
          <button className="ghost" style={{ width: "100%", textAlign: "left" }} onClick={() => setOpenId(openId === l.id ? null : l.id)}>{openId === l.id ? "▾" : "▸"} {l.label}</button>
          {openId === l.id && body && (
            <div style={{ paddingLeft: 14 }}>
              {(body.groups.length > 0 || body.machines.length > 0) && <div className="muted" style={{ fontSize: "0.7rem", margin: "4px 0 2px" }}>COMPONENTS</div>}
              {body.groups.map((g) => (
                <button key={`g${g.name}`} className="rail-item" style={{ width: "100%", textAlign: "left" }} onClick={() => onPick(l.id, g.name, "group")}>▦ {g.label || g.name} <span className="muted">(group)</span></button>
              ))}
              {body.machines.map((m) => (
                <button key={`m${m.name}`} className="rail-item" style={{ width: "100%", textAlign: "left" }} onClick={() => onPick(l.id, m.name, "machine")}>▪ {m.label || m.name}</button>
              ))}
              <div className="muted" style={{ fontSize: "0.7rem", margin: "6px 0 2px" }}>TECHNOLOGIES (place as a single machine)</div>
              {body.technologies.map((t) => (
                <button key={`t${t.technology_id}`} className="rail-item" style={{ width: "100%", textAlign: "left" }} onClick={() => onPick(l.id, t.technology_id, "technology")}>▫ {t.technology_id}</button>
              ))}
            </div>
          )}
        </div>
      ))}
    </Modal>
  );
}

// ── Connect dialog ────────────────────────────────────────────────────────────
function ConnectDialog({ fromLabel, targets, commodities, onConfirm, onClose }: { fromLabel: string; targets: { id: string; label: string }[]; commodities: string[]; onConfirm: (to: string, commodity: string, lag: number) => void; onClose: () => void }) {
  const [to, setTo] = useState("");
  const [commodity, setCommodity] = useState("");
  const [lag, setLag] = useState(0);
  return (
    <Modal onClose={onClose} title={`Connect from ${fromLabel}`}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: "0.82rem" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span className="muted">to</span>
          <select value={to} onChange={(e) => setTo(e.target.value)} style={inp}>
            <option value="">choose a node…</option>
            {targets.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span className="muted">stream</span>
          <SearchableSelect value={commodity} options={commodities} onChange={setCommodity} onCreate={setCommodity} placeholder="commodity" />
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span className="muted">lag (yr)</span>
          <input type="number" value={lag} onChange={(e) => setLag(Number(e.target.value) || 0)} style={{ ...inp, width: 64 }} />
        </label>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 6, marginTop: 4 }}>
          <button className="ghost" onClick={onClose}>cancel</button>
          <button className="run-button" disabled={!to || !commodity} onClick={() => onConfirm(to, commodity, lag)}>↔ Connect</button>
        </div>
      </div>
    </Modal>
  );
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.25)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }} onClick={onClose}>
      <div style={{ background: "var(--surface)", border: "1px solid var(--border-strong)", borderRadius: 6, width: 420, maxHeight: "70vh", overflow: "auto", padding: 16 }} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ margin: "0 0 10px" }}>{title}</h3>
        {children}
        <div style={{ textAlign: "right", marginTop: 10 }}><button className="ghost" onClick={onClose}>close</button></div>
      </div>
    </div>
  );
}
