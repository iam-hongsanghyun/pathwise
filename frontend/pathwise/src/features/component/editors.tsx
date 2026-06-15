// Detail editors for the Component builder — each edits one component's core
// substance. Pure presentational; the host maps changes back into the library.

import { SearchableSelect } from "../controls/SearchableSelect";
import type {
  CommodityTemplate,
  GroupComponent,
  IoRow,
  MachineComponent,
  MaccGroup,
  MeasureTemplate,
  TechnologyTemplate,
} from "../../lib/api/components";

export const num = (v: string): number => (v.trim() === "" ? 0 : Number(v) || 0);

export const inputStyle: React.CSSProperties = {
  padding: "4px 6px",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-button)",
  background: "var(--surface)",
  font: "inherit",
};

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: "0.78rem" }}>
      <span className="muted">{label}</span>
      {children}
    </label>
  );
}

export function Row({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>{children}</div>;
}

// ── Commodity / stream ────────────────────────────────────────────────────────
export function CommodityEditor({
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

// ── Technology (recipe streams) ───────────────────────────────────────────────
export function TechnologyEditor({
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
      <h2 style={{ margin: "0 0 12px" }}>Technology (recipe)</h2>
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
      <table className="grid" style={{ width: "100%", fontSize: "0.78rem" }}>
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
                  onCreate={
                    r.role === "impact"
                      ? (name) => setIo(i, { target: name })
                      : (name) => {
                          onAddCommodity(name);
                          setIo(i, { target: name });
                        }
                  }
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

// ── Machine (facility) + MACC measures ────────────────────────────────────────
export function MachineEditor({
  value,
  techIds,
  commodityIds,
  embeddedTech,
  onChange,
  onRename,
}: {
  value: MachineComponent;
  techIds: string[];
  commodityIds: string[];
  /** Optional inline recipe editor for the machine's technology (1:1 feel). */
  embeddedTech?: React.ReactNode;
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
            <SearchableSelect value={value.technology} options={techIds} onChange={(v) => onChange({ ...value, technology: v })} onCreate={(name) => onChange({ ...value, technology: name })} hint="add a technology first" />
          </div>
        </Field>
        <Field label="capacity">
          <input style={{ ...inputStyle, width: 110 }} type="number" value={value.capacity} onChange={(e) => onChange({ ...value, capacity: num(e.target.value) })} />
        </Field>
      </Row>

      {embeddedTech}

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

// ── Standalone measure (reusable) ─────────────────────────────────────────────
export function MeasureEditor({
  value,
  commodityIds,
  onChange,
  onRename,
}: {
  value: MeasureTemplate;
  commodityIds: string[];
  onChange: (v: MeasureTemplate) => void;
  onRename: (id: string) => void;
}) {
  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>Measure <span className="muted" style={{ fontSize: "0.8rem" }}>(reusable)</span></h2>
      <Row>
        <Field label="id">
          <input style={inputStyle} value={value.measure_id} onChange={(e) => { onChange({ ...value, measure_id: e.target.value }); onRename(e.target.value); }} />
        </Field>
        <Field label="label">
          <input style={inputStyle} value={value.label} onChange={(e) => onChange({ ...value, label: e.target.value })} />
        </Field>
        <Field label="type">
          <select style={inputStyle} value={value.type} onChange={(e) => onChange({ ...value, type: e.target.value as MeasureTemplate["type"] })}>
            <option value="energy_efficiency">energy_efficiency</option>
            <option value="emission_reduction">emission_reduction</option>
            <option value="environmental">environmental</option>
          </select>
        </Field>
        <Field label="target">
          <div style={{ minWidth: 150 }}>
            <SearchableSelect value={value.target} options={commodityIds} onChange={(v) => onChange({ ...value, target: v })} onCreate={(name) => onChange({ ...value, target: name })} placeholder="stream / impact" />
          </div>
        </Field>
        <Field label="lifetime">
          <input style={{ ...inputStyle, width: 70 }} type="number" value={value.lifetime} onChange={(e) => onChange({ ...value, lifetime: num(e.target.value) })} />
        </Field>
      </Row>
      <h3 style={{ margin: "8px 0 6px", fontSize: "0.85rem" }}>
        Cost curve <span className="muted">(piecewise blocks)</span>
        <button className="ghost" style={{ marginLeft: 8 }} onClick={() => onChange({ ...value, blocks: [...value.blocks, { reduction: 0.02, capex_per_capacity: 0, opex_per_capacity: 0 }] })}>＋ add block</button>
      </h3>
      <table className="grid" style={{ fontSize: "0.78rem" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--muted)" }}><th>block</th><th>reduction</th><th>capex /cap</th><th>opex /cap</th><th /></tr>
        </thead>
        <tbody>
          {value.blocks.map((b, bi) => (
            <tr key={bi}>
              <td className="muted">{bi}</td>
              <td><input style={{ ...inputStyle, width: 70 }} type="number" step="0.01" value={b.reduction} onChange={(e) => onChange({ ...value, blocks: value.blocks.map((x, j) => (j === bi ? { ...x, reduction: num(e.target.value) } : x)) })} /></td>
              <td><input style={{ ...inputStyle, width: 90 }} type="number" value={b.capex_per_capacity} onChange={(e) => onChange({ ...value, blocks: value.blocks.map((x, j) => (j === bi ? { ...x, capex_per_capacity: num(e.target.value) } : x)) })} /></td>
              <td><input style={{ ...inputStyle, width: 90 }} type="number" value={b.opex_per_capacity} onChange={(e) => onChange({ ...value, blocks: value.blocks.map((x, j) => (j === bi ? { ...x, opex_per_capacity: num(e.target.value) } : x)) })} /></td>
              <td><button className="ghost" onClick={() => onChange({ ...value, blocks: value.blocks.filter((_, j) => j !== bi) })}>✕</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {value.blocks.length === 0 && <p className="muted" style={{ fontSize: "0.78rem" }}>No blocks — a measure needs at least one cost-curve step.</p>}
    </section>
  );
}

// ── MACC (a group/bundle of measures) ─────────────────────────────────────────
export function MaccEditor({
  value,
  measures,
  onChange,
  onRename,
}: {
  value: MaccGroup;
  /** All standalone measures available to bundle. */
  measures: { id: string; label: string }[];
  onChange: (v: MaccGroup) => void;
  onRename: (id: string) => void;
}) {
  const toggle = (mid: string, on: boolean) =>
    onChange({ ...value, measures: on ? [...value.measures, mid] : value.measures.filter((m) => m !== mid) });
  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>MACC <span className="muted" style={{ fontSize: "0.8rem" }}>(group of measures)</span></h2>
      <Row>
        <Field label="id">
          <input style={inputStyle} value={value.macc_id} onChange={(e) => { onChange({ ...value, macc_id: e.target.value }); onRename(e.target.value); }} />
        </Field>
        <Field label="label">
          <input style={inputStyle} value={value.label} onChange={(e) => onChange({ ...value, label: e.target.value })} />
        </Field>
      </Row>
      <h3 style={{ margin: "8px 0 6px", fontSize: "0.85rem" }}>Measures in this MACC</h3>
      {measures.length === 0 && <p className="muted" style={{ fontSize: "0.78rem" }}>No measures yet — add individual measures first.</p>}
      {measures.map((m) => (
        <label key={m.id} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: "0.82rem", padding: "2px 0" }}>
          <input type="checkbox" checked={value.measures.includes(m.id)} onChange={(e) => toggle(m.id, e.target.checked)} />
          {m.label}
        </label>
      ))}
    </section>
  );
}

// ── Group (bundle of components) ──────────────────────────────────────────────
export function GroupEditor({
  value,
  componentNames,
  onChange,
  onRename,
}: {
  value: GroupComponent;
  componentNames: string[];
  onChange: (v: GroupComponent) => void;
  onRename: (id: string) => void;
}) {
  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>Group (bundle)</h2>
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
        Children <span className="muted">(components placed inside this bundle)</span>
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
      <p className="muted" style={{ fontSize: "0.74rem" }}>
        Connections between children are drawn in the Value Chain tab (this tab defines what
        components <i>are</i>).
      </p>
    </section>
  );
}
