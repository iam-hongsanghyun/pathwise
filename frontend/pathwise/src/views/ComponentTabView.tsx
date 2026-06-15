// Component tab — each library has THREE fixed structures:
//   Technology  (recipe: properties + input/output streams + linked MACCs)
//   Stream      (commodity properties)
//   Measures    (MACC = a group of measures · Individual = reusable measures)
// Left = the structure tree; right-click adds/renames/deletes; the right (main)
// detail shows the properties of the selected item.

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CommodityEditor,
  GroupEditor,
  MaccEditor,
  MachineEditor,
  MeasureEditor,
  TechnologyEditor,
} from "../features/component/editors";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import type { TreeAction, TreeNode } from "../features/tree/types";
import {
  type CommodityTemplate,
  type ComponentLibrary,
  deleteComponentLibrary,
  emptyLibrary,
  getComponentLibrary,
  type GroupComponent,
  type LibrarySummary,
  listComponentLibraries,
  type MaccGroup,
  type MachineComponent,
  type MeasureTemplate,
  saveComponentLibrary,
  type TechnologyTemplate,
} from "../lib/api/components";

type Kind = "library" | "cat" | "tech" | "stream" | "measure" | "macc" | "machinecomp" | "groupcomp";
interface Sel {
  libId: string;
  kind: Kind;
  /** For cat: the category key; for items: the item id. */
  id?: string;
}
const PREFIX: Record<string, Kind> = { t: "tech", s: "stream", m: "measure", g: "macc", mc: "machinecomp", gc: "groupcomp" };
const KIND_PREFIX: Partial<Record<Kind, string>> = { tech: "t", stream: "s", measure: "m", macc: "g", machinecomp: "mc", groupcomp: "gc" };

const uniq = (base: string, taken: Set<string>): string => {
  if (!taken.has(base)) return base;
  let i = 2;
  while (taken.has(`${base}_${i}`)) i++;
  return `${base}_${i}`;
};

function parseId(treeId: string): Sel {
  const parts = treeId.split(":");
  const [prefix, libId] = parts;
  const rest = parts.slice(2).join(":");
  if (prefix === "lib") return { libId, kind: "library" };
  if (prefix === "cat") return { libId, kind: "cat", id: rest };
  return { libId, kind: PREFIX[prefix] ?? "tech", id: rest };
}
function treeIdOf(s: Sel): string {
  if (s.kind === "library") return `lib:${s.libId}`;
  if (s.kind === "cat") return `cat:${s.libId}:${s.id}`;
  return `${KIND_PREFIX[s.kind]}:${s.libId}:${s.id}`;
}

export function ComponentTabView() {
  const [libs, setLibs] = useState<LibrarySummary[]>([]);
  const [openLibs, setOpenLibs] = useState<Map<string, ComponentLibrary>>(new Map());
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [sel, setSel] = useState<Sel | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const saved = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    listComponentLibraries().then(setLibs).catch((e) => setError(String(e)));
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
      return new Map(prev).set(libId, fn(structuredClone(cur)));
    });
    setDirty((prev) => new Set(prev).add(libId));
  }

  // ── Tree adapter: library → {Technology, Stream, Measures{MACC, Individual}} ──
  const treeNodes = useMemo<TreeNode[]>(() => {
    const out: TreeNode[] = [];
    const cat = (libId: string, key: string, label: string, parent: string, has: boolean): void => {
      out.push({ id: `cat:${libId}:${key}`, parentId: parent, kind: "group", label, hasChildren: has, draggable: false, droppable: false });
    };
    for (const l of libs) {
      out.push({ id: `lib:${l.id}`, parentId: null, kind: "library", label: l.label || l.id, hasChildren: true, draggable: false, droppable: false });
      const body = openLibs.get(l.id);
      const tn = body ? body.technologies.length : l.technologies;
      const sn = body ? body.commodities.length : l.commodities;
      cat(l.id, "tech", "Technology", `lib:${l.id}`, tn > 0);
      cat(l.id, "stream", "Stream", `lib:${l.id}`, sn > 0);
      cat(l.id, "measures", "Measures", `lib:${l.id}`, true);
      if (!body) continue;
      for (const t of body.technologies) out.push({ id: `t:${l.id}:${t.technology_id}`, parentId: `cat:${l.id}:tech`, kind: "leaf", label: t.technology_id, hasChildren: false, draggable: false, droppable: false });
      for (const c of body.commodities) out.push({ id: `s:${l.id}:${c.commodity_id}`, parentId: `cat:${l.id}:stream`, kind: "leaf", label: c.commodity_id, hasChildren: false, draggable: false, droppable: false });
      cat(l.id, "macc", "MACC", `cat:${l.id}:measures`, body.maccs.length > 0);
      cat(l.id, "indiv", "Individual", `cat:${l.id}:measures`, body.measures.length > 0);
      for (const g of body.maccs) out.push({ id: `g:${l.id}:${g.macc_id}`, parentId: `cat:${l.id}:macc`, kind: "leaf", label: g.label || g.macc_id, hasChildren: false, draggable: false, droppable: false });
      for (const m of body.measures) out.push({ id: `m:${l.id}:${m.measure_id}`, parentId: `cat:${l.id}:indiv`, kind: "leaf", label: m.label || m.measure_id, hasChildren: false, draggable: false, droppable: false });
      // Components = the placeable units: single machines + composite groups (e.g. CCGT).
      cat(l.id, "components", "Components", `lib:${l.id}`, body.machines.length + body.groups.length > 0);
      for (const g of body.groups) out.push({ id: `gc:${l.id}:${g.name}`, parentId: `cat:${l.id}:components`, kind: "group", label: g.label || g.name, level: g.level, hasChildren: false, draggable: false, droppable: false });
      for (const m of body.machines) out.push({ id: `mc:${l.id}:${m.name}`, parentId: `cat:${l.id}:components`, kind: "leaf", label: m.label || m.name, hasChildren: false, draggable: false, droppable: false });
    }
    return out;
  }, [libs, openLibs]);

  // ── Add / rename / delete ────────────────────────────────────────────────────
  function addTech(libId: string) {
    editLib(libId, (l) => {
      const id = uniq("Technology", new Set(l.technologies.map((t) => t.technology_id)));
      const tech: TechnologyTemplate = { technology_id: id, lifespan: 20, capex: 0, opex: 0, io: [], maccs: [] };
      setSel({ libId, kind: "tech", id });
      setExpanded((p) => new Set(p).add(`lib:${libId}`).add(`cat:${libId}:tech`));
      return { ...l, technologies: [...l.technologies, tech] };
    });
  }
  function addStream(libId: string) {
    editLib(libId, (l) => {
      const id = uniq("stream", new Set(l.commodities.map((c) => c.commodity_id)));
      setSel({ libId, kind: "stream", id });
      setExpanded((p) => new Set(p).add(`lib:${libId}`).add(`cat:${libId}:stream`));
      return { ...l, commodities: [...l.commodities, { commodity_id: id, kind: "material", unit: "unit" } as CommodityTemplate] };
    });
  }
  function addMeasure(libId: string) {
    editLib(libId, (l) => {
      const id = uniq("measure", new Set(l.measures.map((m) => m.measure_id)));
      const m: MeasureTemplate = { measure_id: id, label: "", type: "energy_efficiency", target: l.commodities[0]?.commodity_id ?? "", lifetime: 15, blocks: [{ reduction: 0.05, capex_per_capacity: 0, opex_per_capacity: 0 }] };
      setSel({ libId, kind: "measure", id });
      setExpanded((p) => new Set(p).add(`lib:${libId}`).add(`cat:${libId}:measures`).add(`cat:${libId}:indiv`));
      return { ...l, measures: [...l.measures, m] };
    });
  }
  function addMacc(libId: string) {
    editLib(libId, (l) => {
      const id = uniq("macc", new Set(l.maccs.map((g) => g.macc_id)));
      setSel({ libId, kind: "macc", id });
      setExpanded((p) => new Set(p).add(`lib:${libId}`).add(`cat:${libId}:measures`).add(`cat:${libId}:macc`));
      return { ...l, maccs: [...l.maccs, { macc_id: id, label: "", measures: [] } as MaccGroup] };
    });
  }
  function addMachineComp(libId: string) {
    editLib(libId, (l) => {
      const id = uniq("machine", new Set([...l.machines.map((m) => m.name), ...l.groups.map((g) => g.name)]));
      const m: MachineComponent = { name: id, label: "", technology: l.technologies[0]?.technology_id ?? "", capacity: 1000, measures: [] };
      setSel({ libId, kind: "machinecomp", id });
      setExpanded((p) => new Set(p).add(`lib:${libId}`).add(`cat:${libId}:components`));
      return { ...l, machines: [...l.machines, m] };
    });
  }
  function addGroupComp(libId: string) {
    editLib(libId, (l) => {
      const id = uniq("group", new Set([...l.machines.map((m) => m.name), ...l.groups.map((g) => g.name)]));
      const g: GroupComponent = { name: id, label: "", level: "facility", children: [], connections: [] };
      setSel({ libId, kind: "groupcomp", id });
      setExpanded((p) => new Set(p).add(`lib:${libId}`).add(`cat:${libId}:components`));
      return { ...l, groups: [...l.groups, g] };
    });
  }
  function deleteItem(s: Sel) {
    editLib(s.libId, (l) => {
      if (s.kind === "tech") return { ...l, technologies: l.technologies.filter((t) => t.technology_id !== s.id) };
      if (s.kind === "stream") return { ...l, commodities: l.commodities.filter((c) => c.commodity_id !== s.id) };
      if (s.kind === "measure") return { ...l, measures: l.measures.filter((m) => m.measure_id !== s.id), maccs: l.maccs.map((g) => ({ ...g, measures: g.measures.filter((x) => x !== s.id) })) };
      if (s.kind === "macc") return { ...l, maccs: l.maccs.filter((g) => g.macc_id !== s.id), technologies: l.technologies.map((t) => ({ ...t, maccs: t.maccs.filter((x) => x !== s.id) })) };
      if (s.kind === "machinecomp") return { ...l, machines: l.machines.filter((m) => m.name !== s.id), groups: l.groups.map((g) => ({ ...g, children: g.children.filter((c) => c.component !== s.id) })) };
      if (s.kind === "groupcomp") return { ...l, groups: l.groups.filter((g) => g.name !== s.id).map((g) => ({ ...g, children: g.children.filter((c) => c.component !== s.id) })) };
      return l;
    });
    setSel({ libId: s.libId, kind: "library" });
  }
  function renameItem(s: Sel, name: string) {
    editLib(s.libId, (l) => {
      if (s.kind === "tech") return { ...l, technologies: l.technologies.map((t) => (t.technology_id === s.id ? { ...t, technology_id: name } : t)), machines: l.machines.map((m) => (m.technology === s.id ? { ...m, technology: name } : m)) };
      if (s.kind === "stream") return { ...l, commodities: l.commodities.map((c) => (c.commodity_id === s.id ? { ...c, commodity_id: name } : c)) };
      if (s.kind === "measure") return { ...l, measures: l.measures.map((m) => (m.measure_id === s.id ? { ...m, measure_id: name } : m)), maccs: l.maccs.map((g) => ({ ...g, measures: g.measures.map((x) => (x === s.id ? name : x)) })) };
      if (s.kind === "macc") return { ...l, maccs: l.maccs.map((g) => (g.macc_id === s.id ? { ...g, macc_id: name } : g)), technologies: l.technologies.map((t) => ({ ...t, maccs: t.maccs.map((x) => (x === s.id ? name : x)) })) };
      const fixChildren = (g: GroupComponent) => ({ ...g, children: g.children.map((c) => (c.component === s.id ? { ...c, component: name } : c)) });
      if (s.kind === "machinecomp") return { ...l, machines: l.machines.map((m) => (m.name === s.id ? { ...m, name } : m)), groups: l.groups.map(fixChildren) };
      if (s.kind === "groupcomp") return { ...l, groups: l.groups.map((g) => (g.name === s.id ? { ...g, name } : g)).map(fixChildren) };
      return l;
    });
    setSel({ ...s, id: name });
  }

  async function newLibrary() {
    const id = window.prompt("New library id (letters, digits, -_.):", "")?.trim();
    if (!id) return;
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(id)) return setError(`invalid library id '${id}'`);
    try {
      await saveComponentLibrary(id, emptyLibrary(id));
      setLibs(await listComponentLibraries());
      setExpanded((p) => new Set(p).add(`lib:${id}`));
      await loadLib(id);
      setSel({ libId: id, kind: "library" });
    } catch (e) {
      setError(String(e));
    }
  }
  async function removeLibrary(id: string) {
    if (!window.confirm(`Delete library '${id}'?`)) return;
    try {
      await deleteComponentLibrary(id);
      setLibs(await listComponentLibraries());
      setOpenLibs((p) => { const m = new Map(p); m.delete(id); return m; });
      if (sel?.libId === id) setSel(null);
    } catch (e) {
      setError(String(e));
    }
  }

  // ── Context menu ──────────────────────────────────────────────────────────────
  function actionsFor(node: TreeNode): TreeAction[] {
    const s = parseId(node.id);
    if (s.kind === "library")
      return [
        { id: "add-tech", label: "Add technology" },
        { id: "add-stream", label: "Add stream" },
        { id: "add-measure", label: "Add measure" },
        { id: "add-macc", label: "Add MACC" },
        { id: "add-machine", label: "Add component (single)" },
        { id: "add-group", label: "Add component (group)" },
        { id: "rename-lib", label: "Rename library", separatorBefore: true },
        { id: "delete-lib", label: "Delete library", danger: true },
      ];
    if (s.kind === "cat") {
      const map: Record<string, TreeAction[]> = {
        tech: [{ id: "add-tech", label: "Add technology" }],
        stream: [{ id: "add-stream", label: "Add stream" }],
        measures: [{ id: "add-measure", label: "Add measure" }, { id: "add-macc", label: "Add MACC" }],
        macc: [{ id: "add-macc", label: "Add MACC" }],
        indiv: [{ id: "add-measure", label: "Add measure" }],
        components: [{ id: "add-machine", label: "Add single component" }, { id: "add-group", label: "Add group component" }],
      };
      return map[s.id ?? ""] ?? [];
    }
    return [
      { id: "rename", label: "Rename" },
      { id: "delete", label: "Delete", danger: true },
    ];
  }
  function onContextAction(actionId: string, node: TreeNode) {
    const s = parseId(node.id);
    if (actionId === "add-tech") addTech(s.libId);
    else if (actionId === "add-stream") addStream(s.libId);
    else if (actionId === "add-measure") addMeasure(s.libId);
    else if (actionId === "add-macc") addMacc(s.libId);
    else if (actionId === "add-machine") addMachineComp(s.libId);
    else if (actionId === "add-group") addGroupComp(s.libId);
    else if (actionId === "delete-lib") void removeLibrary(s.libId);
    else if (actionId === "rename-lib") {
      const label = window.prompt("Library label:", libs.find((l) => l.id === s.libId)?.label ?? s.libId);
      if (label != null) editLib(s.libId, (l) => ({ ...l, label }));
    } else if (actionId === "delete") deleteItem(s);
    else if (actionId === "rename") {
      const name = window.prompt("New id:", s.id)?.trim();
      if (name) renameItem(s, name);
    }
  }

  // ── Detail ─────────────────────────────────────────────────────────────────────
  const body = sel ? openLibs.get(sel.libId) : undefined;
  const commodityIds = useMemo(() => (body?.commodities ?? []).map((c) => c.commodity_id), [body]);

  function renderDetail() {
    if (!sel || !body) return <p className="muted">Pick or create a library on the left to start building.</p>;
    if (sel.kind === "library" || sel.kind === "cat") {
      const l = libs.find((x) => x.id === sel.libId);
      return (
        <section>
          <h2 style={{ margin: "0 0 8px" }}>{body.label || sel.libId}</h2>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: "0.8rem", marginBottom: 12 }}>
            <span className="muted">label</span>
            <input style={{ ...inp, flex: 1, maxWidth: 280 }} value={body.label} onChange={(e) => editLib(sel.libId, (lib) => ({ ...lib, label: e.target.value }))} />
          </label>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
            <button className="ghost" onClick={() => addTech(sel.libId)}>＋ Technology</button>
            <button className="ghost" onClick={() => addStream(sel.libId)}>＋ Stream</button>
            <button className="ghost" onClick={() => addMeasure(sel.libId)}>＋ Measure</button>
            <button className="ghost" onClick={() => addMacc(sel.libId)}>＋ MACC</button>
            <button className="ghost" onClick={() => addMachineComp(sel.libId)}>＋ Component</button>
            <button className="ghost" onClick={() => addGroupComp(sel.libId)}>＋ Group</button>
          </div>
          <p className="muted" style={{ fontSize: "0.78rem" }}>
            {l?.technologies ?? 0} technologies · {l?.commodities ?? 0} streams · {l?.measures ?? 0} measures · {l?.maccs ?? 0} MACCs.
            {" "}A technology gets its own input/output streams; measures are reusable and bundled into MACCs; a technology links the MACCs that apply to it.
          </p>
        </section>
      );
    }
    if (sel.kind === "tech") {
      const t = body.technologies.find((x) => x.technology_id === sel.id);
      if (!t) return null;
      const setTech = (v: TechnologyTemplate) => editLib(sel.libId, (l) => ({ ...l, technologies: l.technologies.map((x) => (x.technology_id === sel.id ? v : x)) }));
      const toggleMacc = (mid: string, on: boolean) => setTech({ ...t, maccs: on ? [...t.maccs, mid] : t.maccs.filter((x) => x !== mid) });
      return (
        <>
          <TechnologyEditor
            value={t}
            commodityIds={commodityIds}
            onAddCommodity={(id) => editLib(sel.libId, (l) => ({ ...l, commodities: [...l.commodities, { commodity_id: id, kind: "material", unit: "unit" } as CommodityTemplate] }))}
            onChange={setTech}
            onRename={(id) => setSel({ libId: sel.libId, kind: "tech", id })}
          />
          <div className="rail-section" style={{ marginTop: 12 }}>
            <div className="rail-head">Applicable MACCs</div>
            {body.maccs.length === 0 && <div className="rail-empty" style={{ fontSize: "0.74rem" }}>no MACCs in this library yet</div>}
            {body.maccs.map((g) => (
              <label key={g.macc_id} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: "0.82rem", padding: "2px 8px" }}>
                <input type="checkbox" checked={t.maccs.includes(g.macc_id)} onChange={(e) => toggleMacc(g.macc_id, e.target.checked)} />
                {g.label || g.macc_id}
              </label>
            ))}
          </div>
        </>
      );
    }
    if (sel.kind === "stream") {
      const c = body.commodities.find((x) => x.commodity_id === sel.id);
      if (!c) return null;
      const targeting = body.measures.filter((m) => m.target === sel.id).map((m) => m.label || m.measure_id);
      return (
        <>
          <CommodityEditor
            value={c}
            onChange={(v) => editLib(sel.libId, (l) => ({ ...l, commodities: l.commodities.map((x) => (x.commodity_id === sel.id ? v : x)) }))}
            onRename={(id) => setSel({ libId: sel.libId, kind: "stream", id })}
          />
          <div className="rail-section" style={{ marginTop: 12 }}>
            <div className="rail-head">Measures targeting this stream</div>
            <div className="rail-empty" style={{ fontSize: "0.78rem" }}>{targeting.length ? targeting.join(", ") : "none"}</div>
          </div>
        </>
      );
    }
    if (sel.kind === "measure") {
      const m = body.measures.find((x) => x.measure_id === sel.id);
      if (!m) return null;
      return (
        <MeasureEditor
          value={m}
          commodityIds={commodityIds}
          onChange={(v) => editLib(sel.libId, (l) => ({ ...l, measures: l.measures.map((x) => (x.measure_id === sel.id ? v : x)) }))}
          onRename={(id) => setSel({ libId: sel.libId, kind: "measure", id })}
        />
      );
    }
    if (sel.kind === "machinecomp") {
      const m = body.machines.find((x) => x.name === sel.id);
      if (!m) return null;
      return (
        <MachineEditor
          value={m}
          techIds={body.technologies.map((t) => t.technology_id)}
          commodityIds={commodityIds}
          onChange={(v) => editLib(sel.libId, (l) => ({ ...l, machines: l.machines.map((x) => (x.name === sel.id ? v : x)) }))}
          onRename={(id) => setSel({ libId: sel.libId, kind: "machinecomp", id })}
        />
      );
    }
    if (sel.kind === "groupcomp") {
      const gc = body.groups.find((x) => x.name === sel.id);
      if (!gc) return null;
      return (
        <GroupEditor
          value={gc}
          componentNames={[...body.machines.map((m) => m.name), ...body.groups.map((x) => x.name)].filter((n) => n !== sel.id)}
          commodityIds={commodityIds}
          onChange={(v) => editLib(sel.libId, (l) => ({ ...l, groups: l.groups.map((x) => (x.name === sel.id ? v : x)) }))}
          onRename={(id) => setSel({ libId: sel.libId, kind: "groupcomp", id })}
        />
      );
    }
    // macc
    const g = body.maccs.find((x) => x.macc_id === sel.id);
    if (!g) return null;
    return (
      <MaccEditor
        value={g}
        measures={body.measures.map((m) => ({ id: m.measure_id, label: m.label || m.measure_id }))}
        onChange={(v) => editLib(sel.libId, (l) => ({ ...l, maccs: l.maccs.map((x) => (x.macc_id === sel.id ? v : x)) }))}
        onRename={(id) => setSel({ libId: sel.libId, kind: "macc", id })}
      />
    );
  }

  return (
    <div className="view-full builder" style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {error && <div className="error" style={{ padding: "4px 12px" }} onClick={() => setError(null)}>{error} <span className="muted">(dismiss)</span></div>}
      <div style={{ display: "flex", height: "100%", minHeight: 0 }}>
        <aside style={{ width: 280, overflow: "auto", borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", flexShrink: 0 }}>
          <div className="rail-head-row" style={{ padding: "6px 10px" }}>
            <span className="rail-head">Libraries</span>
            <button className="rail-add" title="new library" onClick={newLibrary}>＋</button>
          </div>
          <TreeExplorer
            nodes={treeNodes}
            selectedId={sel ? treeIdOf(sel) : null}
            expandedIds={expanded}
            onToggle={(id, exp) => {
              setExpanded((p) => { const m = new Set(p); if (exp) m.add(id); else m.delete(id); return m; });
              if (exp && id.startsWith("lib:")) void loadLib(id.slice(4));
            }}
            onSelect={(id) => setSel(parseId(id))}
            actionsFor={actionsFor}
            onContextAction={onContextAction}
            onMove={() => undefined}
            emptyHint="No libraries — click ＋ to add one."
          />
          <div className="muted" style={{ fontSize: "0.7rem", padding: "8px 10px", borderTop: "1px solid var(--border)" }}>Right-click for actions</div>
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

const inp: React.CSSProperties = {
  padding: "4px 6px",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-button)",
  background: "var(--surface)",
  font: "inherit",
};
