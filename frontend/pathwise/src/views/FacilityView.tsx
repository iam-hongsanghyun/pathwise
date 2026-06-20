// Facility tab — the REAL-WORLD layer between Component (scientific spec) and
// Value Chain (flows). It builds the shared node tree (sector → company →
// machine, free-text levels, any depth) and holds each machine's real-world
// data: physical capacity, owner, build/close year. It edits ONLY structure +
// machine data — connections are the Value Chain's job (same workbook, different
// concern). It never edits the component library: the base Library tree shown at
// the BOTTOM of the left rail is a READ-ONLY drag source.

import { useEffect, useMemo, useState } from "react";
import { useDialogs } from "../features/controls/Dialog";
import { Resizer } from "../layout/Resizer";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import type { TreeAction, TreeMoveEvent, TreeNode } from "../features/tree/types";
import {
  type ComponentLibrary,
  getComponentLibrary,
  type LibrarySummary,
  listComponentLibraries,
  placeTechnology,
} from "../lib/api/components";
import { getFullModel, putModel } from "../lib/api/session";
import { childrenOf, parseNodes } from "../lib/groupGraph";
import type { Row, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  sessionId: string | null;
  adoptServerModel: (wb: Workbook) => void;
}

const s = (v: unknown): string => (v == null ? "" : String(v));
let _ctr = 0;
const genId = (p: string): string => `${p}_${Date.now().toString(36)}${(_ctr++).toString(36)}`;

export function FacilityView({ workbook, setWorkbook, sessionId, adoptServerModel }: Props) {
  const { prompt, confirm, node: dialogNode } = useDialogs();
  const [selId, setSelId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [libExpanded, setLibExpanded] = useState<Set<string>>(new Set());
  const [leftW] = useState(300);
  const [libH, setLibH] = useState(260); // adjustable height of the bottom library tree
  const [error, setError] = useState<string | null>(null);

  // The shared node tree (same workbook the Value Chain edits).
  const nodes = useMemo(() => parseNodes(workbook), [workbook]);
  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const machineRow = (id: string): Row | undefined =>
    (workbook.machines ?? []).find((r) => s(r.machine_id) === id);

  // ── Base library catalogue (read-only drag source at the bottom of the rail) ──
  const [baseLibs, setBaseLibs] = useState<LibrarySummary[]>([]);
  const [libBodies, setLibBodies] = useState<Map<string, ComponentLibrary>>(new Map());
  useEffect(() => {
    listComponentLibraries().then(setBaseLibs).catch((e) => setError(String(e)));
  }, []);
  async function loadLibBody(libId: string) {
    if (libBodies.has(libId)) return;
    try {
      const body = await getComponentLibrary(libId);
      setLibBodies((p) => new Map(p).set(libId, body));
    } catch (e) {
      setError(String(e));
    }
  }

  const setSheet = (wb: Workbook, sheet: string, rows: Row[]): Workbook => ({ ...wb, [sheet]: rows });
  const descendantsOf = (id: string): Set<string> => {
    const out = new Set<string>([id]);
    let added = true;
    while (added) {
      added = false;
      for (const n of nodes)
        if (n.parentId && out.has(n.parentId) && !out.has(n.id)) {
          out.add(n.id);
          added = true;
        }
    }
    return out;
  };

  // ── Structure edits (write the shared `nodes` sheet) ─────────────────────────
  async function addSubgroup(parentId: string | null) {
    const label = (await prompt({ title: "Add group", label: "name", placeholder: "e.g. Korea, POSCO, Pohang" }))?.trim();
    if (!label) return;
    const level = (
      await prompt({
        title: "Level for this group",
        label: "level",
        defaultValue: parentId ? "company" : "sector",
        placeholder: "sector / company / facility / … (your own names)",
      })
    )?.trim() || "";
    const id = genId("n");
    setWorkbook(setSheet(workbook, "nodes", [...(workbook.nodes ?? []), { node_id: id, parent_id: parentId, kind: "group", level, label }]));
    if (parentId) setExpanded((p) => new Set(p).add(parentId));
    setSelId(id);
  }
  async function renameNode(id: string) {
    const next = (await prompt({ title: "Rename", label: "name", defaultValue: nodeById.get(id)?.label ?? id }))?.trim();
    if (!next) return;
    setWorkbook(setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (s(r.node_id) === id ? { ...r, label: next } : r))));
  }
  function setLevel(id: string, level: string) {
    setWorkbook(setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (s(r.node_id) === id ? { ...r, level } : r))));
  }
  async function deleteNode(id: string) {
    const doomed = descendantsOf(id);
    if (!(await confirm({ title: "Delete", message: `Delete '${nodeById.get(id)?.label ?? id}' and everything under it?`, danger: true, confirmLabel: "Delete" }))) return;
    let wb = setSheet(workbook, "nodes", (workbook.nodes ?? []).filter((r) => !doomed.has(s(r.node_id))));
    wb = setSheet(wb, "machines", (wb.machines ?? []).filter((r) => !doomed.has(s(r.machine_id))));
    wb = setSheet(wb, "connections", (wb.connections ?? []).filter((r) => !doomed.has(s(r.from_node)) && !doomed.has(s(r.to_node))));
    setWorkbook(wb);
    if (selId && doomed.has(selId)) setSelId(null);
  }
  function onMove(e: TreeMoveEvent) {
    const newParent = e.position === "inside" ? e.targetId : nodeById.get(e.beforeSiblingId ?? "")?.parentId ?? null;
    if (e.dragId === newParent) return;
    setWorkbook(setSheet(workbook, "nodes", (workbook.nodes ?? []).map((r) => (s(r.node_id) === e.dragId ? { ...r, parent_id: newParent } : r))));
  }

  // Drag a technology from the base Library tree onto a facility node → place a
  // machine (real-world instance) under it. The recipe stays in the component;
  // the machine carries the physical capacity + real-world data.
  async function dropTechnology(libId: string, technology: string, parentId: string) {
    if (!sessionId) return;
    setError(null);
    try {
      await putModel(sessionId, workbook); // the endpoint operates on the stored model
      const res = await placeTechnology(sessionId, { library: libId, technology, parent_id: parentId, capacity: 0 });
      adoptServerModel(await getFullModel(sessionId));
      setExpanded((p) => new Set(p).add(parentId));
      const newId = res.root ?? res.created[0];
      if (newId) setSelId(newId);
    } catch (e) {
      setError(String(e));
    }
  }

  // Edit a machine's real-world fields on the shared `machines` row.
  function editMachine(id: string, patch: Record<string, Row[string]>) {
    setWorkbook(setSheet(workbook, "machines", (workbook.machines ?? []).map((r) => (s(r.machine_id) === id ? { ...r, ...patch } : r))));
  }

  // ── Trees ────────────────────────────────────────────────────────────────────
  // The facility node tree (top): the shared structure, drop target for the library.
  const facilityNodes = useMemo<TreeNode[]>(() => {
    const out: TreeNode[] = [];
    const walk = (parentId: string | null) => {
      for (const nd of childrenOf(nodes, parentId)) {
        const kids = childrenOf(nodes, nd.id);
        out.push({
          id: nd.id,
          parentId: nd.parentId,
          kind: nd.kind === "machine" ? "machine" : "group",
          label: nd.label,
          level: nd.level || undefined,
          hasChildren: kids.length > 0,
          droppable: nd.kind !== "machine",
        });
        walk(nd.id);
      }
    };
    walk(null);
    return out;
  }, [nodes]);

  // The base Library catalogue (bottom): READ-ONLY drag source. lib → technologies.
  const libraryNodes = useMemo<TreeNode[]>(() => {
    const out: TreeNode[] = [];
    for (const l of baseLibs) {
      out.push({ id: `lib:${l.id}`, parentId: null, kind: "library", label: l.label || l.id, hasChildren: l.technologies > 0, draggable: false });
      const body = libBodies.get(l.id);
      if (!body) continue;
      for (const t of body.technologies)
        out.push({ id: `t:${l.id}:${t.technology_id}`, parentId: `lib:${l.id}`, kind: "leaf", label: t.technology_id, hasChildren: false, draggable: true });
    }
    return out;
  }, [baseLibs, libBodies]);

  function actionsFor(node: TreeNode): TreeAction[] {
    if (node.kind === "machine") return [{ id: "delete", label: "Delete", danger: true }];
    return [
      { id: "add-group", label: "Add group inside" },
      { id: "rename", label: "Rename", separatorBefore: true },
      { id: "delete", label: "Delete", danger: true },
    ];
  }
  function onContextAction(actionId: string, node: TreeNode) {
    if (actionId === "add-group") void addSubgroup(node.id);
    else if (actionId === "rename") void renameNode(node.id);
    else if (actionId === "delete") void deleteNode(node.id);
  }

  const sel = selId ? nodeById.get(selId) : null;
  const inp: React.CSSProperties = {
    padding: "4px 6px",
    border: "1px solid var(--border-strong)",
    borderRadius: "var(--radius-button)",
    background: "var(--surface)",
    font: "inherit",
  };

  function renderDetail() {
    if (!sel) {
      return (
        <section>
          <h2 style={{ margin: "0 0 8px" }}>Facility</h2>
          <p className="muted" style={{ fontSize: "0.82rem", maxWidth: 560 }}>
            Build the real-world structure here. Add groups at any level you like
            (sector, company, facility — your own names, any depth) from the tree
            on the left, then drag technologies from the <b>Library</b> at the
            bottom of the rail onto a group to place a real machine. Give each
            machine its physical capacity, owner and build/close year. Flows
            between nodes are defined in the Value Chain.
          </p>
        </section>
      );
    }
    if (sel.kind === "machine") {
      const r = machineRow(sel.id);
      const tech = s(r?.baseline_technology);
      return (
        <section style={{ maxWidth: 460 }}>
          <div className="eyebrow">machine · {tech || "—"}</div>
          <h2 style={{ margin: "2px 0 12px" }}>{sel.label}</h2>
          <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: "8px 10px", alignItems: "center", fontSize: "0.84rem" }}>
            <span className="muted">capacity</span>
            <input style={inp} type="number" value={s(r?.capacity)} onChange={(e) => editMachine(sel.id, { capacity: e.target.value === "" ? 0 : Number(e.target.value) })} />
            <span className="muted">owner (company)</span>
            <input style={inp} value={s(r?.owner)} placeholder="e.g. POSCO" onChange={(e) => editMachine(sel.id, { owner: e.target.value })} />
            <span className="muted">build year</span>
            <input style={inp} type="number" value={s(r?.build_year)} onChange={(e) => editMachine(sel.id, { build_year: e.target.value === "" ? 0 : Number(e.target.value) })} />
            <span className="muted">close year</span>
            <input style={inp} type="number" value={s(r?.close_year)} onChange={(e) => editMachine(sel.id, { close_year: e.target.value === "" ? 0 : Number(e.target.value) })} />
          </div>
          <p className="muted" style={{ fontSize: "0.74rem", marginTop: 12 }}>
            The recipe (inputs/outputs, per-unit costs &amp; efficiency) lives in the
            component — edit it in the Library tab. Here you set this machine's
            real-world numbers only.
          </p>
        </section>
      );
    }
    // group node
    return (
      <section style={{ maxWidth: 460 }}>
        <div className="eyebrow">group{sel.level ? ` · ${sel.level}` : ""}</div>
        <h2 style={{ margin: "2px 0 12px" }}>{sel.label}</h2>
        <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: "8px 10px", alignItems: "center", fontSize: "0.84rem" }}>
          <span className="muted">level</span>
          <input style={inp} value={sel.level ?? ""} placeholder="sector / company / facility / …" onChange={(e) => setLevel(sel.id, e.target.value)} />
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
          <button className="ghost" onClick={() => void addSubgroup(sel.id)}>＋ group inside</button>
        </div>
        <p className="muted" style={{ fontSize: "0.74rem", marginTop: 12 }}>
          Drag a technology from the Library (bottom-left) onto this group to add a machine, or add another group inside.
        </p>
      </section>
    );
  }

  const tree = (nodesFor: TreeNode[], emptyHint: string, opts: { exp: Set<string>; setExp: (s: Set<string>) => void; drag?: boolean; drop?: boolean }) => (
    <TreeExplorer
      nodes={nodesFor}
      selectedId={selId}
      expandedIds={opts.exp}
      onToggle={(id, e) => {
        opts.setExp((() => {
          const m = new Set(opts.exp);
          if (e) m.add(id);
          else m.delete(id);
          return m;
        })());
        if (opts.drag && e && id.startsWith("lib:")) void loadLibBody(id.slice(4));
      }}
      onSelect={(id) => {
        if (id.startsWith("lib:") || id.startsWith("t:")) return; // library tree is read-only
        setSelId(id);
      }}
      actionsFor={opts.drop ? actionsFor : () => []}
      onContextAction={onContextAction}
      onMove={opts.drop ? onMove : () => undefined}
      acceptsExternal={opts.drop ? (t) => t.kind !== "machine" : undefined}
      onExternalDrop={
        opts.drop
          ? (payload, target) => {
              const parts = payload.split(":");
              if (parts[0] !== "t") return;
              dropTechnology(parts[1], parts.slice(2).join(":"), target.id);
            }
          : undefined
      }
      emptyHint={emptyHint}
    />
  );

  return (
    <div className="view-full builder" style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {error && <div className="error" style={{ padding: "4px 12px" }} onClick={() => setError(null)}>{error} <span className="muted">(dismiss)</span></div>}
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <aside style={{ width: leftW, borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", flexShrink: 0, minHeight: 0 }}>
          {/* TOP: the facility structure (shared node tree). */}
          <div className="rail-head-row" style={{ padding: "6px 10px" }}>
            <span className="rail-head">Facility</span>
            <button className="rail-add" title="add a top-level group" onClick={() => void addSubgroup(null)}>＋</button>
          </div>
          <div style={{ flex: 1, minHeight: 60, overflow: "auto" }}>
            {tree(facilityNodes, "Empty — ＋ to add a group, then drag technologies from the Library below.", { exp: expanded, setExp: setExpanded, drop: true })}
          </div>
          {/* Drag the divider to grow / shrink the library tree below. */}
          <Resizer side="top" width={libH} setWidth={setLibH} min={80} max={600} />
          {/* BOTTOM: the base Library — READ-ONLY drag source. */}
          <div className="rail-head-row" style={{ padding: "6px 10px", borderTop: "1px solid var(--border)" }}>
            <span className="rail-head">Library</span>
            <span className="muted" style={{ fontSize: "0.68rem" }}>drag onto a group ↑</span>
          </div>
          <div style={{ height: libH, minHeight: 60, overflow: "auto" }}>
            {tree(libraryNodes, "No base libraries.", { exp: libExpanded, setExp: setLibExpanded, drag: true })}
          </div>
          <div className="muted" style={{ fontSize: "0.7rem", padding: "8px 10px", borderTop: "1px solid var(--border)" }}>Right-click a group for actions</div>
        </aside>
        <main style={{ flex: 1, overflow: "auto", padding: "16px 20px", minWidth: 0 }}>
          <div className="eyebrow" style={{ marginBottom: 12 }}>facility builder</div>
          {renderDetail()}
        </main>
      </div>
      {dialogNode}
    </div>
  );
}
