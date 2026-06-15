// Component builder — author reusable components in many named libraries.
//
// A focused, per-component editor (unlike the old all-in-one Model view): pick or
// create a library on the left, then build technologies + their input/output
// streams, package them as machines (facilities) with their MACC measures, and
// compose groups. Components copy/move between libraries. Everything persists
// server-side (PUT), debounced — the Value-Chain builder drops fresh copies.

import { useEffect, useMemo, useRef, useState } from "react";
import { SearchableSelect } from "../features/controls/SearchableSelect";
import {
  type CommodityTemplate,
  type ComponentLibrary,
  deleteComponentLibrary,
  emptyLibrary,
  getComponentLibrary,
  type GroupComponent,
  type IoRow,
  type LibrarySummary,
  listComponentLibraries,
  type MachineComponent,
  type MeasureTemplate,
  saveComponentLibrary,
  type TechnologyTemplate,
} from "../lib/api/components";

type Kind = "commodity" | "technology" | "machine" | "group";
interface Sel {
  kind: Kind;
  id: string;
}

const num = (v: string): number => (v.trim() === "" ? 0 : Number(v) || 0);
const uniqueId = (base: string, taken: Set<string>): string => {
  if (!taken.has(base)) return base;
  let i = 2;
  while (taken.has(`${base}_${i}`)) i++;
  return `${base}_${i}`;
};

export function ComponentBuilderView() {
  const [libs, setLibs] = useState<LibrarySummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [lib, setLib] = useState<ComponentLibrary | null>(null);
  const [sel, setSel] = useState<Sel | null>(null);
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const saved = useRef<ComponentLibrary | null>(null);

  useEffect(() => {
    listComponentLibraries()
      .then((l) => {
        setLibs(l);
        if (l.length) void openLib(l[0].id);
      })
      .catch((e) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openLib(id: string) {
    try {
      const l = await getComponentLibrary(id);
      setActiveId(id);
      setLib(l);
      saved.current = l;
      setSel(null);
      setStatus("idle");
    } catch (e) {
      setError(String(e));
    }
  }

  // Debounced save of the active library.
  useEffect(() => {
    if (!lib || !activeId || lib === saved.current) return;
    setStatus("saving");
    const t = setTimeout(async () => {
      try {
        const s = await saveComponentLibrary(activeId, lib);
        saved.current = lib;
        setStatus("saved");
        setLibs((prev) => prev.map((x) => (x.id === s.id ? s : x)));
      } catch (e) {
        setStatus("error");
        setError(String(e));
      }
    }, 600);
    return () => clearTimeout(t);
  }, [lib, activeId]);

  const commit = (next: ComponentLibrary) => setLib(next);

  // ── Library-level actions ───────────────────────────────────────────────────
  async function newLibrary() {
    const id = window.prompt("New library id (letters, digits, -_.):", "")?.trim();
    if (!id) return;
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(id)) {
      setError(`invalid library id '${id}'`);
      return;
    }
    try {
      await saveComponentLibrary(id, emptyLibrary(id));
      setLibs(await listComponentLibraries());
      await openLib(id);
    } catch (e) {
      setError(String(e));
    }
  }
  async function removeLibrary(id: string) {
    if (!window.confirm(`Delete library '${id}'? This cannot be undone.`)) return;
    try {
      await deleteComponentLibrary(id);
      const remaining = await listComponentLibraries();
      setLibs(remaining);
      if (activeId === id) {
        setLib(null);
        setActiveId(null);
        if (remaining.length) await openLib(remaining[0].id);
      }
    } catch (e) {
      setError(String(e));
    }
  }

  // ── Add components ──────────────────────────────────────────────────────────
  function addCommodity() {
    if (!lib) return;
    const id = uniqueId("stream", new Set(lib.commodities.map((c) => c.commodity_id)));
    const row: CommodityTemplate = { commodity_id: id, kind: "material", unit: "unit" };
    commit({ ...lib, commodities: [...lib.commodities, row] });
    setSel({ kind: "commodity", id });
  }
  function addTechnology() {
    if (!lib) return;
    const id = uniqueId("Technology", new Set(lib.technologies.map((t) => t.technology_id)));
    const row: TechnologyTemplate = { technology_id: id, lifespan: 20, capex: 0, opex: 0, io: [] };
    commit({ ...lib, technologies: [...lib.technologies, row] });
    setSel({ kind: "technology", id });
  }
  function addMachine() {
    if (!lib) return;
    const id = uniqueId("machine", new Set([...lib.machines.map((m) => m.name), ...lib.groups.map((g) => g.name)]));
    const row: MachineComponent = {
      name: id,
      label: "",
      technology: lib.technologies[0]?.technology_id ?? "",
      capacity: 1000,
      measures: [],
    };
    commit({ ...lib, machines: [...lib.machines, row] });
    setSel({ kind: "machine", id });
  }
  function addGroup() {
    if (!lib) return;
    const id = uniqueId("group", new Set([...lib.machines.map((m) => m.name), ...lib.groups.map((g) => g.name)]));
    const row: GroupComponent = { name: id, label: "", level: "facility", children: [], connections: [] };
    commit({ ...lib, groups: [...lib.groups, row] });
    setSel({ kind: "group", id });
  }

  // ── Per-component delete / copy / move ──────────────────────────────────────
  function deleteSelected() {
    if (!lib || !sel) return;
    const next = { ...lib };
    if (sel.kind === "commodity") next.commodities = lib.commodities.filter((c) => c.commodity_id !== sel.id);
    if (sel.kind === "technology") next.technologies = lib.technologies.filter((t) => t.technology_id !== sel.id);
    if (sel.kind === "machine") next.machines = lib.machines.filter((m) => m.name !== sel.id);
    if (sel.kind === "group") next.groups = lib.groups.filter((g) => g.name !== sel.id);
    commit(next);
    setSel(null);
  }

  /** Copy (or move) the selected component into another library, with its
   *  technology/commodity dependencies, then persist the target. */
  async function copySelected(targetId: string, move: boolean) {
    if (!lib || !sel || targetId === activeId) return;
    try {
      const target = await getComponentLibrary(targetId);
      const next: ComponentLibrary = JSON.parse(JSON.stringify(target));
      if (sel.kind === "commodity") {
        const c = lib.commodities.find((x) => x.commodity_id === sel.id);
        if (c && !next.commodities.some((x) => x.commodity_id === c.commodity_id)) next.commodities.push(c);
      } else if (sel.kind === "technology") {
        const t = lib.technologies.find((x) => x.technology_id === sel.id);
        if (t && !next.technologies.some((x) => x.technology_id === t.technology_id)) next.technologies.push(t);
      } else if (sel.kind === "machine") {
        const m = lib.machines.find((x) => x.name === sel.id);
        if (m) {
          if (!next.machines.some((x) => x.name === m.name)) next.machines.push(m);
          const t = lib.technologies.find((x) => x.technology_id === m.technology);
          if (t && !next.technologies.some((x) => x.technology_id === t.technology_id)) next.technologies.push(t);
        }
      } else if (sel.kind === "group") {
        const g = lib.groups.find((x) => x.name === sel.id);
        if (g && !next.groups.some((x) => x.name === g.name)) next.groups.push(g);
      }
      await saveComponentLibrary(targetId, next);
      setLibs(await listComponentLibraries());
      if (move) deleteSelected();
      setStatus("saved");
    } catch (e) {
      setError(String(e));
    }
  }

  const commodityIds = useMemo(() => (lib?.commodities ?? []).map((c) => c.commodity_id), [lib]);
  const techIds = useMemo(() => (lib?.technologies ?? []).map((t) => t.technology_id), [lib]);
  const componentNames = useMemo(
    () => [...(lib?.machines ?? []).map((m) => m.name), ...(lib?.groups ?? []).map((g) => g.name)],
    [lib],
  );

  const statusText =
    status === "saving" ? "saving…" : status === "saved" ? "saved" : status === "error" ? "save failed" : "";

  return (
    <div className="view-full builder">
      {error && (
        <div className="error" style={{ padding: "4px 12px" }} onClick={() => setError(null)}>
          {error} <span className="muted">(click to dismiss)</span>
        </div>
      )}
      <div style={{ display: "flex", height: "100%", minHeight: 0 }}>
        {/* ── Left rail: libraries + component lists ── */}
        <aside className="rail" style={{ width: 256, overflow: "auto", borderRight: "1px solid var(--border)" }}>
          <div className="rail-section">
            <div className="rail-head-row">
              <span className="rail-head">Libraries</span>
              <button className="rail-add" title="new library" onClick={newLibrary}>
                ＋
              </button>
            </div>
            {libs.map((l) => (
              <div key={l.id} className="rail-item-row">
                <button
                  className={`rail-item${l.id === activeId ? " is-active" : ""}`}
                  onClick={() => openLib(l.id)}
                  style={{ flex: 1, textAlign: "left" }}
                >
                  {l.label} <span className="rail-count">{l.machines + l.groups}</span>
                </button>
                <button className="rail-add" title="delete library" onClick={() => removeLibrary(l.id)}>
                  ✕
                </button>
              </div>
            ))}
            {libs.length === 0 && <div className="rail-empty">No libraries — add one.</div>}
          </div>

          {lib && (
            <>
              <ComponentList
                title="Technologies"
                items={lib.technologies.map((t) => ({ id: t.technology_id, label: t.technology_id }))}
                kind="technology"
                sel={sel}
                onSelect={setSel}
                onAdd={addTechnology}
              />
              <ComponentList
                title="Machines (facilities)"
                items={lib.machines.map((m) => ({ id: m.name, label: m.label || m.name }))}
                kind="machine"
                sel={sel}
                onSelect={setSel}
                onAdd={addMachine}
              />
              <ComponentList
                title="Groups"
                items={lib.groups.map((g) => ({ id: g.name, label: g.label || g.name }))}
                kind="group"
                sel={sel}
                onSelect={setSel}
                onAdd={addGroup}
              />
              <ComponentList
                title="Streams"
                items={lib.commodities.map((c) => ({ id: c.commodity_id, label: c.commodity_id }))}
                kind="commodity"
                sel={sel}
                onSelect={setSel}
                onAdd={addCommodity}
              />
            </>
          )}
        </aside>

        {/* ── Main: focused editor for the selected component ── */}
        <main style={{ flex: 1, overflow: "auto", padding: "16px 20px", minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
            <div className="eyebrow">component builder</div>
            <span className="muted" style={{ fontSize: "0.78rem" }}>
              {activeId ? lib?.label || activeId : "no library"} · {statusText}
            </span>
            {sel && (
              <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                <CopyMove libs={libs} activeId={activeId} onCopy={(t) => copySelected(t, false)} onMove={(t) => copySelected(t, true)} />
                <button className="ghost" onClick={deleteSelected} title="delete this component">
                  ✕ delete
                </button>
              </div>
            )}
          </div>

          {!lib && <p className="muted">Pick or create a library on the left to start building.</p>}
          {lib && !sel && (
            <p className="muted">
              Select a component on the left, or add one. Build a <b>technology</b> and its streams,
              package it as a <b>machine</b> (with its MACC measures), then compose <b>groups</b>.
            </p>
          )}

          {lib && sel?.kind === "commodity" && (
            <CommodityEditor
              value={lib.commodities.find((c) => c.commodity_id === sel.id)!}
              onChange={(v) =>
                commit({ ...lib, commodities: lib.commodities.map((c) => (c.commodity_id === sel.id ? v : c)) })
              }
              onRename={(id) => setSel({ kind: "commodity", id })}
            />
          )}
          {lib && sel?.kind === "technology" && (
            <TechnologyEditor
              value={lib.technologies.find((t) => t.technology_id === sel.id)!}
              commodityIds={commodityIds}
              onAddCommodity={(id) =>
                commit({ ...lib, commodities: [...lib.commodities, { commodity_id: id, kind: "material", unit: "unit" }] })
              }
              onChange={(v) =>
                commit({ ...lib, technologies: lib.technologies.map((t) => (t.technology_id === sel.id ? v : t)) })
              }
              onRename={(id) => setSel({ kind: "technology", id })}
            />
          )}
          {lib && sel?.kind === "machine" && (
            <MachineEditor
              value={lib.machines.find((m) => m.name === sel.id)!}
              techIds={techIds}
              commodityIds={commodityIds}
              onChange={(v) => commit({ ...lib, machines: lib.machines.map((m) => (m.name === sel.id ? v : m)) })}
              onRename={(id) => setSel({ kind: "machine", id })}
            />
          )}
          {lib && sel?.kind === "group" && (
            <GroupEditor
              value={lib.groups.find((g) => g.name === sel.id)!}
              componentNames={componentNames.filter((nm) => nm !== sel.id)}
              commodityIds={commodityIds}
              onChange={(v) => commit({ ...lib, groups: lib.groups.map((g) => (g.name === sel.id ? v : g)) })}
              onRename={(id) => setSel({ kind: "group", id })}
            />
          )}
        </main>
      </div>
    </div>
  );
}

// ── Rail list of one component kind ──────────────────────────────────────────
function ComponentList({
  title,
  items,
  kind,
  sel,
  onSelect,
  onAdd,
}: {
  title: string;
  items: { id: string; label: string }[];
  kind: Kind;
  sel: Sel | null;
  onSelect: (s: Sel) => void;
  onAdd: () => void;
}) {
  return (
    <div className="rail-section">
      <div className="rail-head-row">
        <span className="rail-subhead">{title}</span>
        <button className="rail-add" title={`add ${kind}`} onClick={onAdd}>
          ＋
        </button>
      </div>
      {items.map((it) => (
        <button
          key={it.id}
          className={`rail-item${sel?.kind === kind && sel.id === it.id ? " is-active" : ""}`}
          onClick={() => onSelect({ kind, id: it.id })}
          style={{ textAlign: "left", width: "100%" }}
        >
          {it.label}
        </button>
      ))}
      {items.length === 0 && <div className="rail-empty">none</div>}
    </div>
  );
}

// ── Small field helpers ──────────────────────────────────────────────────────
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: "0.78rem" }}>
      <span className="muted">{label}</span>
      {children}
    </label>
  );
}
const inputStyle: React.CSSProperties = {
  padding: "4px 6px",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-button)",
  background: "var(--surface)",
  font: "inherit",
};
function Row({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>{children}</div>;
}

// ── Copy / move dropdown ─────────────────────────────────────────────────────
function CopyMove({
  libs,
  activeId,
  onCopy,
  onMove,
}: {
  libs: LibrarySummary[];
  activeId: string | null;
  onCopy: (target: string) => void;
  onMove: (target: string) => void;
}) {
  const targets = libs.filter((l) => l.id !== activeId);
  if (targets.length === 0) return null;
  return (
    <>
      <select
        defaultValue=""
        title="copy to library"
        style={inputStyle}
        onChange={(e) => {
          if (e.target.value) onCopy(e.target.value);
          e.target.value = "";
        }}
      >
        <option value="">copy to…</option>
        {targets.map((l) => (
          <option key={l.id} value={l.id}>
            {l.label}
          </option>
        ))}
      </select>
      <select
        defaultValue=""
        title="move to library"
        style={inputStyle}
        onChange={(e) => {
          if (e.target.value) onMove(e.target.value);
          e.target.value = "";
        }}
      >
        <option value="">move to…</option>
        {targets.map((l) => (
          <option key={l.id} value={l.id}>
            {l.label}
          </option>
        ))}
      </select>
    </>
  );
}

// ── Commodity editor ─────────────────────────────────────────────────────────
function CommodityEditor({
  value,
  onChange,
  onRename,
}: {
  value: CommodityTemplate;
  onChange: (v: CommodityTemplate) => void;
  onRename: (id: string) => void;
}) {
  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>Stream</h2>
      <Row>
        <Field label="id">
          <input
            style={inputStyle}
            value={value.commodity_id}
            onChange={(e) => {
              onChange({ ...value, commodity_id: e.target.value });
              onRename(e.target.value);
            }}
          />
        </Field>
        <Field label="kind">
          <select
            style={inputStyle}
            value={value.kind}
            onChange={(e) => onChange({ ...value, kind: e.target.value as CommodityTemplate["kind"] })}
          >
            {["energy", "material", "indirect", "product", "byproduct"].map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </Field>
        <Field label="unit">
          <input style={inputStyle} value={value.unit} onChange={(e) => onChange({ ...value, unit: e.target.value })} />
        </Field>
        <Field label="price (buy)">
          <input
            style={inputStyle}
            type="number"
            value={value.price ?? ""}
            onChange={(e) => onChange({ ...value, price: e.target.value === "" ? null : num(e.target.value) })}
          />
        </Field>
        <Field label="sale price">
          <input
            style={inputStyle}
            type="number"
            value={value.sale_price ?? ""}
            onChange={(e) => onChange({ ...value, sale_price: e.target.value === "" ? null : num(e.target.value) })}
          />
        </Field>
      </Row>
    </section>
  );
}

// ── Technology editor (recipe + io streams) ──────────────────────────────────
function TechnologyEditor({
  value,
  commodityIds,
  onAddCommodity,
  onChange,
  onRename,
}: {
  value: TechnologyTemplate;
  commodityIds: string[];
  onAddCommodity: (id: string) => void;
  onChange: (v: TechnologyTemplate) => void;
  onRename: (id: string) => void;
}) {
  const setIo = (i: number, patch: Partial<IoRow>) =>
    onChange({ ...value, io: value.io.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const addIo = () => onChange({ ...value, io: [...value.io, { target: "", role: "input", coefficient: 1 }] });
  const delIo = (i: number) => onChange({ ...value, io: value.io.filter((_, j) => j !== i) });

  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>Technology</h2>
      <Row>
        <Field label="id">
          <input
            style={inputStyle}
            value={value.technology_id}
            onChange={(e) => {
              onChange({ ...value, technology_id: e.target.value });
              onRename(e.target.value);
            }}
          />
        </Field>
        <Field label="lifespan (yr)">
          <input style={{ ...inputStyle, width: 90 }} type="number" value={value.lifespan} onChange={(e) => onChange({ ...value, lifespan: num(e.target.value) })} />
        </Field>
        <Field label="capex /cap">
          <input style={{ ...inputStyle, width: 100 }} type="number" value={value.capex} onChange={(e) => onChange({ ...value, capex: num(e.target.value) })} />
        </Field>
        <Field label="opex /unit">
          <input style={{ ...inputStyle, width: 100 }} type="number" value={value.opex} onChange={(e) => onChange({ ...value, opex: num(e.target.value) })} />
        </Field>
      </Row>

      <h3 style={{ margin: "8px 0 6px", fontSize: "0.85rem" }}>
        Streams <span className="muted">(inputs · outputs · impacts)</span>
        <button className="ghost" style={{ marginLeft: 8 }} onClick={addIo}>
          ＋ add stream
        </button>
      </h3>
      <table className="grid" style={{ width: "100%", fontSize: "0.78rem", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--muted)" }}>
            <th style={{ width: "26%" }}>target</th>
            <th>role</th>
            <th>coef</th>
            <th>product?</th>
            <th>blend group</th>
            <th>min</th>
            <th>max</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {value.io.map((r, i) => (
            <tr key={i}>
              <td>
                <SearchableSelect
                  value={r.target}
                  options={commodityIds}
                  onChange={(v) => setIo(i, { target: v })}
                  onCreate={r.role === "impact" ? (name) => setIo(i, { target: name }) : (name) => { onAddCommodity(name); setIo(i, { target: name }); }}
                  placeholder={r.role === "impact" ? "impact id" : "stream"}
                />
              </td>
              <td>
                <select style={inputStyle} value={r.role} onChange={(e) => setIo(i, { role: e.target.value as IoRow["role"] })}>
                  <option value="input">input</option>
                  <option value="output">output</option>
                  <option value="impact">impact</option>
                </select>
              </td>
              <td>
                <input style={{ ...inputStyle, width: 70 }} type="number" value={r.coefficient} onChange={(e) => setIo(i, { coefficient: num(e.target.value) })} />
              </td>
              <td style={{ textAlign: "center" }}>
                {r.role === "output" && (
                  <input type="checkbox" checked={!!r.is_product} onChange={(e) => setIo(i, { is_product: e.target.checked })} />
                )}
              </td>
              <td>
                <input style={{ ...inputStyle, width: 80 }} value={r.group ?? ""} onChange={(e) => setIo(i, { group: e.target.value || null })} />
              </td>
              <td>
                <input style={{ ...inputStyle, width: 56 }} type="number" value={r.share_min ?? ""} onChange={(e) => setIo(i, { share_min: e.target.value === "" ? null : num(e.target.value) })} />
              </td>
              <td>
                <input style={{ ...inputStyle, width: 56 }} type="number" value={r.share_max ?? ""} onChange={(e) => setIo(i, { share_max: e.target.value === "" ? null : num(e.target.value) })} />
              </td>
              <td>
                <button className="ghost" title="remove" onClick={() => delIo(i)}>
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {value.io.length === 0 && <p className="muted" style={{ fontSize: "0.78rem" }}>No streams yet — a technology needs at least one product output.</p>}
    </section>
  );
}

// ── Machine editor (facility) + Measures (MACC) subgroup ─────────────────────
function MachineEditor({
  value,
  techIds,
  commodityIds,
  onChange,
  onRename,
}: {
  value: MachineComponent;
  techIds: string[];
  commodityIds: string[];
  onChange: (v: MachineComponent) => void;
  onRename: (id: string) => void;
}) {
  const setMeasure = (i: number, patch: Partial<MeasureTemplate>) =>
    onChange({ ...value, measures: value.measures.map((m, j) => (j === i ? { ...m, ...patch } : m)) });
  const addMeasure = () =>
    onChange({
      ...value,
      measures: [
        ...value.measures,
        {
          measure_id: `measure_${value.measures.length + 1}`,
          label: "",
          type: "energy_efficiency",
          target: commodityIds[0] ?? "",
          lifetime: 15,
          blocks: [{ reduction: 0.05, capex_per_capacity: 0, opex_per_capacity: 0 }],
        },
      ],
    });
  const delMeasure = (i: number) => onChange({ ...value, measures: value.measures.filter((_, j) => j !== i) });

  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>Machine (facility)</h2>
      <Row>
        <Field label="name">
          <input
            style={inputStyle}
            value={value.name}
            onChange={(e) => {
              onChange({ ...value, name: e.target.value });
              onRename(e.target.value);
            }}
          />
        </Field>
        <Field label="label">
          <input style={inputStyle} value={value.label} onChange={(e) => onChange({ ...value, label: e.target.value })} />
        </Field>
        <Field label="technology">
          <div style={{ minWidth: 180 }}>
            <SearchableSelect value={value.technology} options={techIds} onChange={(v) => onChange({ ...value, technology: v })} hint="add a technology first" />
          </div>
        </Field>
        <Field label="capacity">
          <input style={{ ...inputStyle, width: 110 }} type="number" value={value.capacity} onChange={(e) => onChange({ ...value, capacity: num(e.target.value) })} />
        </Field>
      </Row>

      <h3 style={{ margin: "12px 0 6px", fontSize: "0.85rem" }}>
        Measures <span className="muted">(MACC retrofits of this machine)</span>
        <button className="ghost" style={{ marginLeft: 8 }} onClick={addMeasure}>
          ＋ add measure
        </button>
      </h3>
      {value.measures.map((m, i) => (
        <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 4, padding: 10, marginBottom: 8 }}>
          <Row>
            <Field label="id">
              <input style={inputStyle} value={m.measure_id} onChange={(e) => setMeasure(i, { measure_id: e.target.value })} />
            </Field>
            <Field label="label">
              <input style={inputStyle} value={m.label} onChange={(e) => setMeasure(i, { label: e.target.value })} />
            </Field>
            <Field label="type">
              <select style={inputStyle} value={m.type} onChange={(e) => setMeasure(i, { type: e.target.value as MeasureTemplate["type"] })}>
                <option value="energy_efficiency">energy_efficiency</option>
                <option value="emission_reduction">emission_reduction</option>
                <option value="environmental">environmental</option>
              </select>
            </Field>
            <Field label="target">
              <div style={{ minWidth: 140 }}>
                <SearchableSelect value={m.target} options={commodityIds} onChange={(v) => setMeasure(i, { target: v })} onCreate={(name) => setMeasure(i, { target: name })} placeholder="stream / impact" />
              </div>
            </Field>
            <Field label="lifetime">
              <input style={{ ...inputStyle, width: 70 }} type="number" value={m.lifetime} onChange={(e) => setMeasure(i, { lifetime: num(e.target.value) })} />
            </Field>
            <button className="ghost" style={{ alignSelf: "flex-end" }} onClick={() => delMeasure(i)} title="remove measure">
              ✕
            </button>
          </Row>
          <table className="grid" style={{ fontSize: "0.76rem" }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                <th>block</th>
                <th>reduction</th>
                <th>capex /cap</th>
                <th>opex /cap</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {m.blocks.map((b, bi) => (
                <tr key={bi}>
                  <td className="muted">{bi}</td>
                  <td>
                    <input style={{ ...inputStyle, width: 70 }} type="number" step="0.01" value={b.reduction} onChange={(e) => setMeasure(i, { blocks: m.blocks.map((x, j) => (j === bi ? { ...x, reduction: num(e.target.value) } : x)) })} />
                  </td>
                  <td>
                    <input style={{ ...inputStyle, width: 90 }} type="number" value={b.capex_per_capacity} onChange={(e) => setMeasure(i, { blocks: m.blocks.map((x, j) => (j === bi ? { ...x, capex_per_capacity: num(e.target.value) } : x)) })} />
                  </td>
                  <td>
                    <input style={{ ...inputStyle, width: 90 }} type="number" value={b.opex_per_capacity} onChange={(e) => setMeasure(i, { blocks: m.blocks.map((x, j) => (j === bi ? { ...x, opex_per_capacity: num(e.target.value) } : x)) })} />
                  </td>
                  <td>
                    <button className="ghost" onClick={() => setMeasure(i, { blocks: m.blocks.filter((_, j) => j !== bi) })} title="remove block">
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="ghost" style={{ marginTop: 4 }} onClick={() => setMeasure(i, { blocks: [...m.blocks, { reduction: 0.02, capex_per_capacity: 0, opex_per_capacity: 0 }] })}>
            ＋ add block
          </button>
        </div>
      ))}
      {value.measures.length === 0 && <p className="muted" style={{ fontSize: "0.78rem" }}>No measures — this machine has no MACC retrofits.</p>}
    </section>
  );
}

// ── Group editor (children + internal connections) ───────────────────────────
function GroupEditor({
  value,
  componentNames,
  commodityIds,
  onChange,
  onRename,
}: {
  value: GroupComponent;
  componentNames: string[];
  commodityIds: string[];
  onChange: (v: GroupComponent) => void;
  onRename: (id: string) => void;
}) {
  const aliases = value.children.map((c) => c.alias || c.component);
  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>Group</h2>
      <Row>
        <Field label="name">
          <input
            style={inputStyle}
            value={value.name}
            onChange={(e) => {
              onChange({ ...value, name: e.target.value });
              onRename(e.target.value);
            }}
          />
        </Field>
        <Field label="label">
          <input style={inputStyle} value={value.label} onChange={(e) => onChange({ ...value, label: e.target.value })} />
        </Field>
        <Field label="level">
          <input style={inputStyle} value={value.level} onChange={(e) => onChange({ ...value, level: e.target.value })} placeholder="e.g. facility, company" />
        </Field>
      </Row>

      <h3 style={{ margin: "8px 0 6px", fontSize: "0.85rem" }}>
        Children <span className="muted">(other components placed inside)</span>
        <button className="ghost" style={{ marginLeft: 8 }} onClick={() => onChange({ ...value, children: [...value.children, { component: componentNames[0] ?? "", alias: "" }] })}>
          ＋ add child
        </button>
      </h3>
      {value.children.map((c, i) => (
        <Row key={i}>
          <Field label="component">
            <div style={{ minWidth: 180 }}>
              <SearchableSelect value={c.component} options={componentNames} onChange={(v) => onChange({ ...value, children: value.children.map((x, j) => (j === i ? { ...x, component: v } : x)) })} hint="build a machine/group first" />
            </div>
          </Field>
          <Field label="alias (instance name)">
            <input style={inputStyle} value={c.alias} placeholder={c.component} onChange={(e) => onChange({ ...value, children: value.children.map((x, j) => (j === i ? { ...x, alias: e.target.value } : x)) })} />
          </Field>
          <button className="ghost" style={{ alignSelf: "flex-end" }} onClick={() => onChange({ ...value, children: value.children.filter((_, j) => j !== i) })}>
            ✕
          </button>
        </Row>
      ))}

      <h3 style={{ margin: "12px 0 6px", fontSize: "0.85rem" }}>
        Connections <span className="muted">(wiring between children)</span>
        <button className="ghost" style={{ marginLeft: 8 }} onClick={() => onChange({ ...value, connections: [...value.connections, { source: aliases[0] ?? "", target: aliases[1] ?? "", commodity: commodityIds[0] ?? "", lag_years: 0 }] })} disabled={value.children.length < 2}>
          ＋ add connection
        </button>
      </h3>
      {value.connections.map((cn, i) => (
        <Row key={i}>
          <Field label="from">
            <select style={inputStyle} value={cn.source} onChange={(e) => onChange({ ...value, connections: value.connections.map((x, j) => (j === i ? { ...x, source: e.target.value } : x)) })}>
              {aliases.map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </Field>
          <Field label="to">
            <select style={inputStyle} value={cn.target} onChange={(e) => onChange({ ...value, connections: value.connections.map((x, j) => (j === i ? { ...x, target: e.target.value } : x)) })}>
              {aliases.map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </Field>
          <Field label="commodity">
            <select style={inputStyle} value={cn.commodity} onChange={(e) => onChange({ ...value, connections: value.connections.map((x, j) => (j === i ? { ...x, commodity: e.target.value } : x)) })}>
              {commodityIds.map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </Field>
          <Field label="lag (yr)">
            <input style={{ ...inputStyle, width: 64 }} type="number" value={cn.lag_years} onChange={(e) => onChange({ ...value, connections: value.connections.map((x, j) => (j === i ? { ...x, lag_years: num(e.target.value) } : x)) })} />
          </Field>
          <button className="ghost" style={{ alignSelf: "flex-end" }} onClick={() => onChange({ ...value, connections: value.connections.filter((_, j) => j !== i) })}>
            ✕
          </button>
        </Row>
      ))}
    </section>
  );
}
