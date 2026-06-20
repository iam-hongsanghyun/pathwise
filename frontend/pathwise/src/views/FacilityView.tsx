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
import { SearchSelect } from "../features/controls/SearchSelect";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import type { TreeAction, TreeMoveEvent, TreeNode } from "../features/tree/types";
import {
  type ComponentLibrary,
  getComponentLibrary,
  type LibrarySummary,
  listComponentLibraries,
  placeTechnology,
} from "../lib/api/components";
import type { LibraryEntry } from "../lib/api/libraries";
import { getFullModel, putModel } from "../lib/api/session";
import { childrenOf, parseNodes } from "../lib/groupGraph";
import type { Row, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  sessionId: string | null;
  adoptServerModel: (wb: Workbook) => void;
  /** Importable libraries — Facility imports the node-bearing ones (a structure). */
  libraries?: LibraryEntry[];
  onPickLibrary?: (key: string) => void;
}

/** Which kind a dragged Library leaf carries (encoded as the leaf id's prefix). */
type DragKind = "t" | "s" | "m" | "g";

// The PREFIXED modelling groups — Technology / Stream / Measures & MACC — are
// auto-created when a component is dropped, and are distinct from the user's own
// (free-text) groups like sector / company.
const PREFIXED_LEVELS = new Set(["Technology", "Stream", "Measures & MACC"]);
const isPrefixedLevel = (lvl?: string | null): boolean => !!lvl && PREFIXED_LEVELS.has(lvl);

const s = (v: unknown): string => (v == null ? "" : String(v));
let _ctr = 0;
const genId = (p: string): string => `${p}_${Date.now().toString(36)}${(_ctr++).toString(36)}`;

export function FacilityView({ workbook, setWorkbook, sessionId, adoptServerModel, libraries = [], onPickLibrary }: Props) {
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

  // The group a dropped component is filed under, by its kind.
  const KIND_GROUP: Record<DragKind, string> = {
    t: "Technology",
    s: "Stream",
    m: "Measures & MACC",
    g: "Measures & MACC",
  };

  /** Find (or create) the kind-group under `parentId`, returning [groupId, wb]. */
  function ensureKindGroup(wb: Workbook, parentId: string, kind: DragKind): [string, Workbook] {
    const label = KIND_GROUP[kind];
    const existing = (wb.nodes ?? []).find(
      (r) => s(r.parent_id) === parentId && s(r.kind) === "group" && s(r.level) === label,
    );
    if (existing) return [s(existing.node_id), wb];
    const id = genId("kg");
    return [id, setSheet(wb, "nodes", [...(wb.nodes ?? []), { node_id: id, parent_id: parentId, kind: "group", level: label, label }])];
  }

  // Drop a component from the Library onto a facility node: prompt for a name,
  // ensure its KIND group (Technology / Stream / Measures & MACC) under the
  // target, then place it there. A technology becomes a real machine (recipe
  // hard-copied via placeTechnology) carrying physical data; other kinds become
  // a named real-world entry under their group.
  async function dropComponent(libId: string, kind: DragKind, compId: string, parentId: string) {
    if (!sessionId) return;
    const kindWord = { t: "technology", s: "stream", m: "measure", g: "MACC" }[kind];
    const name = (await prompt({ title: `Name this ${kindWord}`, label: "name", defaultValue: compId, placeholder: "e.g. Pohang BF#3" }))?.trim();
    if (!name) return;
    setError(null);
    try {
      const [kgId, wb] = ensureKindGroup(workbook, parentId, kind);
      if (kind === "t") {
        setWorkbook(wb);
        await putModel(sessionId, wb); // the endpoint operates on the stored model
        const res = await placeTechnology(sessionId, { library: libId, technology: compId, parent_id: kgId, capacity: 0 });
        let fresh = await getFullModel(sessionId);
        const newId = res.root ?? res.created[0];
        if (newId) {
          fresh = setSheet(fresh, "nodes", (fresh.nodes ?? []).map((r) => (s(r.node_id) === newId ? { ...r, label: name } : r)));
        }
        adoptServerModel(fresh);
        await putModel(sessionId, fresh);
        setExpanded((p) => new Set(p).add(parentId).add(kgId));
        if (newId) setSelId(newId);
      } else {
        // Stream / Measure / MACC → a named real-world entry under its group.
        const leafId = genId("c");
        const next = setSheet(wb, "nodes", [
          ...(wb.nodes ?? []),
          { node_id: leafId, parent_id: kgId, kind: "machine", label: name, level: kindWord },
        ]);
        setWorkbook(next);
        await putModel(sessionId, next);
        setExpanded((p) => new Set(p).add(parentId).add(kgId));
        setSelId(leafId);
      }
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

  // The base Library catalogue (bottom): READ-ONLY drag source. Each library
  // shows its components by kind (Technology / Stream / Measures & MACC); every
  // component leaf is draggable, its id encoding the kind (t/s/m/g).
  const libraryNodes = useMemo<TreeNode[]>(() => {
    const out: TreeNode[] = [];
    for (const l of baseLibs) {
      const total = l.technologies + l.commodities + l.measures + l.maccs;
      out.push({ id: `lib:${l.id}`, parentId: null, kind: "library", label: l.label || l.id, hasChildren: total > 0, draggable: false });
      const body = libBodies.get(l.id);
      if (!body) continue;
      const lib = `lib:${l.id}`;
      const grp = (sub: string, label: string, has: boolean) => {
        const id = `${lib}:${sub}`;
        out.push({ id, parentId: lib, kind: "group", label, hasChildren: has, draggable: false });
        return id;
      };
      const tg = grp("tech", "Technology", body.technologies.length > 0);
      for (const t of body.technologies)
        out.push({ id: `t:${l.id}:${t.technology_id}`, parentId: tg, kind: "leaf", label: t.technology_id, hasChildren: false, draggable: true });
      const sg = grp("stream", "Stream", body.commodities.length > 0);
      for (const c of body.commodities)
        out.push({ id: `s:${l.id}:${c.commodity_id}`, parentId: sg, kind: "leaf", label: c.commodity_id, hasChildren: false, draggable: true });
      const mg = grp("meas", "Measures & MACC", body.measures.length + body.maccs.length > 0);
      for (const g of body.maccs)
        out.push({ id: `g:${l.id}:${g.macc_id}`, parentId: mg, kind: "leaf", label: g.label || g.macc_id, hasChildren: false, draggable: true });
      for (const m of body.measures)
        out.push({ id: `m:${l.id}:${m.measure_id}`, parentId: mg, kind: "leaf", label: m.label || m.measure_id, hasChildren: false, draggable: true });
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
      if (!r) {
        // A non-technology real-world entry (stream / measure / MACC leaf).
        return (
          <section style={{ maxWidth: 460 }}>
            <div className="eyebrow">{sel.level || "component"}</div>
            <h2 style={{ margin: "2px 0 12px" }}>{sel.label}</h2>
            <p className="muted" style={{ fontSize: "0.78rem" }}>
              A real-world {sel.level || "component"} in this facility. Its definition lives in the
              component — edit it in the Library tab.
            </p>
          </section>
        );
      }
      const tech = s(r.baseline_technology);
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
    // group node — show its children as CARDS (like the component view). The
    // Technology / Stream / Measures & MACC groups are PREFIXED (modelling)
    // groups, distinct from normal user groups (sector/company/…).
    const prefixed = isPrefixedLevel(sel.level);
    const kids = childrenOf(nodes, sel.id);
    const childCard = (k: (typeof kids)[number]) => {
      const grandkids = childrenOf(nodes, k.id);
      const isMachine = k.kind === "machine";
      const r = isMachine ? machineRow(k.id) : undefined;
      const sub = isMachine
        ? r
          ? `${s(r.baseline_technology)}${r.capacity ? ` · ${r.capacity}` : ""}`
          : k.level || "component"
        : isPrefixedLevel(k.level)
          ? `${k.level} · ${grandkids.length}`
          : `${k.level || "group"} · ${grandkids.length}`;
      return (
        <button className="lib-card-v2" key={k.id} onClick={() => setSelId(k.id)}>
          <div className="lib-card-top">
            <span className="lib-card-name"><span className="lib-dot" /> {k.label}</span>
            {isPrefixedLevel(k.level) && <span className="lib-tier">{k.level}</span>}
          </div>
          <div className="lib-card-sub muted">{sub}</div>
        </button>
      );
    };
    return (
      <section>
        <div className="eyebrow">{prefixed ? `${sel.level} · modelling group` : `group${sel.level ? ` · ${sel.level}` : ""}`}</div>
        <h2 style={{ margin: "2px 0 8px" }}>{sel.label}</h2>
        {!prefixed && (
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: "0.8rem", marginBottom: 10 }}>
            <span className="muted">level</span>
            <input style={{ ...inp, maxWidth: 240 }} value={sel.level ?? ""} placeholder="sector / company / facility / …" onChange={(e) => setLevel(sel.id, e.target.value)} />
          </label>
        )}
        <p className="muted" style={{ fontSize: "0.78rem", marginBottom: 8 }}>
          {prefixed
            ? `Drag a ${sel.level === "Technology" ? "technology" : sel.level === "Stream" ? "stream" : "measure / MACC"} from the Library below to add one here.`
            : "Right-click in the tree to add a group inside (like a folder), or drag a component from the Library below — it files under a Technology / Stream / Measures & MACC group."}
        </p>
        {kids.length === 0 ? (
          <p className="muted" style={{ fontSize: "0.78rem" }}>Empty — drag a component from the Library at the bottom-left.</p>
        ) : (
          <div className="lib-grid">{kids.map(childCard)}</div>
        )}
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
        // Only the top-level library node loads a body (kind-groups have a colon).
        if (opts.drag && e && id.startsWith("lib:") && !id.slice(4).includes(":")) void loadLibBody(id.slice(4));
      }}
      onSelect={(id) => {
        // The library tree (bottom) is a read-only drag source — never selectable.
        if (opts.drag) return;
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
              const kind = parts[0];
              if (kind !== "t" && kind !== "s" && kind !== "m" && kind !== "g") return;
              void dropComponent(parts[1], kind, parts.slice(2).join(":"), target.id);
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
          {onPickLibrary && (
            <div style={{ padding: "0 10px 6px" }}>
              <SearchSelect
                value=""
                onChange={(v) => v && onPickLibrary(v)}
                options={libraries
                  .filter((l) => l.has_value_chain)
                  .map((l) => ({ value: `${l.tier}/${l.id}`, label: `${l.label}` }))}
                placeholder="import a facility…"
              />
            </div>
          )}
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
