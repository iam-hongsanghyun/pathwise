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
import { HierarchyMap } from "../features/topology/HierarchyMap";
import { sourceStreams } from "../lib/hierarchyLayout";
import { Alternatives, FlowContext, MachineInspector, PortsPanel, SourceStreamInspector } from "../features/valuechain/panels";
import { ModelHealth } from "../features/valuechain/ModelHealth";
import { indexIssues, rollUpBadges, validateModel, type FixDescriptor, type Issue } from "../lib/validate";
import { useDialogs } from "../features/controls/Dialog";
import { SearchableSelect } from "../features/controls/SearchableSelect";
import { SearchSelect } from "../features/controls/SearchSelect";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import { Resizer } from "../layout/Resizer";
import type { TreeAction, TreeMoveEvent, TreeNode } from "../features/tree/types";
import {
  addAlternative,
  type AvailableTechnology,
  getComponentLibrary,
  getSessionComponentLibrary,
  instantiateComponent,
  type LibScope,
  type LibrarySummary,
  listAllComponentLibraries,
  listAvailableTechnologies,
  placeTechnology,
} from "../lib/api/components";
import type { LibraryEntry } from "../lib/api/libraries";
import { getFullModel, putModel } from "../lib/api/session";
import { commodityUnit, machineProduct, maxOutputCap, minOutputCap, setMaxOutputCap, setMinOutputCap } from "../lib/caps";
import { parseNodes } from "../lib/groupGraph";
import type { Cell, Row, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  sessionId: string | null;
  adoptServerModel: (wb: Workbook) => void;
  /** Importable libraries (for the blank-model "start from an example" affordance). */
  libraries?: LibraryEntry[];
  onPickLibrary?: (key: string) => void;
}

const s = (v: unknown): string => (v == null ? "" : String(v));
let _ctr = 0;
const genId = (p: string): string => `${p}_${Date.now().toString(36)}${(_ctr++).toString(36)}`;
// Alternative technologies are shown as synthetic, muted child rows under a
// machine (they are not real nodes — they live in the `transitions` sheet). The
// row id encodes which machine + which target technology so the context menu can
// act on it without a separate lookup.
const ALT_PREFIX = "alt:";
const altRowId = (machineId: string, technology: string): string => `${ALT_PREFIX}${machineId}::${technology}`;
function parseAltId(id: string): { machineId: string; technology: string } | null {
  if (!id.startsWith(ALT_PREFIX)) return null;
  const rest = id.slice(ALT_PREFIX.length);
  const sep = rest.indexOf("::");
  return sep < 0 ? null : { machineId: rest.slice(0, sep), technology: rest.slice(sep + 2) };
}

export function ValueChainTabView({ workbook, setWorkbook, sessionId, adoptServerModel, libraries = [], onPickLibrary }: Props) {
  const [selId, setSelId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [libs, setLibs] = useState<LibrarySummary[]>([]);
  const [availableTechs, setAvailableTechs] = useState<AvailableTechnology[]>([]);
  const [picker, setPicker] = useState<{ parentId: string } | null>(null);
  const [altPicker, setAltPicker] = useState<{ machineId: string } | null>(null);
  const [connectFrom, setConnectFrom] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [leftW, setLeftW] = useState(240); // structure rail width (draggable)
  const [rightW, setRightW] = useState(300); // detail rail width (draggable)
  const { prompt, confirm, node: dialogNode } = useDialogs();

  useEffect(() => {
    if (!sessionId) return;
    listAllComponentLibraries(sessionId).then(setLibs).catch((e) => setError(String(e)));
  }, [sessionId]);

  // The technology pool an alternative can be drawn from (base + session libs);
  // refetch when the model changes so an imported project's techs appear.
  useEffect(() => {
    if (sessionId) listAvailableTechnologies(sessionId).then(setAvailableTechs).catch(() => setAvailableTechs([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, workbook]);

  const nodes = useMemo(() => parseNodes(workbook), [workbook]);
  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const selNode = selId ? nodeById.get(selId) : null;

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
  async function addSubgroup(parentId: string | null) {
    const label = (await prompt({ title: "Add subgroup", label: "name", placeholder: "e.g. Korea, Steel Co" }))?.trim();
    if (!label) return;
    const level = (await prompt({ title: "Level for this group", label: "level", defaultValue: parentId ? "company" : "value_chain", placeholder: "value_chain / country / company / facility" }))?.trim() || "";
    const id = genId("grp");
    setWorkbook(setSheet(workbook, "nodes", [...(workbook.nodes ?? []), { node_id: id, parent_id: parentId, kind: "group", level, label }]));
    if (parentId) setExpanded((p) => new Set(p).add(parentId));
    setSelId(id);
  }

  async function deleteNode(id: string) {
    if (!(await confirm({ title: "Delete item", message: `Delete '${nodeById.get(id)?.label ?? id}' and everything inside it?`, danger: true, confirmLabel: "Delete" }))) return;
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

  async function renameNode(id: string, label?: string) {
    const next = (label ?? (await prompt({ title: "Rename", label: "name", defaultValue: nodeById.get(id)?.label ?? id })) ?? "").trim();
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

  async function dropPick(library: string, name: string, kind: "technology" | "machine" | "group", parentId: string, scope: LibScope) {
    if (!sessionId) return;
    setError(null);
    try {
      await putModel(sessionId, workbook);
      const res =
        kind === "technology"
          ? await placeTechnology(sessionId, { library, technology: name, parent_id: parentId, capacity: 1000, scope })
          : await instantiateComponent(sessionId, { library, component: name, parent_id: parentId, scope });
      adoptServerModel(await getFullModel(sessionId));
      setExpanded((p) => new Set(p).add(parentId));
      // Select the freshly instantiated node so it's immediately editable in the
      // right rail (no need to hunt for it in the tree).
      const newId = res.root ?? res.created[0];
      if (newId) setSelId(newId);
    } catch (e) {
      setError(String(e));
    }
  }

  // ── Alternatives (technologies the optimiser may switch a machine to) ─────────
  async function addAlt(machineId: string, technology: string, library: string, scope: "base" | "session") {
    if (!sessionId) return;
    setError(null);
    try {
      await putModel(sessionId, workbook); // the endpoint operates on the stored model
      await addAlternative(sessionId, { library, technology, machine_id: machineId, scope });
      adoptServerModel(await getFullModel(sessionId));
    } catch (e) {
      setError(String(e));
    }
  }
  function removeAlt(baseline: string, technology: string) {
    setWorkbook(setSheet(workbook, "transitions",
      (workbook.transitions ?? []).filter((r) => !(s(r.from_technology) === baseline && s(r.to_technology) === technology))));
  }

  // ── Connections ─────────────────────────────────────────────────────────────
  function addConnection(from: string, to: string, commodity: string, lag: number, minFlow: number | null, maxFlow: number | null) {
    if (!from || !to || from === to || !commodity) return;
    setWorkbook(setSheet(workbook, "connections", [...(workbook.connections ?? []), { from_node: from, to_node: to, commodity_id: commodity, lag_years: lag, min_flow: minFlow ?? "", max_flow: maxFlow ?? "" }]));
  }
  function editConnection(rowIndex: number, commodity: string, lag: number, minFlow: number | null, maxFlow: number | null) {
    if (!commodity) return;
    setWorkbook(setSheet(workbook, "connections", (workbook.connections ?? []).map((r, i) => (i === rowIndex ? { ...r, commodity_id: commodity, lag_years: lag, min_flow: minFlow ?? "", max_flow: maxFlow ?? "" } : r))));
  }
  function deleteConnection(rowIndex: number) {
    setWorkbook(setSheet(workbook, "connections", (workbook.connections ?? []).filter((_, i) => i !== rowIndex)));
  }

  // ── Purchasing (markets scoped to a node) ───────────────────────────────────
  function addMarket(nodeId: string, commodity: string, kind: "buy" | "sell") {
    // A new BUY market defaults to the stream's own price (not 0) so it doesn't
    // silently let the optimiser buy for free — the validation layer flags a 0.
    const comm = (workbook.commodities ?? []).find((c) => s(c.commodity_id) === commodity);
    const buyPrice = Number(comm?.price) || 0;
    const sellPrice = Number(comm?.sale_price) || 0;
    const row: Row = kind === "buy"
      ? { market_id: genId("buy"), target: commodity, company: nodeId, price: buyPrice }
      : { market_id: genId("sell"), target: commodity, company: nodeId, sell_price: sellPrice };
    setWorkbook(setSheet(workbook, "markets", [...(workbook.markets ?? []), row]));
  }
  function setMarketPrice(rowIndex: number, field: "price" | "sell_price", value: number) {
    setWorkbook(setSheet(workbook, "markets", (workbook.markets ?? []).map((r, i) => (i === rowIndex ? { ...r, [field]: value } : r))));
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
    setWorkbook(setSheet(workbook, "demand", [...(workbook.demand ?? []), { company: nodeId, commodity_id: products[0] ?? "", year: 2025, amount: 100 }]));
  }
  function setDemandRow(idx: number, patch: Record<string, Cell>) {
    setWorkbook(setSheet(workbook, "demand", (workbook.demand ?? []).map((r, j) => (j === idx ? { ...r, ...patch } : r))));
  }
  function delDemandRow(idx: number) {
    setWorkbook(setSheet(workbook, "demand", (workbook.demand ?? []).filter((_, j) => j !== idx)));
  }

  const commodities = useMemo(() => (workbook.commodities ?? []).map((c) => s(c.commodity_id)), [workbook]);

  // ── Validation (live, client-side mirror of the most common model issues) ─────
  const issues = useMemo(() => validateModel(workbook), [workbook]);
  const issueIdx = useMemo(() => indexIssues(issues), [issues]);
  const badges = useMemo(() => rollUpBadges(workbook, issueIdx.byNode), [workbook, issueIdx]);

  /** Apply an issue's one-click fix (declarative descriptor → setSheet mutation,
   *  undoable + persisted by App). Value-requiring fixes prompt first. */
  async function applyFix(issue: Issue) {
    const fix = issue.fix;
    if (!fix) return;
    let d: FixDescriptor = fix.descriptor;
    if (fix.promptFor) {
      const raw = (await prompt({ title: fix.label, label: fix.promptFor.label, defaultValue: fix.promptFor.defaultValue != null ? String(fix.promptFor.defaultValue) : undefined }))?.trim();
      const val = Number(raw);
      if (!raw || !Number.isFinite(val)) return;
      const f = fix.promptFor.field;
      if (d.kind === "patchRow") d = { ...d, patch: { ...d.patch, [f]: val } };
      else if (d.kind === "appendRow") d = { ...d, row: { ...d.row, [f]: val } };
      else if (d.kind === "setCommodityField") d = { ...d, patch: { ...d.patch, [f]: val } };
    }
    if (d.kind === "appendRow") setWorkbook(setSheet(workbook, d.sheet, [...(workbook[d.sheet] ?? []), d.row]));
    else if (d.kind === "removeRow") setWorkbook(setSheet(workbook, d.sheet, (workbook[d.sheet] ?? []).filter((_, i) => i !== d.rowIndex)));
    else if (d.kind === "patchRow") setWorkbook(setSheet(workbook, d.sheet, (workbook[d.sheet] ?? []).map((r, i) => (i === d.rowIndex ? { ...r, ...d.patch } : r))));
    else if (d.kind === "setCommodityField") setWorkbook(setSheet(workbook, "commodities", (workbook.commodities ?? []).map((r) => (s(r.commodity_id) === d.commodityId ? { ...r, ...d.patch } : r))));
  }

  const hasHierarchy = (workbook.nodes ?? []).length > 0;

  // ── Context menu ──────────────────────────────────────────────────────────────
  function actionsFor(node: TreeNode): TreeAction[] {
    if (parseAltId(node.id)) return [{ id: "remove-alternative", label: "Remove this alternative", danger: true }];
    const common: TreeAction[] = [
      { id: "connect", label: "Connect to…" },
      { id: "up", label: "Move up", separatorBefore: true },
      { id: "down", label: "Move down" },
      { id: "rename", label: "Rename", separatorBefore: true },
      { id: "delete", label: "Delete", danger: true },
    ];
    if (node.kind === "machine") return [{ id: "add-alternative", label: "Add alternative…" }, ...common];
    return [
      { id: "add-subgroup", label: "Add subgroup" },
      { id: "add-component", label: "Add component…" },
      { id: "add-target", label: "Add target (demand)" },
      ...common,
    ];
  }
  function onContextAction(actionId: string, node: TreeNode) {
    const alt = parseAltId(node.id);
    if (alt) {
      if (actionId === "remove-alternative") {
        const baseline = s((workbook.machines ?? []).find((m) => s(m.machine_id) === alt.machineId)?.baseline_technology);
        removeAlt(baseline, alt.technology);
      }
      setSelId(alt.machineId);
      return;
    }
    setSelId(node.id);
    if (actionId === "add-subgroup") addSubgroup(node.id);
    else if (actionId === "add-component") setPicker({ parentId: node.id });
    else if (actionId === "add-alternative") { setExpanded((p) => new Set(p).add(node.id)); setAltPicker({ machineId: node.id }); }
    else if (actionId === "add-target") addTarget(node.id);
    else if (actionId === "connect") setConnectFrom(node.id);
    else if (actionId === "up") moveNode(node.id, "up");
    else if (actionId === "down") moveNode(node.id, "down");
    else if (actionId === "rename") renameNode(node.id);
    else if (actionId === "delete") deleteNode(node.id);
  }

  const treeNodes = useMemo<TreeNode[]>(() => {
    const baselineOf = new Map<string, string>();
    for (const m of workbook.machines ?? []) baselineOf.set(s(m.machine_id), s(m.baseline_technology));
    const altsOf = (machineId: string): string[] => {
      const base = baselineOf.get(machineId);
      if (!base) return [];
      return (workbook.transitions ?? []).filter((r) => s(r.from_technology) === base).map((r) => s(r.to_technology)).filter(Boolean);
    };
    const out: TreeNode[] = [];
    for (const n of nodes) {
      const alts = n.kind === "machine" ? altsOf(n.id) : [];
      out.push({
        id: n.id, parentId: n.parentId, kind: n.kind, label: n.label,
        level: n.level || undefined, order: n.order,
        hasChildren: nodes.some((c) => c.parentId === n.id) || alts.length > 0,
        droppable: n.kind === "group",
        badge: badges.get(n.id),
      });
      // Alternatives the optimiser may switch this machine to — greyed-out leaves.
      alts.forEach((tech, i) =>
        out.push({ id: altRowId(n.id, tech), parentId: n.id, kind: "leaf", label: tech, level: "alternative", order: i, hasChildren: false, muted: true, draggable: false, droppable: false }),
      );
    }
    return out;
  }, [nodes, workbook, badges]);

  // Selecting an alternative leaf selects its owning machine (alternatives are
  // not real nodes), so the right-hand inspector shows the machine + its options.
  function selectNode(id: string) {
    const alt = parseAltId(id);
    setSelId(alt ? alt.machineId : id);
  }

  return (
    <div className="view-full builder">
      {error && <div className="error error-bar" onClick={() => setError(null)}>{error} <span className="muted">(dismiss)</span></div>}

      <div className="builder-body">
        {/* LEFT: structure only */}
        <aside className="builder-rail" style={{ width: leftW }}>
          <div className="rail-head-row">
            <span className="rail-head">Structure</span>
            <button className="rail-add" title="add top-level subgroup" onClick={() => addSubgroup(null)}>＋</button>
          </div>
          <div className="rail-scroll">
            <TreeExplorer
              nodes={treeNodes}
              selectedId={selId}
              expandedIds={expanded}
              onToggle={(id, exp) => setExpanded((p) => { const m = new Set(p); if (exp) m.add(id); else m.delete(id); return m; })}
              onSelect={selectNode}
              actionsFor={actionsFor}
              onContextAction={onContextAction}
              onMove={onMove}
              emptyHint="Empty — click ＋ (or right-click) to add a value chain / sector."
            />
          </div>
          <div className="rail-foot">Right-click an item for actions · drag to move</div>
        </aside>
        <Resizer width={leftW} setWidth={setLeftW} side="left" />

        {/* CENTER: relationship canvas */}
        <main className="builder-canvas">
          <div className="view-head" style={{ padding: "12px 16px 0" }}>
            <div className="eyebrow">value chain</div>
            <span className="view-status">connections &amp; flows between facilities</span>
          </div>
          {!hasHierarchy ? (
            <div className="vc-empty">
              <h2 className="view-title" style={{ margin: 0 }}>Start a value chain</h2>
              <p className="detail-note" style={{ maxWidth: 420, textAlign: "center", margin: 0 }}>
                A value chain is a tree of <b>nodes</b> (sector → company → facility) holding <b>machines</b> that run a <b>technology</b>; you wire them with <b>connections</b> (in-chain) and <b>markets</b> (buy/sell outside).
              </p>
              {(() => {
                const vc = libraries.filter((l) => l.has_value_chain);
                return vc.length > 0 && onPickLibrary ? (
                  <div style={{ width: 320, textAlign: "center" }}>
                    <div className="detail-note" style={{ marginBottom: 4 }}>start from an example</div>
                    <SearchSelect value="" onChange={(key) => key && onPickLibrary(key)} placeholder="open an example model…"
                      options={vc.map((l) => ({ value: `${l.tier}/${l.id}`, label: l.label }))} />
                  </div>
                ) : null;
              })()}
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button className="run-button" onClick={() => addSubgroup(null)}>＋ Add value chain</button>
                <span className="detail-note">…then right-click it to add subgroups or components</span>
              </div>
            </div>
          ) : (
            <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
              <HierarchyMap
                workbook={workbook}
                editable
                selectedId={selId}
                onSelect={setSelId}
                onAddConnection={addConnection}
                onEditConnection={editConnection}
                onDeleteConnection={deleteConnection}
                commodities={commodities}
              />
            </div>
          )}
        </main>

        <Resizer width={rightW} setWidth={setRightW} side="right" />
        {/* RIGHT: detail of the selected item */}
        <aside className="builder-rail is-right" style={{ width: rightW }}>
          {selId?.startsWith("stream:") ? (
            (() => {
              const cid = selId.slice("stream:".length);
              const src = sourceStreams(workbook).find((x) => x.id === cid);
              const labels = (src?.consumers ?? []).map((id) => nodeById.get(id)?.label ?? id);
              return (
                <SourceStreamInspector
                  wb={workbook}
                  commodityId={cid}
                  consumerLabels={labels}
                  onMaxPurchase={(v) =>
                    setWorkbook(
                      setSheet(
                        workbook,
                        "commodities",
                        (workbook.commodities ?? []).map((r) => (s(r.commodity_id) === cid ? { ...r, max_purchase: v ?? "" } : r)),
                      ),
                    )
                  }
                />
              );
            })()
          ) : !selNode ? (
            <div style={{ padding: "8px 0" }}>
              <ModelHealth issues={issues} onJump={(id) => setSelId(id)} onFix={applyFix} />
              <div className="muted" style={{ padding: "8px 16px", fontSize: "0.82rem" }}>Select an item on the left to see its details. Right-click for actions.</div>
            </div>
          ) : selNode.kind === "machine" ? (
            (() => {
              const baseline = s((workbook.machines ?? []).find((m) => s(m.machine_id) === selId)?.baseline_technology);
              const alts = (workbook.transitions ?? []).filter((r) => s(r.from_technology) === baseline).map((r) => s(r.to_technology));
              const product = machineProduct(workbook, selId!);
              return (
                <>
                  <MachineInspector
                    wb={workbook}
                    machineId={selId!}
                    onCapacity={(v) => setWorkbook(setSheet(workbook, "machines", (workbook.machines ?? []).map((r) => (s(r.machine_id) === selId ? { ...r, capacity: v } : r))))}
                    unitLabel={product ? commodityUnit(workbook, product) : undefined}
                    minOutput={product ? minOutputCap(workbook, selId!, product) : null}
                    onMinOutput={product ? (v) => setWorkbook(setMinOutputCap(workbook, selId!, product, v)) : undefined}
                    maxOutput={product ? maxOutputCap(workbook, selId!, product) : null}
                    onMaxOutput={product ? (v) => setWorkbook(setMaxOutputCap(workbook, selId!, product, v)) : undefined}
                  />
                  <div style={{ padding: "0 20px 16px" }}>
                    <Alternatives
                      baseline={baseline}
                      alternatives={alts}
                      available={availableTechs}
                      onAdd={(tech, library, scope) => void addAlt(selId!, tech, library, scope)}
                      onRemove={(tech) => removeAlt(baseline, tech)}
                    />
                    <FlowContext wb={workbook} nodeId={selId!} />
                  </div>
                </>
              );
            })()
          ) : (
            <div style={{ padding: "14px 16px" }}>
              <div className="eyebrow">group</div>
              <input className="title-input" value={selNode.label} onChange={(e) => renameNode(selId!, e.target.value)} />
              <label className="field-row" style={{ marginBottom: 14 }}>
                <span className="muted">level</span>
                <input className="field-input" style={{ flex: 1 }} value={selNode.level} onChange={(e) => setLevel(selId!, e.target.value)} placeholder="value_chain / company / facility" />
              </label>

              <FlowContext wb={workbook} nodeId={selId!} />

              <PortsPanel wb={workbook} nodeId={selId!} commodities={commodities} onAdd={(c, k) => addMarket(selId!, c, k)} onPrice={setMarketPrice} onRemove={removeMarket} />

              <div className="rail-section">
                <div className="rail-head-row">
                  <span className="rail-head">Targets (this node)</span>
                  <button className="rail-add" onClick={() => addTarget(selId!)}>＋</button>
                </div>
                {demandFor(selId!).map(({ idx, r }) => (
                  <div key={idx} style={{ display: "flex", gap: 4, padding: "2px 8px", alignItems: "center" }}>
                    <span style={{ flex: 1 }}>
                      <SearchSelect value={s(r.commodity_id)} onChange={(v) => setDemandRow(idx, { commodity_id: v })}
                        options={products.map((p) => ({ value: p }))} placeholder="stream…" />
                    </span>
                    <input className="field-input" style={{ width: 70 }} type="number" min={0} value={Number(r.amount) || 0} onChange={(e) => setDemandRow(idx, { amount: Number(e.target.value) || 0 })} />
                    <button className="ghost" onClick={() => delDemandRow(idx)}>✕</button>
                  </div>
                ))}
                {demandFor(selId!).length === 0 && <div className="rail-empty">no targets here — what must this node deliver?</div>}
              </div>
            </div>
          )}
        </aside>
      </div>

      {picker && <ComponentPicker sessionId={sessionId} libs={libs} onPick={(lib, name, kind, scope) => { void dropPick(lib, name, kind, picker.parentId, scope); setPicker(null); }} onClose={() => setPicker(null)} />}
      {altPicker && (() => {
        const baseline = s((workbook.machines ?? []).find((m) => s(m.machine_id) === altPicker.machineId)?.baseline_technology);
        const existing = new Set((workbook.transitions ?? []).filter((r) => s(r.from_technology) === baseline).map((r) => s(r.to_technology)));
        return (
          <AltPicker
            machineLabel={nodeById.get(altPicker.machineId)?.label ?? altPicker.machineId}
            baseline={baseline}
            available={availableTechs}
            exclude={existing}
            onPick={(tech, library, scope) => { void addAlt(altPicker.machineId, tech, library, scope); setAltPicker(null); }}
            onClose={() => setAltPicker(null)}
          />
        );
      })()}
      {connectFrom && (
        <ConnectDialog
          fromLabel={nodeById.get(connectFrom)?.label ?? connectFrom}
          targets={nodes.filter((n) => n.id !== connectFrom).map((n) => ({ id: n.id, label: `${n.label}${n.level ? ` · ${n.level}` : ""}` }))}
          commodities={commodities}
          onConfirm={(to, commodity, lag) => { addConnection(connectFrom, to, commodity, lag, null, null); setConnectFrom(null); }}
          onClose={() => setConnectFrom(null)}
        />
      )}
      {dialogNode}
    </div>
  );
}

// ── Library → component/technology picker ─────────────────────────────────────
// Place a Component — a single machine or a composite group (e.g. CCGT = GT+ST) —
// or a raw technology (as a single machine).
interface PickItem { library: string; libLabel: string; scope: LibScope; name: string; label: string; kind: "technology" | "machine" | "group" }

function ComponentPicker({ sessionId, libs, onPick, onClose }: { sessionId: string | null; libs: LibrarySummary[]; onPick: (library: string, name: string, kind: "technology" | "machine" | "group", scope: LibScope) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  // Flatten EVERY library's components into one searchable list (cross-library),
  // base + this project's own, so you don't have to know which library a
  // technology lives in.
  const [items, setItems] = useState<PickItem[] | null>(null);
  useEffect(() => {
    let alive = true;
    const body = (l: LibrarySummary) =>
      l.scope === "session" && sessionId ? getSessionComponentLibrary(sessionId, l.id) : getComponentLibrary(l.id);
    Promise.all(libs.map((l) => body(l).then((b) => ({ l, b })).catch(() => null)))
      .then((results) => {
        if (!alive) return;
        const out: PickItem[] = [];
        for (const r of results) {
          if (!r) continue;
          const { l, b } = r;
          for (const g of b.groups) out.push({ library: l.id, libLabel: l.label, scope: l.scope, name: g.name, label: g.label || g.name, kind: "group" });
          for (const m of b.machines) out.push({ library: l.id, libLabel: l.label, scope: l.scope, name: m.name, label: m.label || m.name, kind: "machine" });
          for (const t of b.technologies) out.push({ library: l.id, libLabel: l.label, scope: l.scope, name: t.technology_id, label: t.technology_id, kind: "technology" });
        }
        setItems(out);
      });
    return () => { alive = false; };
  }, [libs, sessionId]);
  const ql = q.toLowerCase();
  const filtered = (items ?? []).filter((it) => !ql || it.label.toLowerCase().includes(ql) || it.libLabel.toLowerCase().includes(ql));
  const glyph = (k: PickItem["kind"]) => (k === "group" ? "▦" : k === "machine" ? "▪" : "▫");
  return (
    <Modal onClose={onClose} title="Add a component">
      {libs.length === 0 && <p className="muted">No component libraries — build one in the Component tab.</p>}
      <input autoFocus placeholder="search all libraries…" value={q} onChange={(e) => setQ(e.target.value)} className="field-input" style={{ width: "100%", marginBottom: 8 }} />
      {items === null && <p className="muted">loading…</p>}
      {items !== null && filtered.length === 0 && <p className="muted">{items.length === 0 ? "No components yet — add some in the Component tab." : "No matches."}</p>}
      {filtered.map((it) => (
        <button key={`${it.kind}/${it.scope}/${it.library}/${it.name}`} className="rail-item" style={{ width: "100%", textAlign: "left" }} onClick={() => onPick(it.library, it.name, it.kind, it.scope)}>
          {glyph(it.kind)} {it.label} <span className="muted">· {it.libLabel}{it.scope === "session" ? " · project" : ""}{it.kind === "technology" ? " · technology" : it.kind === "group" ? " · group" : ""}</span>
        </button>
      ))}
    </Modal>
  );
}

// ── Alternative picker (right-click a machine → attach an alternative tech) ─────
// The pool is every technology across the base + session libraries, minus the
// machine's current technology and ones already attached.
function AltPicker({ machineLabel, baseline, available, exclude, onPick, onClose }: {
  machineLabel: string;
  baseline: string;
  available: AvailableTechnology[];
  exclude: Set<string>;
  onPick: (technology: string, library: string, scope: LibScope) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const opts = available.filter((a) => a.technology !== baseline && !exclude.has(a.technology));
  const filtered = q ? opts.filter((a) => a.technology.toLowerCase().includes(q.toLowerCase())) : opts;
  return (
    <Modal onClose={onClose} title={`Add alternative — ${machineLabel}`}>
      <p className="muted" style={{ fontSize: "0.78rem", marginTop: 0 }}>
        Currently runs <strong>{baseline || "—"}</strong>. Pick a technology the optimiser may switch it to. Shared streams are reused automatically; the technology's own inputs/outputs are added as needed.
      </p>
      <input autoFocus placeholder="search technologies…" value={q} onChange={(e) => setQ(e.target.value)} className="field-input" style={{ width: "100%", marginBottom: 8 }} />
      {filtered.length === 0 && <p className="muted">{opts.length === 0 ? "No other technologies available — add some in the Component tab." : "No matches."}</p>}
      {filtered.map((a) => (
        <button key={`${a.scope}/${a.library}/${a.technology}`} className="rail-item" style={{ width: "100%", textAlign: "left" }} onClick={() => onPick(a.technology, a.library, a.scope)}>
          ▫ {a.technology} <span className="muted">· {a.library}</span>
        </button>
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
          <SearchSelect value={to} onChange={setTo} placeholder="choose a node…"
            options={targets.map((t) => ({ value: t.id, label: t.label }))} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span className="muted">stream</span>
          <SearchableSelect value={commodity} options={commodities} onChange={setCommodity} onCreate={setCommodity} placeholder="commodity" />
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span className="muted">lag (yr)</span>
          <input type="number" value={lag} onChange={(e) => setLag(Number(e.target.value) || 0)} className="field-input" style={{ width: 64 }} />
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
