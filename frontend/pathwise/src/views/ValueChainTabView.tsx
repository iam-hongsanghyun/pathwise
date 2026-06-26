// Network tab — wire together the components that already exist in the System.
// The Network NEVER reaches into the Library: components (technologies, storage,
// stations…) are placed + hard-copied in the System; here you only CONNECT them.
// A connection carries a flow that is INTRINSIC to the components — a technology's
// own output meeting another's input — so there is no free-typed flow and nothing
// is placed from a library.
//   LEFT  : the structure tree ONLY (the System's components). Single click =
//           select; the twisty expands/collapses; RIGHT-CLICK carries every
//           action (add subgroup / connect / add target / move up·down / rename /
//           delete).
//   CENTER: the relationship canvas for the selected group — how its children's
//           streams flow (drill by selecting a deeper group).
//   RIGHT : details of the selected item — a group's purchasing + targets, or a
//           asset's required-stream satisfaction.

import { useEffect, useMemo, useState } from "react";
import { HierarchyMap } from "../features/topology/HierarchyMap";
import { sourceStreams } from "../lib/hierarchyLayout";
import { Alternatives, FlowContext, AssetInspector, PortsPanel, SourceStreamInspector } from "../features/valuechain/panels";
import { VariantsPanel } from "../features/valuechain/VariantsPanel";
import { ModelHealth } from "../features/valuechain/ModelHealth";
import { indexIssues, rollUpBadges, validateModel, type FixDescriptor, type Issue } from "../lib/validate";
import { useDialogs } from "../features/controls/Dialog";
import { SearchSelect } from "../features/controls/SearchSelect";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import { FloatingPanel } from "../layout/FloatingPanel";
import { AccordionSidebar } from "../layout/AccordionSidebar";
import type { TreeAction, TreeMoveEvent, TreeNode } from "../features/tree/types";
import {
  addAlternative,
  type AvailableTechnology,
  type LibScope,
  listAvailableTechnologies,
} from "../lib/api/components";
import { getFullModel, putModel } from "../lib/api/session";
import { setSupplyCap } from "../lib/caps";
import { parseNodes } from "../lib/groupGraph";
import type { Cell, Row, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  sessionId: string | null;
  adoptServerModel: (wb: Workbook) => void;
}

const s = (v: unknown): string => (v == null ? "" : String(v));
let _ctr = 0;
const genId = (p: string): string => `${p}_${Date.now().toString(36)}${(_ctr++).toString(36)}`;
// Alternative technologies are shown as synthetic, muted child rows under a
// asset (they are not real nodes — they live in the `transitions` sheet). The
// row id encodes which asset + which target technology so the context menu can
// act on it without a separate lookup.
const ALT_PREFIX = "alt:";
const altRowId = (machineId: string, technology: string): string => `${ALT_PREFIX}${machineId}::${technology}`;
function parseAltId(id: string): { machineId: string; technology: string } | null {
  if (!id.startsWith(ALT_PREFIX)) return null;
  const rest = id.slice(ALT_PREFIX.length);
  const sep = rest.indexOf("::");
  return sep < 0 ? null : { machineId: rest.slice(0, sep), technology: rest.slice(sep + 2) };
}

export function ValueChainTabView({ workbook, setWorkbook, sessionId, adoptServerModel }: Props) {
  const [selId, setSelId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [availableTechs, setAvailableTechs] = useState<AvailableTechnology[]>([]);
  const [altPicker, setAltPicker] = useState<{ machineId: string } | null>(null);
  const [connectFrom, setConnectFrom] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [leftW, setLeftW] = useState(240); // structure rail width (draggable)
  const [railOpen, setRailOpen] = useState(false); // left structure rail — collapsed by default
  const [showHealth, setShowHealth] = useState(false); // model-health popup toggle
  const { prompt, confirm, node: dialogNode } = useDialogs();

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
    const deadLevers = new Set((workbook.levers ?? []).filter((r) => doomed.has(s(r.facility))).map((r) => s(r.lever_id)));
    let wb = setSheet(workbook, "nodes", (workbook.nodes ?? []).filter((r) => !doomed.has(s(r.node_id))));
    wb = setSheet(wb, "assets", (wb.assets ?? []).filter((r) => !doomed.has(s(r.asset_id))));
    wb = setSheet(wb, "links", (wb.links ?? []).filter((r) => !doomed.has(s(r.from_node)) && !doomed.has(s(r.to_node))));
    wb = setSheet(wb, "levers", (wb.levers ?? []).filter((r) => !doomed.has(s(r.facility))));
    wb = setSheet(wb, "lever_blocks", (wb.lever_blocks ?? []).filter((r) => !deadLevers.has(s(r.lever_id))));
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

  // ── Alternatives (technologies the optimiser may switch a asset to) ─────────
  async function addAlt(machineId: string, technology: string, library: string, scope: "base" | "session") {
    if (!sessionId) return;
    setError(null);
    try {
      await putModel(sessionId, workbook); // the endpoint operates on the stored model
      await addAlternative(sessionId, { library, technology, asset_id: machineId, scope });
      adoptServerModel(await getFullModel(sessionId));
    } catch (e) {
      setError(String(e));
    }
  }
  function removeAlt(baseline: string, technology: string) {
    setWorkbook(setSheet(workbook, "transitions",
      (workbook.transitions ?? []).filter((r) => !(s(r.from_technology) === baseline && s(r.to_technology) === technology))));
  }

  // ── Links (pure wiring — flow limits are asset→asset, set in the
  //    asset popup per provider asset; a group link just routes flow). ──
  function addLink(from: string, to: string, flow: string, lag: number) {
    if (!from || !to || from === to || !flow) return;
    setWorkbook(setSheet(workbook, "links", [...(workbook.links ?? []), { from_node: from, to_node: to, flow_id: flow, lag_years: lag }]));
  }
  function editLink(rowIndex: number, flow: string, lag: number) {
    if (!flow) return;
    setWorkbook(setSheet(workbook, "links", (workbook.links ?? []).map((r, i) => (i === rowIndex ? { ...r, flow_id: flow, lag_years: lag } : r))));
  }
  function deleteLink(rowIndex: number) {
    setWorkbook(setSheet(workbook, "links", (workbook.links ?? []).filter((_, i) => i !== rowIndex)));
  }

  // ── Purchasing (markets scoped to a node) ───────────────────────────────────
  function addMarket(nodeId: string, flow: string, kind: "buy" | "sell") {
    // A new BUY market defaults to the stream's own price (not 0) so it doesn't
    // silently let the optimiser buy for free — the validation layer flags a 0.
    const comm = (workbook.flows ?? []).find((c) => s(c.flow_id) === flow);
    const buyPrice = Number(comm?.price) || 0;
    const sellPrice = Number(comm?.sale_price) || 0;
    const row: Row = kind === "buy"
      ? { market_id: genId("buy"), target: flow, company: nodeId, price: buyPrice }
      : { market_id: genId("sell"), target: flow, company: nodeId, sell_price: sellPrice };
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
    for (const c of workbook.flows ?? []) if (s(c.kind) === "product") out.add(s(c.flow_id));
    return [...out];
  }, [workbook]);
  const demandFor = (nodeId: string) =>
    (workbook.demand ?? []).map((r, idx) => ({ idx, r })).filter(({ r }) => s(r.company) === nodeId);
  function addTarget(nodeId: string) {
    setWorkbook(setSheet(workbook, "demand", [...(workbook.demand ?? []), { company: nodeId, flow_id: products[0] ?? "", year: 2025, amount: 100 }]));
  }
  function setDemandRow(idx: number, patch: Record<string, Cell>) {
    setWorkbook(setSheet(workbook, "demand", (workbook.demand ?? []).map((r, j) => (j === idx ? { ...r, ...patch } : r))));
  }
  function delDemandRow(idx: number) {
    setWorkbook(setSheet(workbook, "demand", (workbook.demand ?? []).filter((_, j) => j !== idx)));
  }

  const flows = useMemo(() => (workbook.flows ?? []).map((c) => s(c.flow_id)), [workbook]);

  // The flows a node can emit / absorb — INTRINSIC to its component, never invented
  // here: a technology's own io outputs/inputs, a storage's stored flow (both
  // ways), a station's dispensed fuel. A group rolls up its whole subtree, so you
  // can wire one group's product into another. This is what makes a connection in
  // the Network "from the System" — you join an existing output to an existing
  // input, you don't type a new flow name.
  const ioByNode = useMemo(() => {
    const add = (m: Map<string, Set<string>>, k: string, v: string) => {
      if (!v) return;
      (m.get(k) ?? m.set(k, new Set()).get(k)!).add(v);
    };
    const ownOut = new Map<string, Set<string>>();
    const ownIn = new Map<string, Set<string>>();
    const techOf = new Map((workbook.assets ?? []).map((m) => [s(m.asset_id), s(m.baseline_technology)]));
    const ioByTech = new Map<string, { out: Set<string>; in: Set<string> }>();
    for (const r of workbook.io ?? []) {
      const t = s(r.technology_id);
      const e = ioByTech.get(t) ?? { out: new Set<string>(), in: new Set<string>() };
      if (s(r.role) === "output") e.out.add(s(r.target));
      else if (s(r.role) === "input") e.in.add(s(r.target));
      ioByTech.set(t, e);
    }
    for (const [aid, tech] of techOf) {
      const e = ioByTech.get(tech);
      if (!e) continue;
      e.out.forEach((f) => add(ownOut, aid, f));
      e.in.forEach((f) => add(ownIn, aid, f));
    }
    for (const r of workbook.storage ?? []) {
      add(ownOut, s(r.storage_id), s(r.flow_id)); // a tank can discharge…
      add(ownIn, s(r.storage_id), s(r.flow_id)); // …and charge the same flow
    }
    for (const r of workbook.stations ?? []) {
      add(ownOut, s(r.station_id), s(r.refuel_flow)); // dispenses fuel…
      add(ownIn, s(r.station_id), s(r.refuel_flow)); // …and must be supplied it
    }
    const childrenOf = new Map<string, string[]>();
    for (const n of nodes) {
      const k = n.parentId ?? "";
      (childrenOf.get(k) ?? childrenOf.set(k, []).get(k)!).push(n.id);
    }
    const out = new Map<string, { out: Set<string>; in: Set<string> }>();
    const gather = (id: string): { out: Set<string>; in: Set<string> } => {
      const cached = out.get(id);
      if (cached) return cached;
      const o = new Set(ownOut.get(id) ?? []);
      const i = new Set(ownIn.get(id) ?? []);
      const v = { out: o, in: i };
      out.set(id, v); // set before recursion so a cycle can't loop forever
      for (const c of childrenOf.get(id) ?? []) {
        const cc = gather(c);
        cc.out.forEach((f) => o.add(f));
        cc.in.forEach((f) => i.add(f));
      }
      return v;
    };
    for (const n of nodes) gather(n.id);
    return out;
  }, [workbook, nodes]);

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
      else if (d.kind === "setFlowField") d = { ...d, patch: { ...d.patch, [f]: val } };
    }
    if (d.kind === "appendRow") setWorkbook(setSheet(workbook, d.sheet, [...(workbook[d.sheet] ?? []), d.row]));
    else if (d.kind === "removeRow") setWorkbook(setSheet(workbook, d.sheet, (workbook[d.sheet] ?? []).filter((_, i) => i !== d.rowIndex)));
    else if (d.kind === "patchRow") setWorkbook(setSheet(workbook, d.sheet, (workbook[d.sheet] ?? []).map((r, i) => (i === d.rowIndex ? { ...r, ...d.patch } : r))));
    else if (d.kind === "setFlowField") setWorkbook(setSheet(workbook, "flows", (workbook.flows ?? []).map((r) => (s(r.flow_id) === d.flowId ? { ...r, ...d.patch } : r))));
  }

  const hasHierarchy = (workbook.nodes ?? []).length > 0;
  const periods = useMemo(
    () => (workbook.periods ?? []).map((r) => Number(r.year)).filter(Number.isFinite),
    [workbook],
  );
  const baseYear = periods.length ? Math.min(...periods) : 2025;

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
    if (node.kind === "asset") return [{ id: "add-alternative", label: "Add alternative…" }, ...common];
    return [
      { id: "add-subgroup", label: "Add subgroup" },
      { id: "add-target", label: "Add target (demand)" },
      ...common,
    ];
  }
  function onContextAction(actionId: string, node: TreeNode) {
    const alt = parseAltId(node.id);
    if (alt) {
      if (actionId === "remove-alternative") {
        const baseline = s((workbook.assets ?? []).find((m) => s(m.asset_id) === alt.machineId)?.baseline_technology);
        removeAlt(baseline, alt.technology);
      }
      setSelId(alt.machineId);
      return;
    }
    setSelId(node.id);
    if (actionId === "add-subgroup") addSubgroup(node.id);
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
    // A leaf's TYPE is the kind of component it instantiates (Technology / Storage /
    // Station) — not the raw node `level` (which carried legacy strings like "machine").
    const kindOf = new Map<string, string>();
    for (const m of workbook.assets ?? []) {
      baselineOf.set(s(m.asset_id), s(m.baseline_technology));
      const k = s(m.kind).toLowerCase();
      kindOf.set(s(m.asset_id), k === "storage" ? "Storage" : k === "station" ? "Station" : "Technology");
    }
    const altsOf = (machineId: string): string[] => {
      const base = baselineOf.get(machineId);
      if (!base) return [];
      return (workbook.transitions ?? []).filter((r) => s(r.from_technology) === base).map((r) => s(r.to_technology)).filter(Boolean);
    };
    const out: TreeNode[] = [];
    for (const n of nodes) {
      const alts = n.kind === "asset" ? altsOf(n.id) : [];
      out.push({
        id: n.id, parentId: n.parentId, kind: n.kind, label: n.label,
        level: n.kind === "asset" ? (kindOf.get(n.id) ?? "Technology") : (n.level || undefined),
        order: n.order,
        hasChildren: nodes.some((c) => c.parentId === n.id) || alts.length > 0,
        droppable: n.kind === "group",
        badge: badges.get(n.id),
      });
      // Alternatives the optimiser may switch this asset to — greyed-out leaves.
      alts.forEach((tech, i) =>
        out.push({ id: altRowId(n.id, tech), parentId: n.id, kind: "leaf", label: tech, level: "alternative", order: i, hasChildren: false, muted: true, draggable: false, droppable: false }),
      );
    }
    return out;
  }, [nodes, workbook, badges]);

  // Selecting an alternative leaf selects its owning asset (alternatives are
  // not real nodes), so the right-hand inspector shows the asset + its options.
  function selectNode(id: string) {
    const alt = parseAltId(id);
    setSelId(alt ? alt.machineId : id);
  }

  return (
    <div className="view-full builder">
      {error && <div className="error error-bar" onClick={() => setError(null)}>{error} <span className="muted">(dismiss)</span></div>}

      <div className="builder-body">
        {/* LEFT: accordion sidebar — collapsed by default; expand to browse/edit the tree */}
        <AccordionSidebar
          open={railOpen}
          setOpen={setRailOpen}
          width={leftW}
          setWidth={setLeftW}
          min={200}
          max={420}
          collapsedExtras={
            <button className="rail-add" title="add top-level subgroup" onClick={() => addSubgroup(null)}>＋</button>
          }
          sections={[
            {
              id: "structure",
              title: "Structure",
              defaultOpen: false,
              headAction: (
                <button className="rail-add" title="add top-level subgroup" onClick={() => addSubgroup(null)}>＋</button>
              ),
              body: (
                <>
                  <TreeExplorer
                    nodes={treeNodes}
                    selectedId={selId}
                    expandedIds={expanded}
                    onToggle={(id, exp) => setExpanded((p) => { const m = new Set(p); if (exp) m.add(id); else m.delete(id); return m; })}
                    onSelect={(id) => { setShowHealth(false); selectNode(id); }}
                    actionsFor={actionsFor}
                    onContextAction={onContextAction}
                    onMove={onMove}
                    emptyHint="Empty — click ＋ (or right-click) to add a network / sector."
                  />
                  <div className="rail-foot">Drag to move</div>
                </>
              ),
            },
          ]}
        />

        {/* CENTER: relationship canvas */}
        <main className="builder-canvas">
          <div className="view-head" style={{ padding: "12px 16px 0" }}>
            <div className="eyebrow">network</div>
            <span className="view-status">links &amp; flows between systems</span>
            <span style={{ flex: 1 }} />
            {issues.length > 0 && (
              <button className="ghost health-chip" title="model health" onClick={() => { setSelId(null); setShowHealth(true); }}>
                {issueIdx.errorCount > 0 && <span className="health-dot error" />}
                {issueIdx.warnCount > 0 && <span className="health-dot warning" />}
                {issueIdx.errorCount + issueIdx.warnCount}
              </button>
            )}
          </div>
          {!hasHierarchy ? (
            <div className="vc-empty">
              <h2 className="view-title" style={{ margin: 0 }}>Start a network</h2>
              <p className="detail-note" style={{ maxWidth: 440, textAlign: "center", margin: 0 }}>
                The Network <b>wires together the components you placed in the System</b> — it never adds new ones. Components (technologies, storage, stations) are placed + edited in the <b>System</b> tab; here you join them with <b>links</b> over the flows they already carry, plus <b>markets</b> (buy/sell outside). Import a whole model from the <b>Project</b> tab.
              </p>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button className="run-button" onClick={() => addSubgroup(null)}>＋ Add network</button>
                <span className="detail-note">…then place components in the <b>System</b>, and right-click here to connect them</span>
              </div>
            </div>
          ) : (
            <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
              <HierarchyMap
                workbook={workbook}
                editable
                selectedId={selId}
                onSelect={(id) => { setShowHealth(false); setSelId(id); }}
                onAddLink={addLink}
                onEditLink={editLink}
                onDeleteLink={deleteLink}
                onBackgroundClick={() => { setShowHealth(false); setSelId(null); }}
                flows={flows}
              />
            </div>
          )}
        </main>

      </div>

      {/* Floating, draggable inspector — drag its header to move it; ✕ to close. */}
      {selId?.startsWith("stream:") ? (
        (() => {
          const cid = selId.slice("stream:".length);
          const src = sourceStreams(workbook).find((x) => x.id === cid);
          const labels = (src?.consumers ?? []).map((id) => nodeById.get(id)?.label ?? id);
          return (
            <FloatingPanel title="source flow" width={300} onClose={() => setSelId(null)}>
              <SourceStreamInspector
                wb={workbook}
                flowId={cid}
                consumerLabels={labels}
                baseYear={baseYear}
                periods={periods}
                onSupplyCap={(v) => setWorkbook(setSupplyCap(workbook, cid, v))}
                onAvailability={(from, to) =>
                  setWorkbook(
                    setSheet(
                      workbook,
                      "flows",
                      (workbook.flows ?? []).map((r) =>
                        s(r.flow_id) === cid
                          ? { ...r, available_from: from ?? "", available_to: to ?? "" }
                          : r,
                      ),
                    ),
                  )
                }
              />
            </FloatingPanel>
          );
        })()
      ) : selNode?.kind === "asset" ? (
        (() => {
          const baseline = s((workbook.assets ?? []).find((m) => s(m.asset_id) === selId)?.baseline_technology);
          const alts = (workbook.transitions ?? []).filter((r) => s(r.from_technology) === baseline).map((r) => s(r.to_technology));
          return (
            <FloatingPanel title="asset" width={420} onClose={() => setSelId(null)}>
              <AssetInspector
                wb={workbook}
                machineId={selId!}
                baseYear={baseYear}
                periods={periods}
                onWorkbookChange={setWorkbook}
              />
              <div style={{ padding: "0 16px 14px" }}>
                <Alternatives
                  baseline={baseline}
                  alternatives={alts}
                  available={availableTechs}
                  onAdd={(tech, library, scope) => void addAlt(selId!, tech, library, scope)}
                  onRemove={(tech) => removeAlt(baseline, tech)}
                />
                <FlowContext wb={workbook} nodeId={selId!} />
                <VariantsPanel workbook={workbook} setWorkbook={setWorkbook} machineId={selId!} />
              </div>
            </FloatingPanel>
          );
        })()
      ) : selNode ? (
        <FloatingPanel title="group" width={320} onClose={() => setSelId(null)}>
          <div style={{ padding: "12px 14px" }}>
            <input className="title-input" value={selNode.label} onChange={(e) => renameNode(selId!, e.target.value)} />
            <label className="field-row" style={{ marginBottom: 14 }}>
              <span className="muted">level</span>
              <input className="field-input" style={{ flex: 1 }} value={selNode.level} onChange={(e) => setLevel(selId!, e.target.value)} placeholder="value_chain / company / facility" />
            </label>

            <FlowContext wb={workbook} nodeId={selId!} />

            <PortsPanel wb={workbook} nodeId={selId!} flows={flows} onAdd={(c, k) => addMarket(selId!, c, k)} onPrice={setMarketPrice} onRemove={removeMarket} />

            <div className="rail-section">
              <div className="rail-head-row">
                <span className="rail-head">Targets (this node)</span>
                <button className="rail-add" onClick={() => addTarget(selId!)}>＋</button>
              </div>
              {demandFor(selId!).map(({ idx, r }) => (
                <div key={idx} style={{ display: "flex", gap: 4, padding: "2px 8px", alignItems: "center" }}>
                  <span style={{ flex: 1 }}>
                    <SearchSelect value={s(r.flow_id)} onChange={(v) => setDemandRow(idx, { flow_id: v })}
                      options={products.map((p) => ({ value: p }))} placeholder="flow…" />
                  </span>
                  <input className="field-input" style={{ width: 70 }} type="number" min={0} value={Number(r.amount) || 0} onChange={(e) => setDemandRow(idx, { amount: Number(e.target.value) || 0 })} />
                  <button className="ghost" onClick={() => delDemandRow(idx)}>✕</button>
                </div>
              ))}
              {demandFor(selId!).length === 0 && <div className="rail-empty">no targets here — what must this node deliver?</div>}
            </div>
          </div>
        </FloatingPanel>
      ) : showHealth ? (
        <FloatingPanel title="model health" width={320} onClose={() => setShowHealth(false)}>
          <div style={{ padding: "8px 0" }}>
            <ModelHealth issues={issues} onJump={(id) => { setShowHealth(false); setSelId(id); }} onFix={applyFix} />
          </div>
        </FloatingPanel>
      ) : null}

      {altPicker && (() => {
        const baseline = s((workbook.assets ?? []).find((m) => s(m.asset_id) === altPicker.machineId)?.baseline_technology);
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
      {connectFrom && (() => {
        const fromOut = [...(ioByNode.get(connectFrom)?.out ?? [])];
        const fromSet = new Set(fromOut);
        // Only nodes that can ABSORB one of this node's outputs are valid targets —
        // a connection joins an existing output to an existing input.
        const targets = nodes
          .filter((n) => n.id !== connectFrom)
          .map((n) => ({ n, shared: [...(ioByNode.get(n.id)?.in ?? [])].filter((f) => fromSet.has(f)) }))
          .filter(({ shared }) => shared.length > 0)
          .map(({ n }) => ({ id: n.id, label: `${n.label}${n.level ? ` · ${n.level}` : ""}` }));
        return (
          <ConnectDialog
            fromLabel={nodeById.get(connectFrom)?.label ?? connectFrom}
            fromOut={fromOut}
            targets={targets}
            inputsByNode={ioByNode}
            onConfirm={(to, flow, lag) => { addLink(connectFrom, to, flow, lag); setConnectFrom(null); }}
            onClose={() => setConnectFrom(null)}
          />
        );
      })()}
      {dialogNode}
    </div>
  );
}

// ── Alternative picker (right-click a asset → attach an alternative tech) ─────
// The pool is every technology across the base + session libraries, minus the
// asset's current technology and ones already attached.
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
        Currently runs <strong>{baseline || "—"}</strong>. Pick a technology the optimiser may switch it to. Shared flows are reused automatically; the technology's own inputs/outputs are added as needed.
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
// A connection joins one System component's OUTPUT to another's INPUT over a flow
// they BOTH already carry — there is no free-typed flow. `fromOut` is the source's
// own outputs; `targets` are pre-filtered to nodes that absorb ≥1 of them; the flow
// list narrows to exactly the flows the chosen pair shares.
function ConnectDialog({ fromLabel, fromOut, targets, inputsByNode, onConfirm, onClose }: {
  fromLabel: string;
  fromOut: string[];
  targets: { id: string; label: string }[];
  inputsByNode: Map<string, { out: Set<string>; in: Set<string> }>;
  onConfirm: (to: string, flow: string, lag: number) => void;
  onClose: () => void;
}) {
  const [to, setTo] = useState("");
  const [flow, setFlow] = useState("");
  const [lag, setLag] = useState(0);
  // Flows shared by this source's outputs and the chosen target's inputs.
  const shared = useMemo(() => {
    if (!to) return [] as string[];
    const inn = inputsByNode.get(to)?.in ?? new Set<string>();
    return fromOut.filter((f) => inn.has(f));
  }, [to, fromOut, inputsByNode]);
  // Keep the flow valid as the target changes (auto-pick when there's one choice).
  useEffect(() => {
    if (shared.length === 0) setFlow("");
    else if (!shared.includes(flow)) setFlow(shared.length === 1 ? shared[0] : "");
  }, [shared, flow]);
  return (
    <Modal onClose={onClose} title={`Connect from ${fromLabel}`}>
      {fromOut.length === 0 ? (
        <p className="muted" style={{ fontSize: "0.82rem", marginTop: 0 }}>
          <strong>{fromLabel}</strong> has no output flow to send. Connections carry a flow a
          component already produces — give it (or a child) a technology with an output first.
        </p>
      ) : targets.length === 0 ? (
        <p className="muted" style={{ fontSize: "0.82rem", marginTop: 0 }}>
          Nothing in the System takes any of {fromLabel}'s outputs ({fromOut.join(", ")}). Add a
          component that inputs one of these flows, then connect.
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: "0.82rem" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span className="muted">to (takes one of: {fromOut.join(", ")})</span>
            <SearchSelect value={to} onChange={setTo} placeholder="choose a node…"
              options={targets.map((t) => ({ value: t.id, label: t.label }))} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span className="muted">flow</span>
            <SearchSelect value={flow} onChange={setFlow} placeholder={to ? "shared flow…" : "choose a target first"}
              options={shared.map((f) => ({ value: f }))} />
          </label>
          <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span className="muted">lag (yr)</span>
            <input type="number" value={lag} onChange={(e) => setLag(Number(e.target.value) || 0)} className="field-input" style={{ width: 64 }} />
          </label>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 6, marginTop: 4 }}>
            <button className="ghost" onClick={onClose}>cancel</button>
            <button className="run-button" disabled={!to || !flow} onClick={() => onConfirm(to, flow, lag)}>↔ Connect</button>
          </div>
        </div>
      )}
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
