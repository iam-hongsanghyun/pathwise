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
import { type Column, DataTable } from "../features/controls/DataTable";
import { useDialogs } from "../features/controls/Dialog";
import { TreeExplorer } from "../features/tree/TreeExplorer";
import type { TreeAction, TreeNode } from "../features/tree/types";
import {
  type CommodityTemplate,
  type ComponentLibrary,
  deleteComponentLibrary,
  deleteSessionComponentLibrary,
  emptyLibrary,
  getComponentLibrary,
  getSessionComponentLibrary,
  type LibrarySummary,
  type LibScope,
  listAllComponentLibraries,
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

// Parse a table cell back to a number: "" → 0 (pnum), "" → null (pnull/pint).
const pnum = (raw: string): number => (raw.trim() === "" ? 0 : Number(raw) || 0);
const pnull = (raw: string): number | null => (raw.trim() === "" ? null : Number(raw) || 0);
const pint = (raw: string): number | null => (raw.trim() === "" ? null : Math.round(Number(raw) || 0));

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

export function ComponentTabView({ sessionId }: { sessionId: string | null }) {
  const { prompt, confirm, node: dialogNode } = useDialogs();
  const [libs, setLibs] = useState<LibrarySummary[]>([]);
  const [openLibs, setOpenLibs] = useState<Map<string, ComponentLibrary>>(new Map());
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [sel, setSel] = useState<Sel | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [railMember, setRailMember] = useState<string>(""); // active member in a bucket's time-series rail
  const [unitOptions, setUnitOptions] = useState<string[]>([]); // allowed units for the IO unit picker
  const saved = useRef<Map<string, string>>(new Map());

  // Base (shared) + this session's own libraries (an imported scenario's set).
  useEffect(() => {
    listAllComponentLibraries(sessionId).then(setLibs).catch((e) => setError(String(e)));
  }, [sessionId]);

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
      try {
        for (const libId of dirty) {
          const body = openLibs.get(libId);
          if (!body) continue;
          const summary = await saveLib(libId, body, sessionId);
          saved.current.set(libId, JSON.stringify(body));
          setLibs((prev) => prev.map((x) => (keyOf(x) === libId ? summary : x)));
        }
        setDirty(new Set());
        setStatus("saved");
      } catch (e) {
        setStatus("save failed");
        setError(String(e));
      }
    }, 600);
    return () => clearTimeout(t);
  }, [dirty, openLibs, sessionId]);

  // Reset the bucket time-series rail's active member when the selection changes.
  useEffect(() => { setRailMember(""); }, [sel?.libId, sel?.kind, sel?.id]);

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
      const tag = l.scope === "session" ? " · scenario" : " · base";
      out.push({ id: `lib:${lk}`, parentId: null, kind: "library", label: `${l.label || l.id}${tag}`, hasChildren: true, draggable: false, droppable: false });
      const body = openLibs.get(lk);
      if (!body) continue;

      const { order, buckets } = libraryBuckets(body);
      for (const s of order) {
        const b = buckets.get(s)!;
        const secId = `cat:${lk}:${s}`;
        node(secId, `lib:${lk}`, s, "group", true);
        node(`cat:${lk}:${s}/tech`, secId, "Technology", "group", b.techs.length > 0);
        for (const t of b.techs) node(`t:${lk}:${t.technology_id}`, `cat:${lk}:${s}/tech`, t.technology_id, "leaf", false);
        node(`cat:${lk}:${s}/stream`, secId, "Stream", "group", b.streams.length > 0);
        for (const c of b.streams) node(`s:${lk}:${c.commodity_id}`, `cat:${lk}:${s}/stream`, c.commodity_id, "leaf", false);
        node(`cat:${lk}:${s}/measures`, secId, "Measures & MACC", "group", b.maccs.length + b.measures.length > 0);
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

    if (sub === "tech") {
      const cols: Column<TechnologyTemplate>[] = [
        { key: "id", label: "id", type: "readonly", get: (t) => t.technology_id, onClick: (t) => drill("tech", t.technology_id) },
        { key: "lifespan", label: "lifespan", metaKey: "lifespan", type: "number", get: (t) => t.lifespan, set: (t, v) => ({ ...t, lifespan: pnum(v) }) },
        { key: "capex", label: "capex /cap", metaKey: "capex", type: "number", get: (t) => t.capex, set: (t, v) => ({ ...t, capex: pnum(v) }) },
        { key: "opex", label: "opex /unit", metaKey: "opex", type: "number", get: (t) => t.opex, set: (t, v) => ({ ...t, opex: pnum(v) }) },
        { key: "from", label: "avail. from", metaKey: "introduction_year", type: "number", get: (t) => t.introduction_year ?? "", set: (t, v) => ({ ...t, introduction_year: pint(v) }) },
        { key: "to", label: "avail. to", metaKey: "phase_out_year", type: "number", get: (t) => t.phase_out_year ?? "", set: (t, v) => ({ ...t, phase_out_year: pint(v) }) },
      ];
      return (
        <BucketShell title={`${sector} · Technologies`} add={() => addTech(libId)}>
          <DataTable rows={b.techs} columns={cols} rowKey={(t) => t.technology_id} empty="No technologies in this sector."
            onChange={(rows) => editLib(libId, (l) => { const by = new Map(rows.map((r) => [r.technology_id, r])); return { ...l, technologies: l.technologies.map((t) => by.get(t.technology_id) ?? t) }; })} />
        </BucketShell>
      );
    }
    if (sub === "stream") {
      const cols: Column<CommodityTemplate>[] = [
        { key: "id", label: "id", type: "readonly", get: (c) => c.commodity_id, onClick: (c) => drill("stream", c.commodity_id) },
        { key: "kind", label: "kind", metaKey: "kind", type: "enum", options: ["energy", "material", "indirect", "product", "byproduct"], get: (c) => c.kind, set: (c, v) => ({ ...c, kind: v as CommodityTemplate["kind"] }) },
        { key: "unit", label: "unit", metaKey: "unit", type: "text", get: (c) => c.unit, set: (c, v) => ({ ...c, unit: v }) },
        { key: "sector", label: "sector", metaKey: "sector", type: "text", get: (c) => c.sector ?? "", set: (c, v) => ({ ...c, sector: v.trim() === "" ? null : v }) },
        { key: "price", label: "price", metaKey: "price", type: "number", get: (c) => c.price ?? "", set: (c, v) => ({ ...c, price: pnull(v) }) },
        { key: "sale", label: "sale price", metaKey: "sale_price", type: "number", get: (c) => c.sale_price ?? "", set: (c, v) => ({ ...c, sale_price: pnull(v) }) },
      ];
      return (
        <BucketShell title={`${sector} · Streams`} add={() => addStream(libId, sector === OTHER ? null : sector)}>
          <DataTable rows={b.streams} columns={cols} rowKey={(c) => c.commodity_id} empty="No streams produced in this sector."
            onChange={(rows) => editLib(libId, (l) => { const by = new Map(rows.map((r) => [r.commodity_id, r])); return { ...l, commodities: l.commodities.map((c) => by.get(c.commodity_id) ?? c) }; })} />
        </BucketShell>
      );
    }
    if (sub === "indiv") {
      const cols: Column<MeasureTemplate>[] = [
        { key: "id", label: "id", type: "readonly", get: (m) => m.measure_id, onClick: (m) => drill("measure", m.measure_id) },
        { key: "label", label: "label", metaKey: "label", type: "text", get: (m) => m.label, set: (m, v) => ({ ...m, label: v }) },
        { key: "type", label: "type", metaKey: "measure_type", type: "enum", options: ["energy_efficiency", "emission_reduction", "environmental"], get: (m) => m.type, set: (m, v) => ({ ...m, type: v as MeasureTemplate["type"] }) },
        { key: "target", label: "target", metaKey: "target", type: "text", get: (m) => m.target, set: (m, v) => ({ ...m, target: v }) },
        { key: "lifetime", label: "lifetime", metaKey: "lifetime", type: "number", get: (m) => m.lifetime, set: (m, v) => ({ ...m, lifetime: pnum(v) }) },
        { key: "blocks", label: "# blocks", type: "readonly", get: (m) => m.blocks.length },
      ];
      return (
        <BucketShell title={`${sector} · Measures`} add={() => addMeasure(libId)}>
          <DataTable rows={b.measures} columns={cols} rowKey={(m) => m.measure_id} empty="No individual measures in this sector."
            onChange={(rows) => editLib(libId, (l) => { const by = new Map(rows.map((r) => [r.measure_id, r])); return { ...l, measures: l.measures.map((m) => by.get(m.measure_id) ?? m) }; })} />
        </BucketShell>
      );
    }
    if (sub === "macc") {
      const cols: Column<MaccGroup>[] = [
        { key: "id", label: "id", type: "readonly", get: (g) => g.macc_id, onClick: (g) => drill("macc", g.macc_id) },
        { key: "label", label: "label", metaKey: "label", type: "text", get: (g) => g.label, set: (g, v) => ({ ...g, label: v }) },
        { key: "measures", label: "# measures", type: "readonly", get: (g) => g.measures.length },
      ];
      return (
        <BucketShell title={`${sector} · MACCs`} add={() => addMacc(libId)}>
          <DataTable rows={b.maccs} columns={cols} rowKey={(g) => g.macc_id} empty="No MACC bundles in this sector."
            onChange={(rows) => editLib(libId, (l) => { const by = new Map(rows.map((r) => [r.macc_id, r])); return { ...l, maccs: l.maccs.map((g) => by.get(g.macc_id) ?? g) }; })} />
        </BucketShell>
      );
    }

    // Sector group ("") or the Measures & MACC parent ("measures") → an
    // aggregated, read-only roll-up of the members (click an id to drill in).
    const noop = () => undefined;
    const roll = <T,>(title: string, rows: T[], rowKey: (r: T) => string, cols: Column<T>[]) =>
      rows.length === 0 ? null : (
        <div style={{ marginBottom: 16 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: "0.85rem" }}>{title} <span className="muted">({rows.length})</span></h3>
          <DataTable rows={rows} columns={cols} rowKey={rowKey} onChange={noop} />
        </div>
      );
    const onlyMeasures = sub === "measures";
    return (
      <section>
        <h2 style={{ margin: "0 0 4px" }}>{sector}{onlyMeasures ? " · Measures & MACC" : ""}</h2>
        <p className="muted" style={{ fontSize: "0.76rem", margin: "0 0 12px" }}>
          {onlyMeasures
            ? `${b.measures.length} measures · ${b.maccs.length} MACCs in this sector.`
            : `${b.techs.length} technologies · ${b.streams.length} streams · ${b.measures.length} measures · ${b.maccs.length} MACCs in this sector.`}
          {" "}Open a bucket on the left to edit a column at a time, or click an id below.
        </p>
        {!onlyMeasures && roll<TechnologyTemplate>("Technologies", b.techs, (t) => t.technology_id, [
          { key: "id", label: "id", type: "readonly", get: (t) => t.technology_id, onClick: (t) => drill("tech", t.technology_id) },
          { key: "capex", label: "capex /cap", metaKey: "capex", type: "readonly", get: (t) => t.capex },
          { key: "opex", label: "opex /unit", metaKey: "opex", type: "readonly", get: (t) => t.opex },
        ])}
        {!onlyMeasures && roll<CommodityTemplate>("Streams (outputs)", b.streams, (c) => c.commodity_id, [
          { key: "id", label: "id", type: "readonly", get: (c) => c.commodity_id, onClick: (c) => drill("stream", c.commodity_id) },
          { key: "kind", label: "kind", metaKey: "kind", type: "readonly", get: (c) => c.kind },
          { key: "price", label: "price", metaKey: "price", type: "readonly", get: (c) => c.price ?? "—" },
        ])}
        {roll<MeasureTemplate>("Measures", b.measures, (m) => m.measure_id, [
          { key: "id", label: "id", type: "readonly", get: (m) => m.label || m.measure_id, onClick: (m) => drill("measure", m.measure_id) },
          { key: "type", label: "type", metaKey: "measure_type", type: "readonly", get: (m) => m.type },
          { key: "target", label: "target", metaKey: "target", type: "readonly", get: (m) => m.target },
        ])}
        {roll<MaccGroup>("MACCs", b.maccs, (g) => g.macc_id, [
          { key: "id", label: "id", type: "readonly", get: (g) => g.label || g.macc_id, onClick: (g) => drill("macc", g.macc_id) },
          { key: "measures", label: "# measures", type: "readonly", get: (g) => g.measures.length },
        ])}
        {b.techs.length + b.streams.length + b.measures.length + b.maccs.length === 0 && (
          <p className="muted" style={{ fontSize: "0.78rem" }}>This sector is empty.</p>
        )}
      </section>
    );
  }

  function renderDetail() {
    if (!sel || !body) return <p className="muted">Pick or create a library on the left to start building.</p>;
    if (sel.kind === "library") {
      const l = libs.find((x) => keyOf(x) === sel.libId);
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
          <p className="muted" style={{ fontSize: "0.78rem" }}>
            {l?.technologies ?? 0} technologies · {l?.commodities ?? 0} streams · {l?.measures ?? 0} measures · {l?.maccs ?? 0} MACCs.
            {" "}A technology gets its own input/output streams; measures are reusable and bundled into MACCs; a technology links the MACCs that apply to it.
          </p>
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

  // ── Bottom-rail per-year cost trajectories for a single selected item ────────
  function bottomRail() {
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
    // Bucket selection → pick a member (per-series toggle), edit its trajectory.
    if (sel.kind === "cat" && buckets) {
      const raw = sel.id ?? "";
      const sector = raw.split("/")[0] || OTHER;
      const sub = raw.includes("/") ? raw.split("/")[1] : "";
      const b = buckets.buckets.get(sector);
      if (!b) return null;
      const libId = sel.libId;
      const toggle = (ids: string[], active: string) => (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
          <span className="muted" style={{ fontSize: "0.72rem", alignSelf: "center" }}>edit by-year for:</span>
          {ids.map((id) => (
            <button key={id} className="ghost" style={active === id ? { borderColor: "var(--brand)", color: "var(--brand)" } : undefined} onClick={() => setRailMember(id)}>{id}</button>
          ))}
        </div>
      );
      if (sub === "tech" && b.techs.length) {
        const t = b.techs.find((x) => x.technology_id === railMember) ?? b.techs[0];
        return (<>{toggle(b.techs.map((x) => x.technology_id), t.technology_id)}<TimeSeriesRail kind="tech" value={t} onChange={(v) => editLib(libId, (l) => ({ ...l, technologies: l.technologies.map((x) => (x.technology_id === t.technology_id ? v : x)) }))} /></>);
      }
      if (sub === "stream" && b.streams.length) {
        const c = b.streams.find((x) => x.commodity_id === railMember) ?? b.streams[0];
        return (<>{toggle(b.streams.map((x) => x.commodity_id), c.commodity_id)}<TimeSeriesRail kind="stream" value={c} onChange={(v) => editLib(libId, (l) => ({ ...l, commodities: l.commodities.map((x) => (x.commodity_id === c.commodity_id ? v : x)) }))} /></>);
      }
      if (sub === "indiv" && b.measures.length) {
        const m = b.measures.find((x) => x.measure_id === railMember) ?? b.measures[0];
        return (<>{toggle(b.measures.map((x) => x.measure_id), m.measure_id)}<TimeSeriesRail kind="measure" value={m} onChange={(v) => editLib(libId, (l) => ({ ...l, measures: l.measures.map((x) => (x.measure_id === m.measure_id ? v : x)) }))} /></>);
      }
      return null;
    }
    return null;
  }

  const notes = notesFor();
  const rail = bottomRail();

  return (
    <div className="view-full builder" style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {error && <div className="error" style={{ padding: "4px 12px" }} onClick={() => setError(null)}>{error} <span className="muted">(dismiss)</span></div>}
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
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
        {/* RIGHT rail: editable notes / references for the selected item or sector. */}
        <aside style={{ width: 264, overflow: "auto", borderLeft: "1px solid var(--border)", flexShrink: 0, padding: "14px 14px" }}>
          <div className="eyebrow" style={{ marginBottom: 8 }}>notes &amp; references</div>
          {notes ? (
            <>
              <div className="muted" style={{ fontSize: "0.74rem", marginBottom: 6 }}>{notes.label}</div>
              <textarea
                value={notes.value}
                onChange={(e) => notes.set(e.target.value)}
                placeholder="Sources, assumptions, caveats… (free text — the optimiser ignores it)"
                style={{ ...inp, width: "100%", minHeight: 180, resize: "vertical", lineHeight: 1.45 }}
              />
            </>
          ) : (
            <p className="muted" style={{ fontSize: "0.78rem" }}>Select a technology, stream, measure, MACC, or a sector to add notes.</p>
          )}
        </aside>
      </div>
      {/* BOTTOM rail: per-year cost/price trajectories for the selected item. */}
      {rail && (
        <div style={{ flexShrink: 0, borderTop: "1px solid var(--border)", maxHeight: 240, overflow: "auto", padding: "10px 16px", background: "var(--surface)" }}>
          <div className="eyebrow" style={{ marginBottom: 6 }}>time series <span className="muted" style={{ textTransform: "none", letterSpacing: 0 }}>· per-year overrides of the values above</span></div>
          {rail}
        </div>
      )}
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
