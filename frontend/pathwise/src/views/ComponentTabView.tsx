// Component tab — each library has THREE fixed structures:
//   Technology  (recipe: properties + input/output streams + linked MACCs)
//   Stream      (commodity properties)
//   Measures    (MACC = a group of measures · Individual = reusable measures)
// Left = the structure tree; right-click adds/renames/deletes; the right (main)
// detail shows the properties of the selected item.

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CommodityEditor,
  MaccEditor,
  MeasureEditor,
  TechnologyEditor,
} from "../features/component/editors";
import { TimeSeriesRail } from "../features/component/TimeSeriesRail";
import { Resizer } from "../layout/Resizer";
import { useDialogs } from "../features/controls/Dialog";
import { SearchSelect } from "../features/controls/SearchSelect";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import type { TreeAction, TreeNode } from "../features/tree/types";
import {
  type CatalogEntry,
  type CommodityTemplate,
  type ComponentCatalogKind,
  type ComponentLibrary,
  copyComponentIntoProject,
  deleteComponentLibrary,
  deleteSessionComponentLibrary,
  emptyLibrary,
  getComponentLibrary,
  getSessionComponentLibrary,
  type LibrarySummary,
  type LibScope,
  listAllComponentLibraries,
  listComponentCatalog,
  type MaccGroup,
  type MeasureTemplate,
  saveComponentLibrary,
  saveSessionComponentLibrary,
  type TechnologyTemplate,
} from "../lib/api/components";
import { allowedUnits, getUnits } from "../lib/api/units";

// A library is addressed as `${scope}/${id}` ("base/power", "session/steel") so
// base and session libraries with the same id never collide in the tree.
const splitLib = (libId: string): [LibScope, string] => {
  const i = libId.indexOf("/");
  return i < 0 ? ["base", libId] : [libId.slice(0, i) as LibScope, libId.slice(i + 1)];
};
const keyOf = (l: LibrarySummary): string => `${l.scope}/${l.id}`;
const getLib = (libId: string, sid: string | null): Promise<ComponentLibrary> => {
  const [scope, id] = splitLib(libId);
  return scope === "session" && sid ? getSessionComponentLibrary(sid, id) : getComponentLibrary(id);
};
const saveLib = (libId: string, body: ComponentLibrary, sid: string | null): Promise<LibrarySummary> => {
  const [scope, id] = splitLib(libId);
  return scope === "session" && sid ? saveSessionComponentLibrary(sid, id, body) : saveComponentLibrary(id, body);
};
const removeLib = (libId: string, sid: string | null): Promise<void> => {
  const [scope, id] = splitLib(libId);
  return scope === "session" && sid ? deleteSessionComponentLibrary(sid, id) : deleteComponentLibrary(id);
};

/** Why the backend would reject this library as an incomplete draft, or null if
 *  it is saveable. Mirrors the `min_length` constraints in `data/templates.py`
 *  (a technology needs ≥1 io row; a measure needs ≥1 cost block) so a freshly
 *  added, not-yet-filled component is held back from autosave instead of 422ing. */
function draftBlocker(body: ComponentLibrary): string | null {
  const t = body.technologies.find((x) => x.io.length === 0);
  if (t) return `add an input or output to “${t.technology_id}”`;
  const m = body.measures.find((x) => x.blocks.length === 0);
  if (m) return `add a cost block to “${m.measure_id}”`;
  return null;
}

type Kind = "library" | "cat" | "tech" | "stream" | "measure" | "macc";
interface Sel {
  libId: string;
  kind: Kind;
  /** For cat: the category key; for items: the item id. */
  id?: string;
}
const PREFIX: Record<string, Kind> = { t: "tech", s: "stream", m: "measure", g: "macc" };
const KIND_PREFIX: Partial<Record<Kind, string>> = { tech: "t", stream: "s", measure: "m", macc: "g" };

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

// ── Sector bucketing (shared by the tree and the detail panel) ─────────────────
// A stream belongs to the sector that PRODUCES it; a library shows only the
// streams its technologies OUTPUT (a pure input like electricity is produced
// elsewhere, so it is hidden). A technology files under the sector of its
// product; measures/MACCs under the sector of the technology that links them.
// Anything unclassified falls under "Other".
const OTHER = "Other";
export interface Bucket {
  techs: TechnologyTemplate[];
  streams: CommodityTemplate[];
  maccs: MaccGroup[];
  measures: MeasureTemplate[];
}
export function libraryBuckets(body: ComponentLibrary): { order: string[]; buckets: Map<string, Bucket> } {
  const sec = (s: string | null | undefined): string => (s && s.trim()) || OTHER;
  const secOf = new Map(body.commodities.map((c) => [c.commodity_id, c.sector]));
  const produced = new Set<string>();
  const consumed = new Set<string>();
  for (const t of body.technologies)
    for (const r of t.io) {
      if (r.role === "output") produced.add(r.target);
      else if (r.role === "input") consumed.add(r.target);
    }
  const techSector = (t: TechnologyTemplate): string => {
    const outs = t.io.filter((r) => r.role === "output");
    const prod = outs.find((r) => r.is_product) ?? outs[0];
    return prod ? sec(secOf.get(prod.target)) : OTHER;
  };
  const measSectorOf = new Map<string, string>();
  const maccSectorOf = new Map<string, string>();
  for (const t of body.technologies) {
    const ts = techSector(t);
    for (const mid of t.maccs) {
      if (!maccSectorOf.has(mid)) maccSectorOf.set(mid, ts);
      for (const meas of body.maccs.find((g) => g.macc_id === mid)?.measures ?? [])
        if (!measSectorOf.has(meas)) measSectorOf.set(meas, ts);
    }
  }
  const buckets = new Map<string, Bucket>();
  const B = (s: string): Bucket => {
    let b = buckets.get(s);
    if (!b) buckets.set(s, (b = { techs: [], streams: [], maccs: [], measures: [] }));
    return b;
  };
  for (const t of body.technologies) B(techSector(t)).techs.push(t);
  for (const c of body.commodities) {
    const isOut = produced.has(c.commodity_id);
    if (!isOut && consumed.has(c.commodity_id)) continue; // pure input → produced elsewhere
    B(isOut ? sec(c.sector) : OTHER).streams.push(c); // standalone (neither) → Other
  }
  for (const g of body.maccs) B(maccSectorOf.get(g.macc_id) ?? OTHER).maccs.push(g);
  for (const m of body.measures) B(measSectorOf.get(m.measure_id) ?? sec(secOf.get(m.target))).measures.push(m);
  const order = [...buckets.keys()].sort((a, b) => (a === OTHER ? 1 : b === OTHER ? -1 : a.localeCompare(b)));
  return { order, buckets };
}

// Module-level so its identity is stable across renders (a component defined
// inside render would remount its inputs on every keystroke, dropping focus).
function BucketShell({ title, add, children }: { title: string; add?: () => void; children: React.ReactNode }) {
  return (
    <section>
      <h2 style={{ margin: "0 0 4px" }}>{title}</h2>
      <p className="muted" style={{ fontSize: "0.74rem", margin: "0 0 10px" }}>Edit values inline — changes autosave. Click an id to open the full item.</p>
      {add && <button className="ghost" style={{ marginBottom: 8 }} onClick={add}>＋ add</button>}
      {children}
    </section>
  );
}

/** Two surfaces share this one editor:
 *  - "library": author the shared base catalogue (base libraries only).
 *  - "project": one ACTIVE project's working set; base is a read-only copy source
 *    reached through the "+ add → copy from a library" picker. */
export function ComponentTabView({
  sessionId,
  mode = "library",
  activeProjectId = null,
  setActiveProjectId,
}: {
  sessionId: string | null;
  mode?: "library" | "project";
  activeProjectId?: string | null;
  setActiveProjectId?: (id: string | null) => void;
}) {
  const { prompt, confirm, node: dialogNode } = useDialogs();
  const [libs, setLibs] = useState<LibrarySummary[]>([]);
  const [openLibs, setOpenLibs] = useState<Map<string, ComponentLibrary>>(new Map());
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [sel, setSel] = useState<Sel | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [rightW, setRightW] = useState(340); // resizable right-rail (time series) width
  const [unitOptions, setUnitOptions] = useState<string[]>([]); // allowed units for the IO unit picker
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]); // copy-source pool (project mode)
  const [copyKind, setCopyKind] = useState<ComponentCatalogKind>("technology");
  const saved = useRef<Map<string, string>>(new Map());

  // The session's projects, and the active one addressed as a session library id.
  const sessionProjects = libs.filter((l) => l.scope === "session");
  const activeLibId = activeProjectId ? `session/${activeProjectId}` : null;

  // Base (shared) + this session's own libraries (an imported project's set).
  useEffect(() => {
    listAllComponentLibraries(sessionId).then(setLibs).catch((e) => setError(String(e)));
  }, [sessionId]);

  // Copy-source catalogue (every component across base + session libs), project mode.
  async function loadCatalog() {
    if (!sessionId) return;
    try {
      setCatalog(await listComponentCatalog(sessionId));
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    if (mode === "project" && sessionId) void loadCatalog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, sessionId]);

  // Project mode: default the active project to the first one when unset/stale,
  // and keep the selection + loaded body pointed at it.
  useEffect(() => {
    if (mode !== "project") return;
    if (setActiveProjectId && (!activeProjectId || !sessionProjects.some((l) => l.id === activeProjectId))) {
      setActiveProjectId(sessionProjects[0]?.id ?? null);
      return;
    }
    if (activeLibId) {
      void loadLib(activeLibId);
      setSel((cur) => (cur && cur.libId === activeLibId ? cur : { libId: activeLibId, kind: "library" }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, activeProjectId, libs]);

  // Allowed units for the recipe unit picker (the backend is the source of truth).
  useEffect(() => {
    getUnits().then((u) => setUnitOptions(allowedUnits(u.config))).catch(() => setUnitOptions([]));
  }, []);

  async function loadLib(libId: string) {
    if (openLibs.has(libId)) return;
    try {
      const body = await getLib(libId, sessionId);
      saved.current.set(libId, JSON.stringify(body));
      setOpenLibs((prev) => new Map(prev).set(libId, body));
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    if (dirty.size === 0) return;
    setStatus("saving…");
    const t = setTimeout(async () => {
      const remaining = new Set<string>(); // incomplete drafts held back from save
      let blocked: string | null = null;
      try {
        for (const libId of dirty) {
          const body = openLibs.get(libId);
          if (!body) continue;
          const why = draftBlocker(body);
          if (why) {
            remaining.add(libId); // hold off — the backend would 422 this draft
            blocked = why;
            continue;
          }
          const summary = await saveLib(libId, body, sessionId);
          saved.current.set(libId, JSON.stringify(body));
          setLibs((prev) => prev.map((x) => (keyOf(x) === libId ? summary : x)));
        }
        // Only shrink `dirty` when something saved — re-setting it to the same
        // skipped set would re-trigger this effect in a loop.
        if (remaining.size !== dirty.size) setDirty(remaining);
        setStatus(blocked ? `draft — ${blocked}` : "saved");
      } catch (e) {
        setStatus("save failed");
        setError(String(e));
      }
    }, 600);
    return () => clearTimeout(t);
  }, [dirty, openLibs, sessionId]);

  function editLib(libId: string, fn: (l: ComponentLibrary) => ComponentLibrary) {
    setOpenLibs((prev) => {
      const cur = prev.get(libId);
      if (!cur) return prev;
      return new Map(prev).set(libId, fn(structuredClone(cur)));
    });
    setDirty((prev) => new Set(prev).add(libId));
  }

  // ── Tree: library → Sector → {Technology, Stream (outputs), Measures & MACC} ──
  const treeNodes = useMemo<TreeNode[]>(() => {
    const out: TreeNode[] = [];
    const node = (id: string, parentId: string, label: string, kind: TreeNode["kind"], has: boolean): void => {
      out.push({ id, parentId, kind, label, hasChildren: has, draggable: false, droppable: false });
    };

    for (const l of libs) {
      const lk = keyOf(l); // compound `${scope}/${id}`
      const tag = l.scope === "session" ? " · project" : " · base";
      out.push({ id: `lib:${lk}`, parentId: null, kind: "library", label: `${l.label || l.id}${tag}`, hasChildren: true, draggable: false, droppable: false });
      const body = openLibs.get(lk);
      if (!body) continue;

      const { order, buckets } = libraryBuckets(body);
      // Sector → Group → Components, but the sector level is only worth showing
      // when the library spans more than one sector; otherwise the groups
      // (Technology / Stream / Measures) hang straight off the library.
      const multiSector = order.length > 1;
      for (const s of order) {
        const b = buckets.get(s)!;
        const secId = `cat:${lk}:${s}`;
        const groupParent = multiSector ? secId : `lib:${lk}`;
        if (multiSector) node(secId, `lib:${lk}`, s, "group", true);
        node(`cat:${lk}:${s}/tech`, groupParent, "Technology", "group", b.techs.length > 0);
        for (const t of b.techs) node(`t:${lk}:${t.technology_id}`, `cat:${lk}:${s}/tech`, t.technology_id, "leaf", false);
        node(`cat:${lk}:${s}/stream`, groupParent, "Stream", "group", b.streams.length > 0);
        for (const c of b.streams) node(`s:${lk}:${c.commodity_id}`, `cat:${lk}:${s}/stream`, c.commodity_id, "leaf", false);
        node(`cat:${lk}:${s}/measures`, groupParent, "Measures & MACC", "group", b.maccs.length + b.measures.length > 0);
        node(`cat:${lk}:${s}/macc`, `cat:${lk}:${s}/measures`, "MACC", "group", b.maccs.length > 0);
        for (const g of b.maccs) node(`g:${lk}:${g.macc_id}`, `cat:${lk}:${s}/macc`, g.label || g.macc_id, "leaf", false);
        node(`cat:${lk}:${s}/indiv`, `cat:${lk}:${s}/measures`, "Individual", "group", b.measures.length > 0);
        for (const m of b.measures) node(`m:${lk}:${m.measure_id}`, `cat:${lk}:${s}/indiv`, m.label || m.measure_id, "leaf", false);
      }
    }
    return out;
  }, [libs, openLibs]);

  // ── Add / rename / delete ────────────────────────────────────────────────────
  function addTech(libId: string) {
    editLib(libId, (l) => {
      const id = uniq("Technology", new Set(l.technologies.map((t) => t.technology_id)));
      const tech: TechnologyTemplate = { technology_id: id, lifespan: 20, capex: 0, opex: 0, io: [], maccs: [] };
      setSel({ libId, kind: "tech", id });
      // a new item is unclassified until it has an output / link → lands in "Other"
      setExpanded((p) => new Set(p).add(`lib:${libId}`).add(`cat:${libId}:${OTHER}`).add(`cat:${libId}:${OTHER}/tech`));
      return { ...l, technologies: [...l.technologies, tech] };
    });
  }
  function addStream(libId: string, sector: string | null = null) {
    editLib(libId, (l) => {
      const id = uniq("stream", new Set(l.commodities.map((c) => c.commodity_id)));
      setSel({ libId, kind: "stream", id });
      // standalone until produced by a technology → shown under "Other" for now
      setExpanded((p) => new Set(p).add(`lib:${libId}`).add(`cat:${libId}:${OTHER}`).add(`cat:${libId}:${OTHER}/stream`));
      return { ...l, commodities: [...l.commodities, { commodity_id: id, kind: "material", unit: "unit", sector } as CommodityTemplate] };
    });
  }
  function addMeasure(libId: string) {
    editLib(libId, (l) => {
      const id = uniq("measure", new Set(l.measures.map((m) => m.measure_id)));
      const m: MeasureTemplate = { measure_id: id, label: "", type: "energy_efficiency", target: l.commodities[0]?.commodity_id ?? "", lifetime: 15, blocks: [{ reduction: 0.05, capex_per_capacity: 0, opex_per_capacity: 0 }] };
      setSel({ libId, kind: "measure", id });
      setExpanded((p) => new Set(p).add(`lib:${libId}`).add(`cat:${libId}:${OTHER}`).add(`cat:${libId}:${OTHER}/measures`).add(`cat:${libId}:${OTHER}/indiv`));
      return { ...l, measures: [...l.measures, m] };
    });
  }
  function addMacc(libId: string) {
    editLib(libId, (l) => {
      const id = uniq("macc", new Set(l.maccs.map((g) => g.macc_id)));
      setSel({ libId, kind: "macc", id });
      setExpanded((p) => new Set(p).add(`lib:${libId}`).add(`cat:${libId}:${OTHER}`).add(`cat:${libId}:${OTHER}/measures`).add(`cat:${libId}:${OTHER}/macc`));
      return { ...l, maccs: [...l.maccs, { macc_id: id, label: "", measures: [] } as MaccGroup] };
    });
  }
  function deleteItem(s: Sel) {
    editLib(s.libId, (l) => {
      if (s.kind === "tech") return { ...l, technologies: l.technologies.filter((t) => t.technology_id !== s.id) };
      if (s.kind === "stream") return { ...l, commodities: l.commodities.filter((c) => c.commodity_id !== s.id) };
      if (s.kind === "measure") return { ...l, measures: l.measures.filter((m) => m.measure_id !== s.id), maccs: l.maccs.map((g) => ({ ...g, measures: g.measures.filter((x) => x !== s.id) })) };
      if (s.kind === "macc") return { ...l, maccs: l.maccs.filter((g) => g.macc_id !== s.id), technologies: l.technologies.map((t) => ({ ...t, maccs: t.maccs.filter((x) => x !== s.id) })) };
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
      return l;
    });
    setSel({ ...s, id: name });
  }

  async function newLibrary() {
    const id = (await prompt({ title: "New library", label: "id", placeholder: "letters, digits, -_." }))?.trim();
    if (!id) return;
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(id)) return setError(`invalid library id '${id}'`);
    const libId = `base/${id}`; // new libraries go in the shared base catalogue
    try {
      await saveComponentLibrary(id, emptyLibrary(id));
      setLibs(await listAllComponentLibraries(sessionId));
      setExpanded((p) => new Set(p).add(`lib:${libId}`));
      await loadLib(libId);
      setSel({ libId, kind: "library" });
    } catch (e) {
      setError(String(e));
    }
  }

  async function newProject() {
    if (!sessionId) return setError("no backend session yet");
    const id = (await prompt({ title: "New project", label: "id", placeholder: "letters, digits, -_." }))?.trim();
    if (!id) return;
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(id)) return setError(`invalid project id '${id}'`);
    const libId = `session/${id}`; // a project is a session-scoped library
    try {
      await saveSessionComponentLibrary(sessionId, id, emptyLibrary(id));
      setLibs(await listAllComponentLibraries(sessionId));
      setExpanded((p) => new Set(p).add(`lib:${libId}`));
      await loadLib(libId);
      setActiveProjectId?.(id); // make the new project the active one (project mode)
      setSel({ libId, kind: "library" });
    } catch (e) {
      setError(String(e));
    }
  }

  /** Switch the active project (project mode): point the rail + detail at it. */
  function switchProject(id: string) {
    if (!id) return;
    setActiveProjectId?.(id);
    const libId = `session/${id}`;
    void loadLib(libId);
    setSel({ libId, kind: "library" });
  }

  // Hard-copy a catalogue entry (+ its closure) into the active project.
  async function copyEntryIntoActive(entry: CatalogEntry) {
    if (!sessionId || !activeProjectId || !activeLibId) return;
    try {
      // The copy runs server-side on the STORED project, and the refresh below
      // overwrites the local body — so first flush any pending edits to this
      // project, or they'd be lost in the autosave window (600ms debounce).
      const pending = openLibs.get(activeLibId);
      if (dirty.has(activeLibId) && pending) {
        await saveLib(activeLibId, pending, sessionId);
        saved.current.set(activeLibId, JSON.stringify(pending));
        setDirty((d) => {
          const n = new Set(d);
          n.delete(activeLibId);
          return n;
        });
      }
      await copyComponentIntoProject(sessionId, activeProjectId, {
        src_scope: entry.scope,
        src_id: entry.library_id,
        kind: entry.kind,
        component_id: entry.component_id,
      });
      // Force-refresh the active project body (loadLib skips already-open libs).
      const fresh = await getLib(activeLibId, sessionId);
      saved.current.set(activeLibId, JSON.stringify(fresh));
      setOpenLibs((p) => new Map(p).set(activeLibId, fresh));
      setLibs(await listAllComponentLibraries(sessionId));
      void loadCatalog();
      setStatus(`copied ${entry.component_id} → ${activeProjectId}`);
    } catch (e) {
      setError(String(e));
    }
  }
  async function removeLibrary(libId: string) {
    const [, plain] = splitLib(libId);
    if (!(await confirm({ title: "Delete library", message: `Delete library '${plain}'?`, danger: true, confirmLabel: "Delete" }))) return;
    try {
      await removeLib(libId, sessionId);
      setLibs(await listAllComponentLibraries(sessionId));
      setOpenLibs((p) => { const m = new Map(p); m.delete(libId); return m; });
      if (sel?.libId === libId) setSel(null);
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
        { id: "rename-lib", label: "Rename library", separatorBefore: true },
        { id: "delete-lib", label: "Delete library", danger: true },
      ];
    if (s.kind === "cat") {
      // cat id is `${sector}` (the sector group) or `${sector}/<sub>`
      const sub = (s.id ?? "").includes("/") ? (s.id ?? "").split("/")[1] : "";
      const map: Record<string, TreeAction[]> = {
        "": [
          { id: "add-tech", label: "Add technology" },
          { id: "add-stream", label: "Add stream" },
          { id: "add-measure", label: "Add measure" },
          { id: "add-macc", label: "Add MACC" },
        ],
        tech: [{ id: "add-tech", label: "Add technology" }],
        stream: [{ id: "add-stream", label: "Add stream" }],
        measures: [{ id: "add-measure", label: "Add measure" }, { id: "add-macc", label: "Add MACC" }],
        macc: [{ id: "add-macc", label: "Add MACC" }],
        indiv: [{ id: "add-measure", label: "Add measure" }],
      };
      return map[sub] ?? [];
    }
    return [
      { id: "rename", label: "Rename" },
      { id: "delete", label: "Delete", danger: true },
    ];
  }
  async function onContextAction(actionId: string, node: TreeNode) {
    const s = parseId(node.id);
    if (actionId === "add-tech") addTech(s.libId);
    else if (actionId === "add-stream") {
      const sector = s.kind === "cat" ? (s.id ?? "").split("/")[0] : "";
      addStream(s.libId, sector && sector !== OTHER ? sector : null);
    } else if (actionId === "add-measure") addMeasure(s.libId);
    else if (actionId === "add-macc") addMacc(s.libId);
    else if (actionId === "delete-lib") void removeLibrary(s.libId);
    else if (actionId === "rename-lib") {
      const label = await prompt({ title: "Rename library", label: "label", defaultValue: libs.find((l) => keyOf(l) === s.libId)?.label ?? s.libId });
      if (label != null) editLib(s.libId, (l) => ({ ...l, label }));
    } else if (actionId === "delete") deleteItem(s);
    else if (actionId === "rename") {
      const name = (await prompt({ title: "Rename", label: "id", defaultValue: s.id }))?.trim();
      if (name) renameItem(s, name);
    }
  }

  // ── Detail ─────────────────────────────────────────────────────────────────────
  const body = sel ? openLibs.get(sel.libId) : undefined;
  const commodityIds = useMemo(() => (body?.commodities ?? []).map((c) => c.commodity_id), [body]);
  const streamUnit = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of body?.commodities ?? []) if (c.unit) m.set(c.commodity_id, c.unit);
    return (id: string) => m.get(id);
  }, [body]);
  const buckets = useMemo(() => (body ? libraryBuckets(body) : null), [body]);

  // ── Sector (aggregated roll-up) and Bucket (editable table) views ────────────
  function renderCat(raw: string) {
    if (!sel || !body || !buckets) return null;
    const libId = sel.libId;
    const sector = raw.split("/")[0] || OTHER;
    const sub = raw.includes("/") ? raw.split("/")[1] : "";
    const b = buckets.buckets.get(sector);
    if (!b) return <p className="muted">This sector is empty.</p>;
    const drill = (kind: Kind, id: string) => setSel({ libId, kind, id });

    // Each component is its own card showing its relationships — inputs on the
    // left, the component in the middle, outputs on the right (technologies and
    // streams are never mixed). Clicking opens the component's overview + editor.
    const ioCol = (head: string, items: string[], side: "in" | "out") => (
      <div className={`comp-io comp-io-${side}`}>
        <div className="comp-io-head">{head}</div>
        {items.length
          ? items.map((s) => <div className="comp-io-item" key={s} title={s}>{s}</div>)
          : <div className="comp-io-none">—</div>}
      </div>
    );
    // Distinct count of per-year override years across the given trajectories.
    const tsYears = (...maps: (Record<string, number> | undefined)[]): number => {
      const ys = new Set<string>();
      for (const m of maps) for (const k of Object.keys(m ?? {})) ys.add(k);
      return ys.size;
    };
    const tsChip = (n: number) => (n > 0 ? <div className="comp-card-ts">↻ {n}-year time-series</div> : null);
    const techCard = (t: TechnologyTemplate) => {
      const ins = t.io.filter((r) => r.role === "input").map((r) => String(r.target));
      const outs = t.io.filter((r) => r.role === "output").map((r) => String(r.target));
      return (
        <button className="comp-card" key={`t:${t.technology_id}`} onClick={() => drill("tech", t.technology_id)}>
          <div className="comp-card-row">
            {ioCol("inputs", ins, "in")}
            <div className="comp-card-mid">
              <span className="lib-tier">technology</span>
              <div className="comp-card-title">{t.technology_id}</div>
              <div className="comp-card-meta">capex {t.capex} · opex {t.opex}</div>
              {t.maccs.length > 0 && <div className="comp-card-macc">MACC · {t.maccs.join(", ")}</div>}
              {tsChip(tsYears(t.capex_by_year, t.opex_by_year))}
            </div>
            {ioCol("outputs", outs, "out")}
          </div>
        </button>
      );
    };
    const streamCard = (c: CommodityTemplate) => {
      const prod = (body?.technologies ?? []).filter((t) => t.io.some((r) => r.role === "output" && r.target === c.commodity_id)).map((t) => t.technology_id);
      const cons = (body?.technologies ?? []).filter((t) => t.io.some((r) => r.role === "input" && r.target === c.commodity_id)).map((t) => t.technology_id);
      return (
        <button className="comp-card" key={`s:${c.commodity_id}`} onClick={() => drill("stream", c.commodity_id)}>
          <div className="comp-card-row">
            {ioCol("produced by", prod, "in")}
            <div className="comp-card-mid">
              <span className="lib-tier">stream</span>
              <div className="comp-card-title">{c.commodity_id}</div>
              <div className="comp-card-meta">{c.unit ? `${c.kind} · ${c.unit}` : c.kind}</div>
              {tsChip(tsYears(c.price_by_year, c.sale_price_by_year))}
            </div>
            {ioCol("consumed by", cons, "out")}
          </div>
        </button>
      );
    };
    const maccCard = (g: MaccGroup) => {
      const meas = g.measures.map((mid) => (body?.measures ?? []).find((m) => m.measure_id === mid)).filter((m): m is MeasureTemplate => !!m);
      const usedBy = (body?.technologies ?? []).filter((t) => t.maccs.includes(g.macc_id)).map((t) => t.technology_id);
      return (
        <button className="comp-card" key={`g:${g.macc_id}`} onClick={() => drill("macc", g.macc_id)}>
          <div className="comp-card-row">
            {ioCol("measures", meas.map((m) => `${m.label || m.measure_id}${m.target ? ` → ${m.target}` : ""}`), "in")}
            <div className="comp-card-mid">
              <span className="lib-tier">MACC</span>
              <div className="comp-card-title">{g.label || g.macc_id}</div>
            </div>
            {ioCol("applied to", usedBy, "out")}
          </div>
        </button>
      );
    };
    const measureCard = (m: MeasureTemplate) => (
      <button className="comp-card" key={`m:${m.measure_id}`} onClick={() => drill("measure", m.measure_id)}>
        <div className="comp-card-row">
          <div className="comp-card-mid comp-card-mid-wide">
            <span className="lib-tier">measure</span>
            <div className="comp-card-title">{m.label || m.measure_id}</div>
            <div className="comp-card-meta">{m.target ? `abates ${m.target}` : m.type} · {m.blocks.length} block{m.blocks.length === 1 ? "" : "s"}</div>
            {tsChip(tsYears(...m.blocks.flatMap((b) => [b.capex_per_capacity_by_year, b.opex_per_capacity_by_year])))}
          </div>
        </div>
      </button>
    );
    const grid = (cards: JSX.Element[], empty: string) =>
      cards.length ? <div className="comp-grid">{cards}</div> : <p className="muted" style={{ fontSize: "0.78rem" }}>{empty}</p>;

    if (sub === "tech")
      return <BucketShell title={`${sector} · Technologies`} add={() => addTech(libId)}>{grid(b.techs.map(techCard), "No technologies in this sector.")}</BucketShell>;
    if (sub === "stream")
      return <BucketShell title={`${sector} · Streams`} add={() => addStream(libId, sector === OTHER ? null : sector)}>{grid(b.streams.map(streamCard), "No streams produced in this sector.")}</BucketShell>;
    if (sub === "indiv")
      return <BucketShell title={`${sector} · Measures`} add={() => addMeasure(libId)}>{grid(b.measures.map(measureCard), "No individual measures in this sector.")}</BucketShell>;
    if (sub === "macc")
      return <BucketShell title={`${sector} · MACCs`} add={() => addMacc(libId)}>{grid(b.maccs.map(maccCard), "No MACC bundles in this sector.")}</BucketShell>;

    // Sector group ("") → Group cards (Sector → Group → Components). Keeps
    // technologies / streams / measures separate instead of one flat list.
    if (sub === "") {
      const cards = groupCards(libId, sector, b);
      return (
        <section>
          <h2 style={{ margin: "0 0 4px" }}>{sector}</h2>
          <p className="muted" style={{ fontSize: "0.78rem", margin: "0 0 12px" }}>
            Choose a group to view and edit its components.
          </p>
          {cards.length === 0 ? (
            <p className="muted" style={{ fontSize: "0.78rem" }}>This sector is empty.</p>
          ) : (
            <div className="lib-grid">{cards}</div>
          )}
        </section>
      );
    }

    // Measures & MACC parent ("measures") → MACC + individual-measure cards.
    return (
      <section>
        <h2 style={{ margin: "0 0 4px" }}>{sector} · Measures &amp; MACC</h2>
        <p className="muted" style={{ fontSize: "0.78rem", margin: "0 0 12px" }}>
          {b.maccs.length} MACC bundle{b.maccs.length === 1 ? "" : "s"} · {b.measures.length} individual
          measure{b.measures.length === 1 ? "" : "s"}.
        </p>
        {grid([...b.maccs.map(maccCard), ...b.measures.map(measureCard)], "No measures in this sector.")}
      </section>
    );
  }

  function renderLanding() {
    const tier = (sc: LibScope): string => (sc === "session" ? "project" : sc);
    const open = (l: LibrarySummary) => {
      const key = keyOf(l);
      setExpanded((p) => new Set(p).add(`lib:${key}`));
      void loadLib(key);
      if (mode === "project") setActiveProjectId?.(l.id);
      setSel({ libId: key, kind: "library" });
    };
    // Library mode lands on the base catalogue; project mode on this session's projects.
    const shown = mode === "project" ? sessionProjects : libs.filter((l) => l.scope === "base");
    return (
      <section className="lib-landing">
        <div className="lib-landing-head">
          <div>
            <h2 className="lib-landing-title">{mode === "project" ? "Your projects" : "All libraries"}</h2>
            <p className="muted lib-landing-sub">
              {mode === "project"
                ? "A project is your own working set — start one, then design components from scratch or copy them in from a library."
                : "A library is a catalogue of reusable building blocks — technologies, streams & abatement measures — organised by sector. Open one to author its contents."}
            </p>
          </div>
          <button className="lib-new" onClick={mode === "project" ? newProject : newLibrary}>
            {mode === "project" ? "+ New project" : "+ New library"}
          </button>
        </div>
        {shown.length === 0 ? (
          <p className="muted">
            {mode === "project" ? (
              <>No projects yet — click <b>New project</b> to start.</>
            ) : (
              <>No libraries yet — click <b>New library</b> to start.</>
            )}
          </p>
        ) : (
          <div className="lib-grid">
            {shown.map((l) => (
              <button className="lib-card-v2" key={keyOf(l)} onClick={() => open(l)}>
                <div className="lib-card-top">
                  <span className="lib-card-name"><span className="lib-dot" /> {l.label || l.id}</span>
                  <span className="lib-tier">{tier(l.scope)}</span>
                </div>
                <div className="lib-card-sub muted">
                  {l.scope === "session" ? "this project's set" : "shared building blocks"}
                </div>
                <div className="lib-card-stats">
                  <div><b>{l.technologies}</b><span className="muted">tech</span></div>
                  <div><b>{l.commodities}</b><span className="muted">streams</span></div>
                  <div><b>{l.measures}</b><span className="muted">measures</span></div>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>
    );
  }

  // A clickable catalogue card (same chrome as the top-level library cards),
  // reused for sector and component drill-downs.
  function infoCard(o: {
    key: string;
    title: string;
    badge?: string;
    sub?: string;
    stats?: { n: string | number; label: string }[];
    onClick: () => void;
  }) {
    return (
      <button className="lib-card-v2" key={o.key} onClick={o.onClick}>
        <div className="lib-card-top">
          <span className="lib-card-name"><span className="lib-dot" /> {o.title}</span>
          {o.badge && <span className="lib-tier">{o.badge}</span>}
        </div>
        {o.sub && <div className="lib-card-sub muted">{o.sub}</div>}
        {o.stats && o.stats.length > 0 && (
          <div className="lib-card-stats">
            {o.stats.map((st, i) => (
              <div key={i}><b>{st.n}</b><span className="muted">{st.label}</span></div>
            ))}
          </div>
        )}
      </button>
    );
  }

  // Group cards (Technologies / Streams / MACCs / Measures) for one sector —
  // the middle level of Sector → Group → Components. Clicking opens the group's
  // editable table.
  function groupCards(libId: string, sector: string, b: Bucket) {
    const groups = [
      { sub: "tech", label: "Technologies", desc: "Process recipes — inputs, outputs, costs & impacts", n: b.techs.length },
      { sub: "stream", label: "Streams", desc: "Commodities produced here, and how they connect", n: b.streams.length },
      { sub: "measures", label: "Measures & MACC", desc: "Abatement levers and their cost curves", n: b.maccs.length + b.measures.length },
    ].filter((g) => g.n > 0);
    return groups.map((g) =>
      infoCard({
        key: g.sub,
        title: g.label,
        sub: g.desc,
        stats: [{ n: g.n, label: "components" }],
        onClick: () => {
          setExpanded((p) => new Set(p).add(`cat:${libId}:${sector}`).add(`cat:${libId}:${sector}/${g.sub}`));
          setSel({ libId, kind: "cat", id: `${sector}/${g.sub}` });
        },
      }),
    );
  }

  function renderDetail() {
    if (!sel) return renderLanding();
    if (!body) return <p className="muted">Loading…</p>;
    if (sel.kind === "library") {
      const l = libs.find((x) => keyOf(x) === sel.libId);
      // Project mode: the catalogue of components (from any OTHER library) the
      // user can hard-copy into this project, narrowed to the chosen kind.
      const copyEntries =
        mode === "project"
          ? catalog.filter(
              (e) => e.kind === copyKind && !(e.scope === "session" && e.library_id === activeProjectId),
            )
          : [];
      const copyOptions = copyEntries.map((e, i) => ({
        value: String(i),
        label: `${e.label} · ${e.library_id}${e.scope === "session" ? " · project" : ""}`,
      }));
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
          </div>
          {mode === "project" && (
            <div style={{ marginBottom: 12, padding: "8px 10px", border: "1px solid var(--border)", borderRadius: "var(--radius-button)" }}>
              <div className="muted" style={{ fontSize: "0.74rem", marginBottom: 6 }}>
                …or copy an existing one in — a hard copy, so its values become project-local.
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ minWidth: 120 }}>
                  <SearchSelect
                    value={copyKind}
                    onChange={(v) => v && setCopyKind(v as ComponentCatalogKind)}
                    options={[
                      { value: "technology", label: "Technology" },
                      { value: "stream", label: "Stream" },
                      { value: "measure", label: "Measure" },
                      { value: "macc", label: "MACC" },
                    ]}
                  />
                </span>
                <span style={{ minWidth: 240, flex: 1 }}>
                  <SearchSelect
                    value=""
                    onChange={(v) => {
                      const e = copyEntries[Number(v)];
                      if (e) void copyEntryIntoActive(e);
                    }}
                    options={copyOptions}
                    placeholder={copyOptions.length ? `copy a ${copyKind}…` : `no ${copyKind}s to copy`}
                  />
                </span>
              </div>
            </div>
          )}
          <p className="muted" style={{ fontSize: "0.78rem" }}>
            {l?.technologies ?? 0} technologies · {l?.commodities ?? 0} streams · {l?.measures ?? 0} measures · {l?.maccs ?? 0} MACCs.
            {" "}A technology gets its own input/output streams; measures are reusable and bundled into MACCs; a technology links the MACCs that apply to it.
          </p>
          {buckets && buckets.order.length > 0 && (
            <div className="lib-grid" style={{ marginTop: 8 }}>
              {buckets.order.length > 1
                ? buckets.order.map((sec) => {
                    const b = buckets.buckets.get(sec)!;
                    return infoCard({
                      key: sec,
                      title: sec,
                      sub: "sector",
                      stats: [
                        { n: b.techs.length, label: "tech" },
                        { n: b.streams.length, label: "streams" },
                        { n: b.measures.length + b.maccs.length, label: "measures" },
                      ],
                      onClick: () => {
                        setExpanded((p) => new Set(p).add(`cat:${sel.libId}:${sec}`));
                        setSel({ libId: sel.libId, kind: "cat", id: sec });
                      },
                    });
                  })
                : groupCards(sel.libId, buckets.order[0], buckets.buckets.get(buckets.order[0])!)}
            </div>
          )}
        </section>
      );
    }
    if (sel.kind === "cat") return renderCat(sel.id ?? OTHER);
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
            unitOptions={unitOptions}
            streamUnitOf={streamUnit}
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
    // macc
    const g = body.maccs.find((x) => x.macc_id === sel.id);
    if (!g) return null;
    return (
      <MaccEditor
        value={g}
        measures={body.measures.map((m) => ({ id: m.measure_id, label: m.label || m.measure_id }))}
        allMeasures={body.measures}
        onChange={(v) => editLib(sel.libId, (l) => ({ ...l, maccs: l.maccs.map((x) => (x.macc_id === sel.id ? v : x)) }))}
        onRename={(id) => setSel({ libId: sel.libId, kind: "macc", id })}
      />
    );
  }

  // ── Right-rail notes (editable references per entity / sector) ───────────────
  function notesFor(): { label: string; value: string; set: (v: string) => void } | null {
    if (!sel || !body) return null;
    if (sel.kind === "tech") {
      const t = body.technologies.find((x) => x.technology_id === sel.id);
      return t == null ? null : {
        label: `Technology · ${t.technology_id}`,
        value: t.notes ?? "",
        set: (v) => editLib(sel.libId, (l) => ({ ...l, technologies: l.technologies.map((x) => (x.technology_id === sel.id ? { ...x, notes: v } : x)) })),
      };
    }
    if (sel.kind === "stream") {
      const c = body.commodities.find((x) => x.commodity_id === sel.id);
      return c == null ? null : {
        label: `Stream · ${c.commodity_id}`,
        value: c.notes ?? "",
        set: (v) => editLib(sel.libId, (l) => ({ ...l, commodities: l.commodities.map((x) => (x.commodity_id === sel.id ? { ...x, notes: v } : x)) })),
      };
    }
    if (sel.kind === "measure") {
      const m = body.measures.find((x) => x.measure_id === sel.id);
      return m == null ? null : {
        label: `Measure · ${m.measure_id}`,
        value: m.notes ?? "",
        set: (v) => editLib(sel.libId, (l) => ({ ...l, measures: l.measures.map((x) => (x.measure_id === sel.id ? { ...x, notes: v } : x)) })),
      };
    }
    if (sel.kind === "macc") {
      const g = body.maccs.find((x) => x.macc_id === sel.id);
      return g == null ? null : {
        label: `MACC · ${g.macc_id}`,
        value: g.notes ?? "",
        set: (v) => editLib(sel.libId, (l) => ({ ...l, maccs: l.maccs.map((x) => (x.macc_id === sel.id ? { ...x, notes: v } : x)) })),
      };
    }
    if (sel.kind === "cat" && !(sel.id ?? "").includes("/")) {
      const sector = sel.id ?? OTHER; // a sector group, not a bucket
      return {
        label: `Sector · ${sector}`,
        value: (body.notes_by_sector ?? {})[sector] ?? "",
        set: (v) => editLib(sel.libId, (l) => {
          const nbs = { ...(l.notes_by_sector ?? {}) };
          if (v.trim() === "") delete nbs[sector];
          else nbs[sector] = v;
          return { ...l, notes_by_sector: nbs };
        }),
      };
    }
    return null;
  }

  // ── Right-rail per-year time-series table for the selected single component ──
  function tsRail() {
    if (!sel || !body) return null;
    if (sel.kind === "tech") {
      const t = body.technologies.find((x) => x.technology_id === sel.id);
      return t == null ? null : <TimeSeriesRail kind="tech" value={t} onChange={(v) => editLib(sel.libId, (l) => ({ ...l, technologies: l.technologies.map((x) => (x.technology_id === sel.id ? v : x)) }))} />;
    }
    if (sel.kind === "stream") {
      const c = body.commodities.find((x) => x.commodity_id === sel.id);
      return c == null ? null : <TimeSeriesRail kind="stream" value={c} onChange={(v) => editLib(sel.libId, (l) => ({ ...l, commodities: l.commodities.map((x) => (x.commodity_id === sel.id ? v : x)) }))} />;
    }
    if (sel.kind === "measure") {
      const m = body.measures.find((x) => x.measure_id === sel.id);
      return m == null ? null : <TimeSeriesRail kind="measure" value={m} onChange={(v) => editLib(sel.libId, (l) => ({ ...l, measures: l.measures.map((x) => (x.measure_id === sel.id ? v : x)) }))} />;
    }
    return null;
  }

  const notes = notesFor();
  const rail = tsRail();

  // Library mode shows the shared base catalogue; project mode shows ONLY the
  // active project's own components (base is reached via the copy picker).
  const railNodes =
    mode === "project"
      ? treeNodes.filter((nd) => activeLibId != null && parseId(nd.id).libId === activeLibId)
      : treeNodes.filter((nd) => parseId(nd.id).libId.startsWith("base/"));
  const libTree = (nodes: TreeNode[], emptyHint: string) => (
    <TreeExplorer
      nodes={nodes}
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
      onSelect={(id) => {
        const next = parseId(id);
        if (!openLibs.has(next.libId)) void loadLib(next.libId);
        setSel(next);
      }}
      actionsFor={actionsFor}
      onContextAction={onContextAction}
      onMove={() => undefined}
      emptyHint={emptyHint}
    />
  );

  return (
    <div className="view-full builder" style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {error && <div className="error" style={{ padding: "4px 12px" }} onClick={() => setError(null)}>{error} <span className="muted">(dismiss)</span></div>}
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <aside style={{ width: 280, borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", flexShrink: 0, minHeight: 0 }}>
          {mode === "project" ? (
            <>
              <div className="rail-head-row" style={{ padding: "6px 10px" }}>
                <span className="rail-head">Project</span>
                <button className="rail-add" title="new project" onClick={newProject}>＋</button>
              </div>
              <div style={{ padding: "0 10px 6px" }}>
                <SearchSelect
                  value={activeProjectId ?? ""}
                  onChange={(v) => switchProject(v)}
                  options={sessionProjects.map((l) => ({ value: l.id, label: l.label || l.id }))}
                  placeholder={sessionProjects.length ? "select a project…" : "no projects yet"}
                />
              </div>
              <div style={{ flex: 1, minHeight: 60, overflow: "auto" }}>
                {activeLibId
                  ? libTree(railNodes, "Empty project — add or copy components from the main panel.")
                  : <div className="rail-empty" style={{ padding: 10 }}>Create a project with ＋, then add components.</div>}
              </div>
            </>
          ) : (
            <>
              <div className="rail-head-row" style={{ padding: "6px 10px" }}>
                <button
                  className="rail-head"
                  style={{ background: "none", border: "none", padding: 0, font: "inherit", cursor: "pointer", textAlign: "left" }}
                  title="Show all libraries"
                  onClick={() => setSel(null)}
                >
                  Libraries
                </button>
                <button className="rail-add" title="new library" onClick={newLibrary}>＋</button>
              </div>
              <div style={{ flex: 1, minHeight: 60, overflow: "auto" }}>
                {libTree(railNodes, "No base libraries — ＋ to add one.")}
              </div>
            </>
          )}
          <div className="muted" style={{ fontSize: "0.7rem", padding: "8px 10px", borderTop: "1px solid var(--border)" }}>Right-click for actions</div>
        </aside>
        <main style={{ flex: 1, overflow: "auto", padding: "16px 20px", minWidth: 0, display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
            <div className="eyebrow">{mode === "project" ? "project workbench" : "component library"}</div>
            <span className="muted" style={{ fontSize: "0.78rem" }}>{status}</span>
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>{renderDetail()}</div>
          {/* Notes & references — at the bottom of the main area. */}
          {notes && (
            <div style={{ borderTop: "1px solid var(--border)", marginTop: 20, paddingTop: 12 }}>
              <div className="eyebrow" style={{ marginBottom: 6 }}>
                notes &amp; references <span className="muted" style={{ textTransform: "none", letterSpacing: 0 }}>· {notes.label}</span>
              </div>
              <textarea
                value={notes.value}
                onChange={(e) => notes.set(e.target.value)}
                placeholder="Sources, assumptions, caveats… (free text — the optimiser ignores it)"
                style={{ ...inp, width: "100%", minHeight: 80, resize: "vertical", lineHeight: 1.45 }}
              />
            </div>
          )}
        </main>
        {/* RIGHT rail (resizable): per-year time-series table for the selected component. */}
        {rail && (
          <>
            <Resizer width={rightW} setWidth={setRightW} side="right" />
            <aside style={{ width: rightW, overflow: "auto", borderLeft: "1px solid var(--border)", flexShrink: 0, padding: "14px 14px" }}>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                time series <span className="muted" style={{ textTransform: "none", letterSpacing: 0 }}>· per-year overrides; empty = latest value</span>
              </div>
              {rail}
            </aside>
          </>
        )}
      </div>
      {dialogNode}
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
