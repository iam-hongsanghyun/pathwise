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
import { TemporalValue } from "../features/controls/TemporalValue";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import type { TreeAction, TreeMoveEvent, TreeNode } from "../features/tree/types";
import {
  type ComponentLibrary,
  getComponentLibrary,
  getSessionComponentLibrary,
  type LibrarySummary,
  type LibScope,
  listAllComponentLibraries,
  placeTechnology,
} from "../lib/api/components";
import { getFullModel, putModel } from "../lib/api/session";
import { commodityUnit, machineProduct, maxOutputCap, minOutputCap, setMaxOutputCap, setMinOutputCap } from "../lib/caps";
import { childrenOf, parseNodes } from "../lib/groupGraph";
import type { Row, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  sessionId: string | null;
  adoptServerModel: (wb: Workbook) => void;
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

export function FacilityView({ workbook, setWorkbook, sessionId, adoptServerModel }: Props) {
  const { prompt, confirm, node: dialogNode } = useDialogs();
  const [selId, setSelId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [libExpanded, setLibExpanded] = useState<Set<string>>(new Set());
  const [libH, setLibH] = useState(260); // adjustable height of the bottom library tree
  const [error, setError] = useState<string | null>(null);

  // The shared node tree (same workbook the Value Chain edits).
  const nodes = useMemo(() => parseNodes(workbook), [workbook]);
  const periods = useMemo(
    () => (workbook.periods ?? []).map((r) => Number(r.year)).filter(Number.isFinite),
    [workbook],
  );
  const baseYear = periods.length ? Math.min(...periods) : 2025;
  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const machineRow = (id: string): Row | undefined =>
    (workbook.machines ?? []).find((r) => s(r.machine_id) === id);

  // ── Library catalogue (read-only drag source at the bottom of the rail) ──────
  // Both BASE (shared) and the PROJECT's own (session) component libraries — so a
  // user can drag in project-specific components alongside the base ones. Each is
  // keyed by `${scope}/${id}` so a base and a project library can share an id.
  const [allLibs, setAllLibs] = useState<LibrarySummary[]>([]);
  const [libBodies, setLibBodies] = useState<Map<string, ComponentLibrary>>(new Map());
  useEffect(() => {
    if (!sessionId) return;
    listAllComponentLibraries(sessionId)
      .then(setAllLibs)
      .catch((e) => setError(String(e)));
  }, [sessionId]);
  async function loadLibBody(key: string) {
    if (libBodies.has(key)) return;
    const slash = key.indexOf("/");
    const scope = key.slice(0, slash) as LibScope;
    const id = key.slice(slash + 1);
    try {
      const body =
        scope === "session" && sessionId
          ? await getSessionComponentLibrary(sessionId, id)
          : await getComponentLibrary(id);
      setLibBodies((p) => new Map(p).set(key, body));
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

  // Technology / Stream / Measures & MACC are the LAST group level — under them
  // live only components, never another group. So a drop onto a kind-group (or a
  // machine inside one) files under its nearest NORMAL ancestor group, so the
  // kind-group is a SIBLING, never nested inside another kind-group.
  function normalParentOf(targetId: string): string | null {
    let cur = nodeById.get(targetId);
    while (cur) {
      if (cur.kind !== "machine" && !isPrefixedLevel(cur.level)) return cur.id;
      cur = cur.parentId ? nodeById.get(cur.parentId) : undefined;
    }
    return null;
  }

  /** Find (or create) the kind-group under `parentId`, returning [groupId, wb]. */
  function ensureKindGroup(wb: Workbook, parentId: string | null, kind: DragKind): [string, Workbook] {
    const label = KIND_GROUP[kind];
    const existing = (wb.nodes ?? []).find(
      (r) => s(r.parent_id) === s(parentId) && s(r.kind) === "group" && s(r.level) === label,
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
  async function dropComponent(scope: LibScope, libId: string, kind: DragKind, compId: string, parentId: string) {
    if (!sessionId) return;
    const kindWord = { t: "technology", s: "stream", m: "measure", g: "MACC" }[kind];
    const name = (await prompt({ title: `Name this ${kindWord}`, label: "name", defaultValue: compId, placeholder: "e.g. Pohang BF#3" }))?.trim();
    if (!name) return;
    setError(null);
    try {
      // File under the target's nearest normal group, so the Technology / Stream /
      // Measures & MACC group is a sibling — never nested inside another kind-group.
      const np = normalParentOf(parentId);
      const [kgId, wb] = ensureKindGroup(workbook, np, kind);
      const expand = (p: Set<string>) => {
        const m = new Set(p).add(kgId);
        if (np) m.add(np);
        return m;
      };
      if (kind === "t") {
        setWorkbook(wb);
        await putModel(sessionId, wb); // the endpoint operates on the stored model
        const res = await placeTechnology(sessionId, { library: libId, technology: compId, parent_id: kgId, capacity: 0, scope });
        let fresh = await getFullModel(sessionId);
        const newId = res.root ?? res.created[0];
        if (newId) {
          fresh = setSheet(fresh, "nodes", (fresh.nodes ?? []).map((r) => (s(r.node_id) === newId ? { ...r, label: name } : r)));
        }
        adoptServerModel(fresh);
        await putModel(sessionId, fresh);
        setExpanded(expand);
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
        setExpanded(expand);
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

  // The Library catalogue (bottom): READ-ONLY drag source — base + project libs.
  // Each library shows its components by kind (Technology / Stream / Measures &
  // MACC); every component leaf is draggable, its id encoding kind + scope + lib
  // so placement resolves the right (base vs project) library.
  const libraryNodes = useMemo<TreeNode[]>(() => {
    const out: TreeNode[] = [];
    for (const l of allLibs) {
      const key = `${l.scope}/${l.id}`;
      const total = l.technologies + l.commodities + l.measures + l.maccs;
      out.push({
        id: `lib:${key}`,
        parentId: null,
        kind: "library",
        label: l.label || l.id,
        level: l.scope === "session" ? "project" : undefined,
        hasChildren: total > 0,
        draggable: false,
      });
      const body = libBodies.get(key);
      if (!body) continue;
      const lib = `lib:${key}`;
      const grp = (sub: string, label: string, has: boolean) => {
        const id = `${lib}:${sub}`;
        out.push({ id, parentId: lib, kind: "group", label, hasChildren: has, draggable: false });
        return id;
      };
      const tg = grp("tech", "Technology", body.technologies.length > 0);
      for (const t of body.technologies)
        out.push({ id: `t:${l.scope}:${l.id}:${t.technology_id}`, parentId: tg, kind: "leaf", label: t.technology_id, hasChildren: false, draggable: true });
      const sg = grp("stream", "Stream", body.commodities.length > 0);
      for (const c of body.commodities)
        out.push({ id: `s:${l.scope}:${l.id}:${c.commodity_id}`, parentId: sg, kind: "leaf", label: c.commodity_id, hasChildren: false, draggable: true });
      const mg = grp("meas", "Measures & MACC", body.measures.length + body.maccs.length > 0);
      for (const g of body.maccs)
        out.push({ id: `g:${l.scope}:${l.id}:${g.macc_id}`, parentId: mg, kind: "leaf", label: g.label || g.macc_id, hasChildren: false, draggable: true });
      for (const m of body.measures)
        out.push({ id: `m:${l.scope}:${l.id}:${m.measure_id}`, parentId: mg, kind: "leaf", label: m.label || m.measure_id, hasChildren: false, draggable: true });
    }
    return out;
  }, [allLibs, libBodies]);

  function actionsFor(node: TreeNode): TreeAction[] {
    if (node.kind === "machine") return [{ id: "delete", label: "Delete", danger: true }];
    // A kind-group (Technology / Stream / Measures & MACC) is leaf-level — you
    // can't add a sub-group inside it, only drop components.
    const prefixed = isPrefixedLevel(node.level);
    return [
      ...(prefixed ? [] : [{ id: "add-group", label: "Add group inside" }]),
      { id: "rename", label: "Rename", separatorBefore: !prefixed },
      { id: "delete", label: "Delete", danger: true },
    ];
  }

  // A kind-group holds ONLY components — forbid reparenting any group into one.
  const canDrop = (dragId: string, newParentId: string | null): boolean => {
    if (!newParentId) return true;
    const np = nodeById.get(newParentId);
    if (np && isPrefixedLevel(np.level)) return nodeById.get(dragId)?.kind === "machine";
    return true;
  };
  function onContextAction(actionId: string, node: TreeNode) {
    if (actionId === "add-group") void addSubgroup(node.id);
    else if (actionId === "rename") void renameNode(node.id);
    else if (actionId === "delete") void deleteNode(node.id);
  }

  const sel = selId ? nodeById.get(selId) : null;

  function renderDetail() {
    if (!sel) {
      return (
        <section>
          <h2 className="view-title">Facility</h2>
          <p className="view-lead">
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
          <section className="detail-col">
            <h2 className="view-title">{sel.label}</h2>
            <p className="detail-sub muted">{sel.level || "component"}</p>
            <p className="detail-note">
              A real-world {sel.level || "component"} in this facility. Its definition lives in the
              component — edit it in the Library tab.
            </p>
          </section>
        );
      }
      const tech = s(r.baseline_technology);
      const product = machineProduct(workbook, sel.id);
      const unit = product ? commodityUnit(workbook, product) : "";
      const maxOut = product ? maxOutputCap(workbook, sel.id, product) : null;
      const minOut = product ? minOutputCap(workbook, sel.id, product) : null;
      return (
        <section className="detail-col">
          <h2 className="view-title">{sel.label}</h2>
          <p className="detail-sub muted">machine · {tech || "—"}</p>
          <div className="field-grid">
            <span className="muted">capacity</span>
            <input className="field-input" type="number" value={s(r?.capacity)} onChange={(e) => editMachine(sel.id, { capacity: e.target.value === "" ? 0 : Number(e.target.value) })} />
            <span className="muted">owner (company)</span>
            <input className="field-input" value={s(r?.owner)} placeholder="e.g. POSCO" onChange={(e) => editMachine(sel.id, { owner: e.target.value })} />
            <span className="muted">build year</span>
            <input className="field-input" type="number" value={s(r?.build_year)} onChange={(e) => editMachine(sel.id, { build_year: e.target.value === "" ? 0 : Number(e.target.value) })} />
            <span className="muted">close year</span>
            <input className="field-input" type="number" value={s(r?.close_year)} onChange={(e) => editMachine(sel.id, { close_year: e.target.value === "" ? 0 : Number(e.target.value) })} />
            <span className="muted">max cap. factor</span>
            <input className="field-input" type="number" min={0} max={1} step={0.05} placeholder="1 (no ceiling)" value={s(r?.max_capacity_factor)} onChange={(e) => editMachine(sel.id, { max_capacity_factor: e.target.value === "" ? 1 : Number(e.target.value) })} />
            <span className="muted">max renewals</span>
            <input className="field-input" type="number" min={0} step={1} placeholder="∞ (unlimited)" value={s(r?.max_renewals)} onChange={(e) => editMachine(sel.id, { max_renewals: e.target.value === "" ? null : Number(e.target.value) })} />
            {product && (
              <>
                <span className="muted">min output</span>
                <TemporalValue value={minOut} unit={unit} baseYear={baseYear} periods={periods} placeholder="no floor" label={`${sel.label} · min output`}
                  onChange={(v) => setWorkbook(setMinOutputCap(workbook, sel.id, product, v))} />
                <span className="muted">max output</span>
                <TemporalValue value={maxOut} unit={unit} baseYear={baseYear} periods={periods} placeholder="no cap" label={`${sel.label} · max output`}
                  onChange={(v) => setWorkbook(setMaxOutputCap(workbook, sel.id, product, v))} />
              </>
            )}
          </div>
          <p className="detail-note" style={{ marginTop: 12 }}>
            The recipe (inputs/outputs, per-unit costs &amp; efficiency) lives in the
            component — edit it in the Library tab. Here you set this machine's
            real-world numbers — capacity, owner, build/close year, and an optional
            annual output floor / ceiling ({product || "product"} in {unit || "its unit"}).
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
        <h2 className="view-title">{sel.label}</h2>
        <p className="detail-sub muted">{prefixed ? `${sel.level} · modelling group` : `group${sel.level ? ` · ${sel.level}` : ""}`}</p>
        {!prefixed && (
          <label className="field-row" style={{ marginBottom: 10 }}>
            <span className="muted">level</span>
            <input className="field-input" value={sel.level ?? ""} placeholder="sector / company / facility / …" onChange={(e) => setLevel(sel.id, e.target.value)} />
          </label>
        )}
        <p className="detail-note" style={{ marginBottom: 8 }}>
          {prefixed
            ? `Drag a ${sel.level === "Technology" ? "technology" : sel.level === "Stream" ? "stream" : "measure / MACC"} from the Library below to add one here.`
            : "Right-click in the tree to add a group inside (like a folder), or drag a component from the Library below — it files under a Technology / Stream / Measures & MACC group."}
        </p>
        {kids.length === 0 ? (
          <p className="detail-note">Empty — drag a component from the Library at the bottom-left.</p>
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
      canDrop={opts.drop ? canDrop : undefined}
      acceptsExternal={opts.drop ? () => true : undefined}
      onExternalDrop={
        opts.drop
          ? (payload, target) => {
              const parts = payload.split(":");
              const kind = parts[0];
              const scope = parts[1];
              if (kind !== "t" && kind !== "s" && kind !== "m" && kind !== "g") return;
              if (scope !== "base" && scope !== "session") return;
              void dropComponent(scope, parts[2], kind, parts.slice(3).join(":"), target.id);
            }
          : undefined
      }
      emptyHint={emptyHint}
    />
  );

  return (
    <div className="view-full builder">
      {error && <div className="error error-bar" onClick={() => setError(null)}>{error} <span className="muted">(dismiss)</span></div>}
      <div className="builder-body">
        <aside className="builder-rail">
          {/* TOP: the facility structure (shared node tree). */}
          <div className="rail-head-row">
            <span className="rail-head">Structure</span>
            <button className="rail-add" title="add a top-level group" onClick={() => void addSubgroup(null)}>＋</button>
          </div>
          <div className="rail-scroll">
            {tree(facilityNodes, "Empty — ＋ to add a group, then drag technologies from the Library below.", { exp: expanded, setExp: setExpanded, drop: true })}
          </div>
          {/* Drag the divider to grow / shrink the library tree below. */}
          <Resizer side="top" width={libH} setWidth={setLibH} min={80} max={600} />
          {/* BOTTOM: the base Library — READ-ONLY drag source. */}
          <div className="rail-head-row is-divided">
            <span className="rail-head">Library</span>
            <span className="rail-hint">drag onto a group ↑</span>
          </div>
          <div className="rail-scroll" style={{ flex: "none", height: libH }}>
            {tree(libraryNodes, "No base libraries.", { exp: libExpanded, setExp: setLibExpanded, drag: true })}
          </div>
          <div className="rail-foot">Right-click a group for actions</div>
        </aside>
        <main className="builder-main">
          <div className="view-head">
            <div className="eyebrow">facility</div>
            <span className="view-status">real-world facilities &amp; machines</span>
          </div>
          {renderDetail()}
        </main>
      </div>
      {dialogNode}
    </div>
  );
}
