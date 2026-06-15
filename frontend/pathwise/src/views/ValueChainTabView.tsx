// Value Chain tab — assemble the model as a directory tree (left) whose leaves
// are component instances; the main panel shows, for the selected GROUP, how its
// children's streams connect (editable RelationshipCanvas), or for a MACHINE its
// required-stream satisfaction. Right-click to add/rename/delete; drag to
// reparent. Streams attach at any level: a child→child connection, or a market
// purchase/sale at a node (a company's decision). Pick an optimisation level and
// Run: root/system = joint (→ Analytics), a sub-level = coupled cascade.

import { useEffect, useMemo, useState } from "react";
import { RelationshipCanvas } from "../features/topology/RelationshipCanvas";
import {
  CascadeSummary,
  DemandPanel,
  MachineInspector,
  PortsPanel,
  type CascadeResult,
} from "../features/valuechain/panels";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import type { TreeAction, TreeMoveEvent, TreeNode } from "../features/tree/types";
import {
  type ComponentLibrary,
  getComponentLibrary,
  instantiateComponent,
  type LibrarySummary,
  listComponentLibraries,
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

export function ValueChainTabView({
  workbook,
  setWorkbook,
  sessionId,
  adoptServerModel,
  onJointResult,
}: Props) {
  const [selId, setSelId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [scope, setScope] = useState("system");
  const [baseYear, setBaseYear] = useState(2025);
  const [running, setRunning] = useState<string | null>(null);
  const [cascade, setCascade] = useState<CascadeResult | null>(null);
  const [libs, setLibs] = useState<LibrarySummary[]>([]);
  const [picker, setPicker] = useState<{ parentId: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listComponentLibraries().then(setLibs).catch((e) => setError(String(e)));
  }, []);

  const nodes = useMemo(() => parseNodes(workbook), [workbook]);
  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const selNode = selId ? nodeById.get(selId) : null;
  const groupId = selNode?.kind === "machine" ? selNode.parentId : selId;

  const setSheet = (wb: Workbook, sheet: string, rows: Row[]): Workbook => ({ ...wb, [sheet]: rows });

  // ── Tree adapter ──────────────────────────────────────────────────────────────
  const treeNodes = useMemo<TreeNode[]>(
    () =>
      nodes.map((n) => ({
        id: n.id,
        parentId: n.parentId,
        kind: n.kind,
        label: n.label,
        level: n.level || undefined,
        order: n.order,
        hasChildren: nodes.some((c) => c.parentId === n.id),
        droppable: n.kind === "group",
      })),
    [nodes],
  );

  // ── Structure mutations ─────────────────────────────────────────────────────
  function addSubgroup(parentId: string | null) {
    const label = window.prompt("Subgroup name (e.g. 'Korea', 'Steel Co'):", "")?.trim();
    if (!label) return;
    const level =
      window.prompt("Level (free text: value_chain, country, company, facility…):", parentId ? "company" : "value_chain")?.trim() || "";
    const id = genId("grp");
    const row: Row = { node_id: id, parent_id: parentId, kind: "group", level, label };
    setWorkbook(setSheet(workbook, "nodes", [...(workbook.nodes ?? []), row]));
    if (parentId) setExpanded((p) => new Set(p).add(parentId));
    setSelId(id);
  }

  function deleteNode(id: string) {
    if (!window.confirm(`Delete '${nodeById.get(id)?.label ?? id}' and everything inside it?`)) return;
    const doomed = new Set<string>([id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const n of nodes)
        if (n.parentId && doomed.has(n.parentId) && !doomed.has(n.id)) {
          doomed.add(n.id);
          grew = true;
        }
    }
    const deadMeasures = new Set(
      (workbook.measures ?? []).filter((r) => doomed.has(s(r.facility))).map((r) => s(r.measure_id)),
    );
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

  function renameNode(id: string) {
    const label = window.prompt("Rename:", nodeById.get(id)?.label ?? id)?.trim();
    if (!label) return;
    setWorkbook(setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (s(r.node_id) === id ? { ...r, label } : r))));
  }

  function onMove(e: TreeMoveEvent) {
    const newParent =
      e.position === "inside" ? e.targetId : (e.beforeSiblingId ? nodeById.get(e.beforeSiblingId)?.parentId ?? null : null);
    setWorkbook(setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (s(r.node_id) === e.dragId ? { ...r, parent_id: newParent } : r))));
  }

  async function dropComponent(library: string, component: string, parentId: string) {
    if (!sessionId) return;
    setError(null);
    try {
      await putModel(sessionId, workbook); // authoritative: parent node must exist server-side
      await instantiateComponent(sessionId, { library, component, parent_id: parentId });
      adoptServerModel(await getFullModel(sessionId));
      setExpanded((p) => new Set(p).add(parentId));
    } catch (e) {
      setError(String(e));
    }
  }

  // ── Connections (relationship canvas) ───────────────────────────────────────
  function addConnection(from: string, to: string, commodity: string, lag: number) {
    const row: Row = { from_node: from, to_node: to, commodity_id: commodity, lag_years: lag };
    setWorkbook(setSheet(workbook, "connections", [...(workbook.connections ?? []), row]));
  }
  function deleteConnection(rowIndex: number) {
    setWorkbook(setSheet(workbook, "connections", (workbook.connections ?? []).filter((_, i) => i !== rowIndex)));
  }

  // ── Purchasing (markets scoped to a node) ───────────────────────────────────
  function addMarket(nodeId: string, commodity: string, kind: "buy" | "sell") {
    const row: Row =
      kind === "buy"
        ? { market_id: genId("buy"), target: commodity, company: nodeId, price: 0 }
        : { market_id: genId("sell"), target: commodity, company: nodeId, sell_price: 0 };
    setWorkbook(setSheet(workbook, "markets", [...(workbook.markets ?? []), row]));
  }
  function removeMarket(rowIndex: number) {
    setWorkbook(setSheet(workbook, "markets", (workbook.markets ?? []).filter((_, i) => i !== rowIndex)));
  }

  // ── Demand ──────────────────────────────────────────────────────────────────
  const products = useMemo(() => {
    const out = new Set<string>();
    for (const r of workbook.io ?? []) if (s(r.role) === "output" && r.is_product) out.add(s(r.target));
    for (const c of workbook.commodities ?? []) if (s(c.kind) === "product") out.add(s(c.commodity_id));
    return [...out];
  }, [workbook]);
  const demandRows = workbook.demand ?? [];
  const setDemand = (i: number, patch: Record<string, Cell>) =>
    setWorkbook(setSheet(workbook, "demand", demandRows.map((r, j) => (j === i ? { ...r, ...patch } : r))));

  // ── Market lanes for the canvas (map a market's company → a child of groupId) ─
  const childOfGroup = (companyId: string): string | null => {
    let cur: string | null = companyId;
    while (cur !== null) {
      const parent: string | null = nodeById.get(cur)?.parentId ?? null;
      if (parent === groupId) return cur;
      if (parent === null) return null;
      cur = parent;
    }
    return null;
  };
  const externalIn = (workbook.markets ?? [])
    .filter((r) => s(r.price) !== "")
    .map((r) => ({ childId: childOfGroup(s(r.company)), commodity: s(r.target) }))
    .filter((x): x is { childId: string; commodity: string } => x.childId !== null);
  const externalOut = (workbook.markets ?? [])
    .filter((r) => s(r.sell_price) !== "")
    .map((r) => ({ childId: childOfGroup(s(r.company)), commodity: s(r.target) }))
    .filter((x): x is { childId: string; commodity: string } => x.childId !== null);

  // ── Run ──────────────────────────────────────────────────────────────────────
  const levels = useMemo(() => {
    const set = new Set<string>(["system"]);
    for (const n of nodes) if (n.kind === "group" && n.level) set.add(n.level);
    return [...set];
  }, [nodes]);

  async function run() {
    if (!sessionId) return;
    setError(null);
    setCascade(null);
    setRunning("submitting");
    try {
      // Sync the EXACT current model (with a periods row) authoritatively — the
      // debounced flush closes over a stale workbook, so putModel directly.
      const wb = (workbook.periods ?? []).length
        ? workbook
        : setSheet(workbook, "periods", [{ year: baseYear, duration_years: 1 }]);
      if (wb !== workbook) setWorkbook(wb);
      await putModel(sessionId, wb);
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

  const commodities = useMemo(() => (workbook.commodities ?? []).map((c) => s(c.commodity_id)), [workbook]);
  const hasHierarchy = (workbook.nodes ?? []).length > 0;

  function actionsFor(node: TreeNode): TreeAction[] {
    if (node.kind === "machine") return [
      { id: "rename", label: "Rename" },
      { id: "delete", label: "Delete", danger: true },
    ];
    return [
      { id: "add-subgroup", label: "Add subgroup" },
      { id: "add-component", label: "Add component…" },
      { id: "rename", label: "Rename" },
      { id: "delete", label: "Delete", danger: true, separatorBefore: true },
    ];
  }
  function onContextAction(actionId: string, node: TreeNode) {
    if (actionId === "add-subgroup") addSubgroup(node.id);
    else if (actionId === "add-component") setPicker({ parentId: node.id });
    else if (actionId === "rename") renameNode(node.id);
    else if (actionId === "delete") deleteNode(node.id);
  }

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
        <button className="run-button" onClick={run} disabled={running != null || !sessionId}>
          {running ? `▶ ${running}…` : "▶ Run"}
        </button>
      </div>

      {error && (
        <div className="error" style={{ padding: "4px 12px" }} onClick={() => setError(null)}>
          {error} <span className="muted">(dismiss)</span>
        </div>
      )}

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* left: tree + add + demand + ports */}
        <aside style={{ width: 276, overflow: "auto", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column" }}>
          <div className="rail-head-row" style={{ padding: "6px 10px" }}>
            <span className="rail-head">Structure</span>
            <button className="rail-add" title="add top-level subgroup" onClick={() => addSubgroup(null)}>＋</button>
          </div>
          <TreeExplorer
            nodes={treeNodes}
            selectedId={selId}
            expandedIds={expanded}
            onToggle={(id, exp) =>
              setExpanded((p) => {
                const m = new Set(p);
                if (exp) m.add(id);
                else m.delete(id);
                return m;
              })
            }
            onSelect={setSelId}
            actionsFor={actionsFor}
            onContextAction={onContextAction}
            onMove={onMove}
            emptyHint="Empty — click ＋ to add a value chain / sector."
          />
          {selNode?.kind === "group" && (
            <PortsPanel
              wb={workbook}
              nodeId={selId!}
              commodities={commodities}
              onAdd={(c, k) => addMarket(selId!, c, k)}
              onRemove={removeMarket}
            />
          )}
          <DemandPanel
            rows={demandRows}
            products={products}
            scopes={nodes.filter((n) => n.kind === "group").map((n) => ({ id: n.id, label: n.label }))}
            onAdd={() => setWorkbook(setSheet(workbook, "demand", [...demandRows, { company: "all", commodity_id: products[0] ?? "", year: baseYear, amount: 100 }]))}
            onSet={setDemand}
            onDel={(i) => setWorkbook(setSheet(workbook, "demand", demandRows.filter((_, j) => j !== i)))}
          />
        </aside>

        {/* main: relationship canvas or machine inspector */}
        <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          {!hasHierarchy ? (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12 }}>
              <p className="muted" style={{ maxWidth: 380, textAlign: "center" }}>
                Empty model. Add a subgroup (a value chain, a country, a company…) on the left, then
                right-click it to add subgroups or drop components.
              </p>
              <button className="run-button" onClick={() => addSubgroup(null)}>＋ Add value chain</button>
            </div>
          ) : selNode?.kind === "machine" ? (
            <MachineInspector
              wb={workbook}
              machineId={selId!}
              onCapacity={(v) => setWorkbook(setSheet(workbook, "machines", (workbook.machines ?? []).map((r) => (s(r.machine_id) === selId ? { ...r, capacity: v } : r))))}
            />
          ) : (
            <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
              <div style={{ padding: "4px 14px", fontSize: "0.78rem", color: "var(--muted)", borderBottom: "1px solid var(--border)" }}>
                {selNode ? `Inside ${selNode.label} — how its children connect` : "Top level — how the value chains / sectors connect"} · drag a child's right dot to another's left dot to link
              </div>
              <RelationshipCanvas
                wb={workbook}
                groupId={groupId}
                selectedChildId={null}
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
      </div>

      {picker && (
        <ComponentPicker
          libs={libs}
          onPick={(lib, comp) => {
            void dropComponent(lib, comp, picker.parentId);
            setPicker(null);
          }}
          onClose={() => setPicker(null)}
        />
      )}
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

// ── Library → component picker modal ──────────────────────────────────────────
function ComponentPicker({
  libs,
  onPick,
  onClose,
}: {
  libs: LibrarySummary[];
  onPick: (library: string, component: string) => void;
  onClose: () => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [body, setBody] = useState<ComponentLibrary | null>(null);
  useEffect(() => {
    if (!openId) {
      setBody(null);
      return;
    }
    getComponentLibrary(openId).then(setBody).catch(() => setBody(null));
  }, [openId]);
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.25)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }} onClick={onClose}>
      <div style={{ background: "var(--surface)", border: "1px solid var(--border-strong)", borderRadius: 6, width: 420, maxHeight: "70vh", overflow: "auto", padding: 16 }} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ margin: "0 0 10px" }}>Add a component (fresh copy)</h3>
        {libs.length === 0 && <p className="muted">No component libraries — build one in the Component tab.</p>}
        {libs.map((l) => (
          <div key={l.id} style={{ marginBottom: 4 }}>
            <button className="ghost" style={{ width: "100%", textAlign: "left" }} onClick={() => setOpenId(openId === l.id ? null : l.id)}>
              {openId === l.id ? "▾" : "▸"} {l.label}
            </button>
            {openId === l.id && body && (
              <div style={{ paddingLeft: 14 }}>
                {[...body.groups.map((g) => ({ name: g.name, label: g.label || g.name, kind: "group" })), ...body.machines.map((m) => ({ name: m.name, label: m.label || m.name, kind: "machine" }))].map((c) => (
                  <button key={c.kind + c.name} className="rail-item" style={{ width: "100%", textAlign: "left" }} onClick={() => onPick(l.id, c.name)}>
                    {c.kind === "group" ? "▦" : "▪"} {c.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        <div style={{ textAlign: "right", marginTop: 10 }}>
          <button className="ghost" onClick={onClose}>close</button>
        </div>
      </div>
    </div>
  );
}
