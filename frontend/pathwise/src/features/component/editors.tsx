// Detail editors for the Component builder — each edits one component's core
// substance. Pure presentational; the host maps changes back into the library.

import { SearchableSelect } from "../controls/SearchableSelect";
import { SearchSelect } from "../controls/SearchSelect";
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
          <SearchSelect
            value={value.kind}
            onChange={(v) => onChange({ ...value, kind: v as CommodityTemplate["kind"] })}
            options={["energy", "material", "indirect", "product", "byproduct"].map((k) => ({ value: k }))}
          />
        </Field>
        <Field label="sector">
          <input
            style={inputStyle}
            value={value.sector ?? ""}
            placeholder="e.g. steel · power · (blank = general)"
            onChange={(e) => onChange({ ...value, sector: e.target.value.trim() === "" ? null : e.target.value })}
          />
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
        <Field label="available from">
          <input style={{ ...inputStyle, width: 90 }} type="number" placeholder="any" value={value.introduction_year ?? ""}
            onChange={(e) => onChange({ ...value, introduction_year: e.target.value === "" ? null : Math.round(num(e.target.value)) })} />
        </Field>
        <Field label="available to">
          <input style={{ ...inputStyle, width: 90 }} type="number" placeholder="any" value={value.phase_out_year ?? ""}
            onChange={(e) => onChange({ ...value, phase_out_year: e.target.value === "" ? null : Math.round(num(e.target.value)) })} />
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
                <SearchSelect value={r.role} onChange={(v) => setIo(i, { role: v as IoRow["role"] })}
                  options={[{ value: "input" }, { value: "output" }, { value: "impact" }]} />
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
              <SearchSelect value={m.type} onChange={(v) => setMeasure(i, { type: v as MeasureTemplate["type"] })}
                options={[{ value: "energy_efficiency" }, { value: "emission_reduction" }, { value: "environmental" }]} />
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
          <SearchSelect value={value.type} onChange={(v) => onChange({ ...value, type: v as MeasureTemplate["type"] })}
            options={[{ value: "energy_efficiency" }, { value: "emission_reduction" }, { value: "environmental" }]} />
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
// A marginal-abatement-cost curve: one bar per measure block, width ∝ the
// reduction it delivers, height ∝ its marginal cost (capex per unit reduced),
// sorted cheapest-first. Negative-cost ("no-regret") blocks sit below the axis.
export function MaccChart({ measures }: { measures: MeasureTemplate[] }) {
  const blocks = measures
    .flatMap((m) =>
      m.blocks.map((b) => ({
        name: m.label || m.measure_id,
        width: b.reduction,
        cost: b.reduction > 0 ? b.capex_per_capacity / b.reduction : 0,
      })),
    )
    .filter((b) => b.width > 0)
    .sort((a, b) => a.cost - b.cost);
  if (blocks.length === 0)
    return <p className="muted" style={{ fontSize: "0.78rem" }}>Bundle measures (with blocks) to see the MACC curve.</p>;

  const W = 520, H = 210, padL = 52, padB = 30, padT = 12, padR = 12;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const totalW = blocks.reduce((s, b) => s + b.width, 0) || 1;
  const maxCost = Math.max(...blocks.map((b) => b.cost), 0);
  const minCost = Math.min(...blocks.map((b) => b.cost), 0);
  const range = maxCost - minCost || 1;
  const yOf = (c: number) => padT + ((maxCost - c) / range) * plotH;
  const y0 = yOf(0);
  let cx = padL;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: W, height: "auto" }} role="img" aria-label="MACC curve">
      {/* axes */}
      <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="var(--border-strong)" strokeWidth={1} />
      <line x1={padL} y1={y0} x2={W - padR} y2={y0} stroke="var(--border-strong)" strokeWidth={1} />
      <text x={6} y={padT + 8} fontSize={9} fill="var(--muted)">cost / unit abated</text>
      <text x={W - padR} y={y0 + 18} fontSize={9} fill="var(--muted)" textAnchor="end">cumulative abatement →</text>
      {blocks.map((b, i) => {
        const w = (b.width / totalW) * plotW;
        const yc = yOf(b.cost);
        const x = cx;
        cx += w;
        const top = Math.min(yc, y0);
        const h = Math.max(Math.abs(yc - y0), 1);
        const pos = b.cost >= 0;
        return (
          <g key={i}>
            <rect x={x} y={top} width={Math.max(w - 1, 1)} height={h}
              fill={pos ? "var(--brand)" : "var(--warn)"} opacity={0.85} />
            {w > 26 && (
              <text x={x + w / 2} y={pos ? top - 3 : top + h + 10} fontSize={8}
                fill="var(--muted)" textAnchor="middle">
                {b.name.length > 10 ? `${b.name.slice(0, 9)}…` : b.name}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export function MaccEditor({
  value,
  measures,
  allMeasures,
  onChange,
  onRename,
}: {
  value: MaccGroup;
  /** All standalone measures available to bundle. */
  measures: { id: string; label: string }[];
  /** Full templates (for the MACC chart). */
  allMeasures: MeasureTemplate[];
  onChange: (v: MaccGroup) => void;
  onRename: (id: string) => void;
}) {
  const toggle = (mid: string, on: boolean) =>
    onChange({ ...value, measures: on ? [...value.measures, mid] : value.measures.filter((m) => m !== mid) });
  const bundled = allMeasures.filter((m) => value.measures.includes(m.measure_id));
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
      <h3 style={{ margin: "8px 0 6px", fontSize: "0.85rem" }}>MACC curve</h3>
      <MaccChart measures={bundled} />
      <h3 style={{ margin: "12px 0 6px", fontSize: "0.85rem" }}>Measures in this MACC</h3>
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
      <h3 style={{ margin: "12px 0 6px", fontSize: "0.85rem" }}>
        Connections <span className="muted">(internal wiring — e.g. GT → ST on steam)</span>
        <button className="ghost" style={{ marginLeft: 8 }} disabled={value.children.length < 2} onClick={() => onChange({ ...value, connections: [...value.connections, { source: aliases[0] ?? "", target: aliases[1] ?? "", commodity: commodityIds[0] ?? "", lag_years: 0 }] })}>
          ＋ add connection
        </button>
      </h3>
      {value.connections.map((cn, i) => (
        <Row key={i}>
          <Field label="from">
            <SearchSelect value={cn.source} onChange={(v) => onChange({ ...value, connections: value.connections.map((x, j) => (j === i ? { ...x, source: v } : x)) })}
              options={aliases.map((a) => ({ value: a }))} />
          </Field>
          <Field label="to">
            <SearchSelect value={cn.target} onChange={(v) => onChange({ ...value, connections: value.connections.map((x, j) => (j === i ? { ...x, target: v } : x)) })}
              options={aliases.map((a) => ({ value: a }))} />
          </Field>
          <Field label="commodity">
            <SearchSelect value={cn.commodity} onChange={(v) => onChange({ ...value, connections: value.connections.map((x, j) => (j === i ? { ...x, commodity: v } : x)) })}
              options={commodityIds.map((a) => ({ value: a }))} />
          </Field>
          <Field label="lag (yr)">
            <input style={{ ...inputStyle, width: 64 }} type="number" value={cn.lag_years} onChange={(e) => onChange({ ...value, connections: value.connections.map((x, j) => (j === i ? { ...x, lag_years: num(e.target.value) } : x)) })} />
          </Field>
          <button className="ghost" style={{ alignSelf: "flex-end" }} onClick={() => onChange({ ...value, connections: value.connections.filter((_, j) => j !== i) })}>✕</button>
        </Row>
      ))}
    </section>
  );
}
