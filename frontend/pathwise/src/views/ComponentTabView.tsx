// Component tab — a directory tree of many libraries → groups → components, with
// a selection-driven detail editor. Components carry all their core substance
// (recipe streams, capacity, MACC measures). Drag a component onto another
// library to move it (with its dependencies). Persisted server-side, debounced.

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CommodityEditor,
  GroupEditor,
  MachineEditor,
  TechnologyEditor,
} from "../features/component/editors";
// CommodityEditor is used in the library detail (stream prices).
import { TreeExplorer } from "../features/tree/TreeExplorer";
import type { TreeAction, TreeMoveEvent, TreeNode } from "../features/tree/types";
import {
  type CommodityTemplate,
  type ComponentLibrary,
  deleteComponentLibrary,
  emptyLibrary,
  getComponentLibrary,
  type GroupComponent,
  type LibrarySummary,
  listComponentLibraries,
  type MachineComponent,
  saveComponentLibrary,
  type TechnologyTemplate,
} from "../lib/api/components";

type Kind = "library" | "machine" | "group";
interface Sel {
  libId: string;
  kind: Kind;
  name?: string;
}

const uniq = (base: string, taken: Set<string>): string => {
  if (!taken.has(base)) return base;
  let i = 2;
  while (taken.has(`${base}_${i}`)) i++;
  return `${base}_${i}`;
};

function parseTreeId(id: string): Sel {
  if (id.startsWith("lib:")) return { libId: id.slice(4), kind: "library" };
  const rest = id.slice(4); // after "cmp:"
  const i1 = rest.indexOf(":");
  const libId = rest.slice(0, i1);
  const rest2 = rest.slice(i1 + 1);
  const i2 = rest2.indexOf(":");
  return { libId, kind: rest2.slice(0, i2) as Kind, name: rest2.slice(i2 + 1) };
}
const treeIdOf = (s: Sel): string =>
  s.kind === "library" ? `lib:${s.libId}` : `cmp:${s.libId}:${s.kind}:${s.name}`;

/** Names of every machine/group/technology/commodity a component depends on (so
 *  a cross-library move carries them and references don't break). */
function collectDeps(lib: ComponentLibrary, kind: Kind, name: string) {
  const machines = new Set<string>();
  const groups = new Set<string>();
  const techs = new Set<string>();
  const commodities = new Set<string>();
  const visit = (k: Kind, nm: string) => {
    if (k === "machine") {
      const m = lib.machines.find((x) => x.name === nm);
      if (!m || machines.has(nm)) return;
      machines.add(nm);
      const t = lib.technologies.find((x) => x.technology_id === m.technology);
      if (t) {
        techs.add(t.technology_id);
        for (const io of t.io) if (io.role !== "impact") commodities.add(io.target);
      }
      for (const meas of m.measures) commodities.add(meas.target);
    } else {
      const g = lib.groups.find((x) => x.name === nm);
      if (!g || groups.has(nm)) return;
      groups.add(nm);
      for (const c of g.children)
        visit(lib.machines.some((x) => x.name === c.component) ? "machine" : "group", c.component);
      for (const cn of g.connections) commodities.add(cn.commodity);
    }
  };
  visit(kind, name);
  return { machines, groups, techs, commodities };
}

export function ComponentTabView() {
  const [libs, setLibs] = useState<LibrarySummary[]>([]);
  const [openLibs, setOpenLibs] = useState<Map<string, ComponentLibrary>>(new Map());
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [sel, setSel] = useState<Sel | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const saved = useRef<Map<string, string>>(new Map()); // libId → last-saved JSON

  useEffect(() => {
    listComponentLibraries()
      .then(setLibs)
      .catch((e) => setError(String(e)));
  }, []);

  async function loadLib(id: string) {
    if (openLibs.has(id)) return;
    try {
      const body = await getComponentLibrary(id);
      saved.current.set(id, JSON.stringify(body));
      setOpenLibs((prev) => new Map(prev).set(id, body));
    } catch (e) {
      setError(String(e));
    }
  }

  // Debounced save of every dirty library.
  useEffect(() => {
    if (dirty.size === 0) return;
    setStatus("saving…");
    const t = setTimeout(async () => {
      try {
        for (const id of dirty) {
          const body = openLibs.get(id);
          if (!body) continue;
          const summary = await saveComponentLibrary(id, body);
          saved.current.set(id, JSON.stringify(body));
          setLibs((prev) => prev.map((x) => (x.id === id ? summary : x)));
        }
        setDirty(new Set());
        setStatus("saved");
      } catch (e) {
        setStatus("save failed");
        setError(String(e));
      }
    }, 600);
    return () => clearTimeout(t);
  }, [dirty, openLibs]);

  function editLib(libId: string, fn: (l: ComponentLibrary) => ComponentLibrary) {
    setOpenLibs((prev) => {
      const cur = prev.get(libId);
      if (!cur) return prev;
      const next = fn(structuredClone(cur));
      const m = new Map(prev).set(libId, next);
      return m;
    });
    setDirty((prev) => new Set(prev).add(libId));
  }

  // ── Tree adapter ────────────────────────────────────────────────────────────
  const treeNodes = useMemo<TreeNode[]>(() => {
    const out: TreeNode[] = [];
    for (const l of libs) {
      out.push({
        id: `lib:${l.id}`,
        parentId: null,
        kind: "library",
        label: l.label || l.id,
        hasChildren: l.machines + l.groups > 0,
        droppable: true,
        draggable: false,
      });
      const body = openLibs.get(l.id);
      if (!body) continue;
      for (const g of body.groups)
        out.push({ id: `cmp:${l.id}:group:${g.name}`, parentId: `lib:${l.id}`, kind: "group", label: g.label || g.name, level: g.level, hasChildren: false, droppable: false });
      for (const m of body.machines)
        out.push({ id: `cmp:${l.id}:machine:${m.name}`, parentId: `lib:${l.id}`, kind: "machine", label: m.label || m.name, hasChildren: false, droppable: false });
    }
    return out;
  }, [libs, openLibs]);

  // ── Library + component actions ──────────────────────────────────────────────
  async function newLibrary() {
    const id = window.prompt("New library id (letters, digits, -_.):", "")?.trim();
    if (!id) return;
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(id)) return setError(`invalid library id '${id}'`);
    try {
      await saveComponentLibrary(id, emptyLibrary(id));
      setLibs(await listComponentLibraries());
      setExpanded((p) => new Set(p).add(`lib:${id}`));
      await loadLib(id);
    } catch (e) {
      setError(String(e));
    }
  }
  async function removeLibrary(id: string) {
    if (!window.confirm(`Delete library '${id}'?`)) return;
    try {
      await deleteComponentLibrary(id);
      setLibs(await listComponentLibraries());
      setOpenLibs((p) => {
        const m = new Map(p);
        m.delete(id);
        return m;
      });
      if (sel?.libId === id) setSel(null);
    } catch (e) {
      setError(String(e));
    }
  }
  function addMachine(libId: string) {
    editLib(libId, (l) => {
      const taken = new Set([...l.machines.map((m) => m.name), ...l.groups.map((g) => g.name)]);
      const name = uniq("machine", taken);
      const techId = uniq(name, new Set(l.technologies.map((t) => t.technology_id)));
      const tech: TechnologyTemplate = { technology_id: techId, lifespan: 20, capex: 0, opex: 0, io: [] };
      const machine: MachineComponent = { name, label: "", technology: techId, capacity: 1000, measures: [] };
      setSel({ libId, kind: "machine", name });
      return { ...l, technologies: [...l.technologies, tech], machines: [...l.machines, machine] };
    });
  }
  function addGroup(libId: string) {
    editLib(libId, (l) => {
      const name = uniq("group", new Set([...l.machines.map((m) => m.name), ...l.groups.map((g) => g.name)]));
      const group: GroupComponent = { name, label: "", level: "facility", children: [], connections: [] };
      setSel({ libId, kind: "group", name });
      return { ...l, groups: [...l.groups, group] };
    });
  }
  function deleteComponent(s: Sel) {
    editLib(s.libId, (l) =>
      s.kind === "machine"
        ? { ...l, machines: l.machines.filter((m) => m.name !== s.name) }
        : { ...l, groups: l.groups.filter((g) => g.name !== s.name) },
    );
    setSel({ libId: s.libId, kind: "library" });
  }

  async function moveComponent(e: TreeMoveEvent) {
    const src = parseTreeId(e.dragId);
    if (src.kind === "library") return;
    const dstLib = e.targetId ? parseTreeId(e.targetId).libId : null;
    if (!dstLib || dstLib === src.libId) return; // same library: no-op
    const from = openLibs.get(src.libId);
    if (!from || !src.name) return;
    await loadLib(dstLib);
    const target = openLibs.get(dstLib);
    if (!target) return;
    const deps = collectDeps(from, src.kind, src.name);
    const next = structuredClone(target);
    const has = <T,>(arr: T[], key: (t: T) => string, v: string) => arr.some((x) => key(x) === v);
    for (const id of deps.techs) {
      const t = from.technologies.find((x) => x.technology_id === id);
      if (t && !has(next.technologies, (x) => x.technology_id, id)) next.technologies.push(t);
    }
    for (const id of deps.commodities) {
      const c = from.commodities.find((x) => x.commodity_id === id);
      if (c && !has(next.commodities, (x) => x.commodity_id, id)) next.commodities.push(c);
    }
    for (const nm of deps.machines) {
      const m = from.machines.find((x) => x.name === nm);
      if (m && !has(next.machines, (x) => x.name, nm)) next.machines.push(m);
    }
    for (const nm of deps.groups) {
      const g = from.groups.find((x) => x.name === nm);
      if (g && !has(next.groups, (x) => x.name, nm)) next.groups.push(g);
    }
    setOpenLibs((prev) => new Map(prev).set(dstLib, next));
    // remove the top component from the source
    editLib(src.libId, (l) =>
      src.kind === "machine"
        ? { ...l, machines: l.machines.filter((m) => m.name !== src.name) }
        : { ...l, groups: l.groups.filter((g) => g.name !== src.name) },
    );
    setDirty((p) => new Set(p).add(dstLib));
    setSel({ libId: dstLib, kind: src.kind, name: src.name });
  }

  // ── Detail render ─────────────────────────────────────────────────────────────
  const body = sel ? openLibs.get(sel.libId) : undefined;
  const commodityIds = useMemo(() => (body?.commodities ?? []).map((c) => c.commodity_id), [body]);
  const techIds = useMemo(() => (body?.technologies ?? []).map((t) => t.technology_id), [body]);
  const componentNames = useMemo(
    () => [...(body?.machines ?? []).map((m) => m.name), ...(body?.groups ?? []).map((g) => g.name)],
    [body],
  );

  function renderDetail() {
    if (!sel || !body) return <p className="muted">Pick or create a library on the left to start building.</p>;
    if (sel.kind === "library") {
      const l = libs.find((x) => x.id === sel.libId);
      return (
        <section>
          <h2 style={{ margin: "0 0 12px" }}>Library</h2>
          <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: "0.78rem", maxWidth: 280 }}>
            <span className="muted">label</span>
            <input
              style={{ padding: "4px 6px", border: "1px solid var(--border-strong)", borderRadius: 4, font: "inherit" }}
              value={body.label}
              onChange={(e) => editLib(sel.libId, (lib) => ({ ...lib, label: e.target.value }))}
            />
          </label>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "10px 0" }}>
            <button className="ghost" onClick={() => addMachine(sel.libId)}>＋ Add component</button>
            <button className="ghost" onClick={() => addGroup(sel.libId)}>＋ Add group</button>
          </div>
          <p className="muted" style={{ fontSize: "0.78rem" }}>
            {l?.machines ?? 0} machine(s) · {l?.groups ?? 0} group(s).
            {(l?.machines ?? 0) + (l?.groups ?? 0) === 0
              ? " Empty — add a component above (it gets its own recipe to edit), or right-click this library."
              : " Right-click any item for actions; drag a component onto another library to move it."}
          </p>
          <h3 style={{ margin: "16px 0 6px", fontSize: "0.85rem" }}>
            Streams <span className="muted">(prices used by the model)</span>
            <button
              className="ghost"
              style={{ marginLeft: 8 }}
              onClick={() =>
                editLib(sel.libId, (lib) => ({
                  ...lib,
                  commodities: [
                    ...lib.commodities,
                    { commodity_id: uniq("stream", new Set(lib.commodities.map((c) => c.commodity_id))), kind: "material", unit: "unit" } as CommodityTemplate,
                  ],
                }))
              }
            >
              ＋ add stream
            </button>
          </h3>
          {body.commodities.map((c) => (
            <CommodityEditor
              key={c.commodity_id}
              value={c}
              onChange={(v) => editLib(sel.libId, (lib) => ({ ...lib, commodities: lib.commodities.map((x) => (x.commodity_id === c.commodity_id ? v : x)) }))}
              onRename={() => undefined}
            />
          ))}
        </section>
      );
    }
    if (sel.kind === "machine") {
      const m = body.machines.find((x) => x.name === sel.name);
      if (!m) return null;
      const tech = body.technologies.find((t) => t.technology_id === m.technology);
      const recipe = tech ? (
        <TechnologyEditor
          value={tech}
          commodityIds={commodityIds}
          onAddCommodity={(id) =>
            editLib(sel.libId, (l) => ({ ...l, commodities: [...l.commodities, { commodity_id: id, kind: "material", unit: "unit" } as CommodityTemplate] }))
          }
          onChange={(v) => editLib(sel.libId, (l) => ({ ...l, technologies: l.technologies.map((t) => (t.technology_id === m.technology ? v : t)) }))}
          onRename={(id) =>
            editLib(sel.libId, (l) => ({
              ...l,
              technologies: l.technologies.map((t) => (t.technology_id === m.technology ? { ...t, technology_id: id } : t)),
              machines: l.machines.map((mm) => (mm.name === m.name ? { ...mm, technology: id } : mm)),
            }))
          }
        />
      ) : (
        <p className="muted" style={{ fontSize: "0.78rem" }}>No recipe — pick or type a technology above.</p>
      );
      return (
        <MachineEditor
          value={m}
          techIds={techIds}
          commodityIds={commodityIds}
          embeddedTech={recipe}
          onChange={(v) => editLib(sel.libId, (l) => ({ ...l, machines: l.machines.map((x) => (x.name === sel.name ? v : x)) }))}
          onRename={(name) => setSel({ libId: sel.libId, kind: "machine", name })}
        />
      );
    }
    // group
    const g = body.groups.find((x) => x.name === sel.name);
    if (!g) return null;
    return (
      <GroupEditor
        value={g}
        componentNames={componentNames.filter((nm) => nm !== sel.name)}
        onChange={(v) => editLib(sel.libId, (l) => ({ ...l, groups: l.groups.map((x) => (x.name === sel.name ? v : x)) }))}
        onRename={(name) => setSel({ libId: sel.libId, kind: "group", name })}
      />
    );
  }

  // ── Context menu actions ──────────────────────────────────────────────────────
  function actionsFor(node: TreeNode): TreeAction[] {
    if (node.kind === "library")
      return [
        { id: "add-machine", label: "Add component" },
        { id: "add-group", label: "Add group" },
        { id: "rename-lib", label: "Rename library" },
        { id: "delete-lib", label: "Delete library", danger: true, separatorBefore: true },
      ];
    return [
      { id: "rename", label: "Rename" },
      { id: "delete", label: "Delete", danger: true },
    ];
  }
  function onContextAction(actionId: string, node: TreeNode) {
    const s = parseTreeId(node.id);
    if (actionId === "add-machine") addMachine(s.libId);
    else if (actionId === "add-group") addGroup(s.libId);
    else if (actionId === "delete-lib") void removeLibrary(s.libId);
    else if (actionId === "rename-lib") {
      const label = window.prompt("Library label:", libs.find((l) => l.id === s.libId)?.label ?? s.libId);
      if (label != null) editLib(s.libId, (l) => ({ ...l, label }));
    } else if (actionId === "delete") deleteComponent(s);
    else if (actionId === "rename") {
      const name = window.prompt("New name:", s.name)?.trim();
      if (!name || !s.name) return;
      editLib(s.libId, (l) =>
        s.kind === "machine"
          ? { ...l, machines: l.machines.map((m) => (m.name === s.name ? { ...m, name } : m)) }
          : {
              ...l,
              groups: l.groups
                .map((g) => (g.name === s.name ? { ...g, name } : g))
                // fix references to the renamed component in other groups' children
                .map((g) => ({ ...g, children: g.children.map((c) => (c.component === s.name ? { ...c, component: name } : c)) })),
            },
      );
      setSel({ libId: s.libId, kind: s.kind, name });
    }
  }

  return (
    <div className="view-full builder" style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {error && (
        <div className="error" style={{ padding: "4px 12px" }} onClick={() => setError(null)}>
          {error} <span className="muted">(dismiss)</span>
        </div>
      )}
      <div style={{ display: "flex", height: "100%", minHeight: 0 }}>
        <aside style={{ width: 280, overflow: "auto", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column" }}>
          <div className="rail-head-row" style={{ padding: "6px 10px" }}>
            <span className="rail-head">Libraries</span>
            <button className="rail-add" title="new library" onClick={newLibrary}>＋</button>
          </div>
          <TreeExplorer
            nodes={treeNodes}
            selectedId={sel ? treeIdOf(sel) : null}
            expandedIds={expanded}
            onToggle={(id, exp) => {
              setExpanded((p) => {
                const m = new Set(p);
                if (exp) m.add(id);
                else m.delete(id);
                return m;
              });
              if (exp && id.startsWith("lib:")) void loadLib(id.slice(4));
            }}
            onSelect={(id) => setSel(parseTreeId(id))}
            actionsFor={actionsFor}
            onContextAction={onContextAction}
            onMove={(e) => void moveComponent(e)}
            emptyHint="No libraries — click ＋ to add one."
          />
        </aside>
        <main style={{ flex: 1, overflow: "auto", padding: "16px 20px", minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
            <div className="eyebrow">component builder</div>
            <span className="muted" style={{ fontSize: "0.78rem" }}>{status}</span>
          </div>
          {renderDetail()}
        </main>
      </div>
    </div>
  );
}
