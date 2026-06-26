// Detail editors for the Component builder — each edits one component's core
// substance. Pure presentational; the host maps changes back into the library.

import { InfoTooltip } from "../controls/InfoTooltip";
import { SearchableSelect } from "../controls/SearchableSelect";
import { SearchSelect } from "../controls/SearchSelect";
import { TemporalValue, type TemporalVal } from "../controls/TemporalValue";
import { RecipePreview } from "./RecipePreview";
import { fieldMeta } from "./fieldMeta";
import type {
  ByYear,
  FlowTemplate,
  GroupComponent,
  IoRow,
  LeverTemplate,
  AssetComponent,
  MaccGroup,
  StationTemplate,
  StorageTemplate,
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

export function Field({
  label,
  meta,
  info,
  unit,
  children,
}: {
  label: string;
  /** Data key to source the (i) explanation + unit from (see fieldMeta). */
  meta?: string;
  /** Explicit override of the explanation / unit. */
  info?: string;
  unit?: string;
  children: React.ReactNode;
}) {
  const m = meta ? fieldMeta(meta) : undefined;
  const tip = info ?? m?.info;
  const u = unit ?? m?.unit;
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: "0.78rem" }}>
      <span className="muted" style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
        {label}
        {tip && <InfoTooltip text={tip} unit={u} />}
      </span>
      {children}
    </label>
  );
}

/** A header cell carrying the same (i) tooltip as a Field, for data tables. */
export function Th({ label, meta, width }: { label: string; meta?: string; width?: string | number }) {
  const m = meta ? fieldMeta(meta) : undefined;
  return (
    <th style={{ width }}>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
        {label}
        {m?.info && <InfoTooltip text={m.info} unit={m.unit} />}
      </span>
    </th>
  );
}

export function Row({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>{children}</div>;
}

/** Inline static-or-temporal editor bridging a template's `scalar` + `scalar_by_year`
 *  pair. Static shows a plain clickable value; once it varies over the horizon it shows
 *  the green trend (↗ N yr). Mirrors the System view so every template field is
 *  temporal-capable in place — there is no separate "by year" panel. */
export function TemporalField({
  scalar,
  byYear,
  onChange,
  baseYear,
  periods,
  perYear = false,
  unit,
  placeholder = "0",
  label,
}: {
  scalar: number;
  byYear?: ByYear | null;
  /** `by` is undefined when the user reverts to a single static value. */
  onChange: (scalar: number, by: ByYear | undefined) => void;
  baseYear: number;
  periods?: number[];
  perYear?: boolean;
  unit?: string;
  placeholder?: string;
  label: string;
}) {
  const has = byYear != null && Object.keys(byYear).length > 0;
  const value: TemporalVal = has ? (byYear as ByYear) : scalar;
  return (
    <TemporalValue
      value={value}
      baseYear={baseYear}
      periods={periods}
      variant="text"
      perYear={perYear}
      unit={unit}
      placeholder={placeholder}
      label={label}
      onChange={(v) => {
        if (v == null) onChange(0, undefined);
        else if (typeof v === "number") onChange(v, undefined);
        else onChange(scalar, v); // keep the scalar as the fallback for absent years
      }}
    />
  );
}

// ── Flow / flow ────────────────────────────────────────────────────────
export function FlowEditor({
  value,
  onChange,
  onRename,
  unitOptions = [],
  baseYear = 2025,
  periods,
}: {
  value: FlowTemplate;
  onChange: (v: FlowTemplate) => void;
  onRename: (id: string) => void;
  /** Allowed units (the project's unit registry) — the unit picker is limited to
   *  these so a flow can't carry an unconvertible/typo'd unit. */
  unitOptions?: string[];
  /** Horizon context for the inline temporal price editors. */
  baseYear?: number;
  periods?: number[];
}) {
  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>Flow</h2>
      <Row>
        <Field label="id" meta="flow_id">
          <input
            style={inputStyle}
            value={value.flow_id}
            onChange={(e) => {
              onChange({ ...value, flow_id: e.target.value });
              onRename(e.target.value);
            }}
          />
        </Field>
        <Field label="kind" meta="kind">
          <SearchSelect
            value={value.kind}
            onChange={(v) => onChange({ ...value, kind: v as FlowTemplate["kind"] })}
            options={["energy", "material", "indirect", "product", "byproduct"].map((k) => ({ value: k }))}
          />
        </Field>
        <Field label="sector" meta="sector">
          <input
            style={inputStyle}
            value={value.sector ?? ""}
            placeholder="e.g. steel · power · (blank = general)"
            onChange={(e) => onChange({ ...value, sector: e.target.value.trim() === "" ? null : e.target.value })}
          />
        </Field>
        <Field label="unit" meta="unit">
          <SearchSelect
            value={value.unit ?? ""}
            onChange={(v) => onChange({ ...value, unit: v })}
            options={[...new Set([value.unit, ...unitOptions].filter(Boolean))].map((u) => ({ value: u }))}
            placeholder="pick a unit (Project → Units)"
          />
        </Field>
        <Field label="price (buy)" meta="price">
          <TemporalField scalar={value.price ?? 0} byYear={value.price_by_year} baseYear={baseYear} periods={periods}
            placeholder="no price" label={`${value.flow_id} · buy price`}
            onChange={(s, by) => onChange({ ...value, price: s, price_by_year: by })} />
        </Field>
        <Field label="sale price" meta="sale_price">
          <TemporalField scalar={value.sale_price ?? 0} byYear={value.sale_price_by_year} baseYear={baseYear} periods={periods}
            placeholder="no sale" label={`${value.flow_id} · sale price`}
            onChange={(s, by) => onChange({ ...value, sale_price: s, sale_price_by_year: by })} />
        </Field>
      </Row>
    </section>
  );
}

// ── Technology (recipe flows) ───────────────────────────────────────────────
// ── Storage ────────────────────────────────────────────────────────────────
export function StorageEditor({
  value,
  flowIds,
  onAddFlow,
  onChange,
  onRename,
}: {
  value: StorageTemplate;
  flowIds: string[];
  onAddFlow: (id: string) => void;
  onChange: (v: StorageTemplate) => void;
  onRename: (id: string) => void;
}) {
  const numField = (
    label: string,
    key: keyof StorageTemplate,
    meta?: string,
    width = 100,
    step?: string,
  ) => (
    <Field label={label} meta={meta ?? (key as string)}>
      <input
        style={{ ...inputStyle, width }}
        type="number"
        step={step}
        value={(value[key] as number) ?? 0}
        onChange={(e) => onChange({ ...value, [key]: num(e.target.value) })}
      />
    </Field>
  );
  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>Storage</h2>
      <Row>
        <Field label="id" meta="storage_id">
          <input
            style={inputStyle}
            value={value.storage_id}
            onChange={(e) => {
              onChange({ ...value, storage_id: e.target.value });
              onRename(e.target.value);
            }}
          />
        </Field>
        <Field label="stored flow" meta="flow_id">
          <div style={{ minWidth: 130 }}>
            <SearchableSelect
              value={value.flow_id}
              options={flowIds}
              onChange={(v) => onChange({ ...value, flow_id: v })}
              onCreate={(name) => {
                onAddFlow(name);
                onChange({ ...value, flow_id: name });
              }}
              placeholder="flow to store"
            />
          </div>
        </Field>
        {numField("max capacity", "max_capacity", "max_capacity", 110)}
        {numField("capex /cap", "capex_per_capacity", "capex_per_capacity", 100)}
        {numField("fixed O&M /cap", "fixed_opex_per_capacity", "fixed_opex_per_capacity", 110)}
      </Row>
      <Row>
        {numField("charge eff", "charge_efficiency", "charge_efficiency", 80, "0.01")}
        {numField("discharge eff", "discharge_efficiency", "discharge_efficiency", 80, "0.01")}
        {numField("standing loss", "standing_loss", "standing_loss", 80, "0.001")}
        {numField("initial level", "initial_level", "initial_level", 90)}
      </Row>
      <h3 style={{ margin: "8px 0 6px", fontSize: "0.85rem" }}>
        Running energy <span className="muted">(optional — drawn per unit moved)</span>
      </h3>
      <Row>
        <Field label="energy flow" meta="energy_flow">
          <div style={{ minWidth: 130 }}>
            <SearchableSelect
              value={value.energy_flow ?? ""}
              options={flowIds}
              onChange={(v) => onChange({ ...value, energy_flow: v.trim() || null })}
              onCreate={(name) => {
                onAddFlow(name);
                onChange({ ...value, energy_flow: name });
              }}
              placeholder="none"
            />
          </div>
        </Field>
        {numField("energy /throughput", "energy_per_throughput", "energy_per_throughput", 110, "0.01")}
      </Row>
    </section>
  );
}

// ── Station ────────────────────────────────────────────────────────────────
export function StationEditor({
  value,
  flowIds,
  onAddFlow,
  onChange,
  onRename,
}: {
  value: StationTemplate;
  flowIds: string[];
  onAddFlow: (id: string) => void;
  onChange: (v: StationTemplate) => void;
  onRename: (id: string) => void;
}) {
  const numField = (label: string, key: keyof StationTemplate, width = 100) => (
    <Field label={label} meta={key as string}>
      <input
        style={{ ...inputStyle, width }}
        type="number"
        value={(value[key] as number) ?? 0}
        onChange={(e) => onChange({ ...value, [key]: num(e.target.value) })}
      />
    </Field>
  );
  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>Station <span className="muted" style={{ fontSize: "0.8rem" }}>(refuelling)</span></h2>
      <Row>
        <Field label="id" meta="station_id">
          <input
            style={inputStyle}
            value={value.station_id}
            onChange={(e) => {
              onChange({ ...value, station_id: e.target.value });
              onRename(e.target.value);
            }}
          />
        </Field>
        <Field label="dispensed fuel" meta="refuel_flow">
          <div style={{ minWidth: 130 }}>
            <SearchableSelect
              value={value.refuel_flow}
              options={flowIds}
              onChange={(v) => onChange({ ...value, refuel_flow: v })}
              onCreate={(name) => {
                onAddFlow(name);
                onChange({ ...value, refuel_flow: name });
              }}
              placeholder="fuel flow"
            />
          </div>
        </Field>
        {numField("refuel capacity", "refuel_capacity", 110)}
        {numField("refuel fee /unit", "refuel_fee", 100)}
      </Row>
      <Row>
        {numField("capex", "capex", 100)}
        {numField("fixed O&M", "fixed_opex", 100)}
      </Row>
    </section>
  );
}

/** Per-role wide-sheet field holding each io target's by-year coefficient. */
const IO_TFIELD = {
  input: "input_intensity_by_year",
  output: "output_yield_by_year",
  impact: "direct_impact_by_year",
} as const;

export function TechnologyEditor({
  value,
  flowIds,
  onAddFlow,
  onChange,
  onRename,
  unitOptions = [],
  streamUnitOf,
  baseYear = 2025,
  periods,
}: {
  value: TechnologyTemplate;
  flowIds: string[];
  onAddFlow: (id: string) => void;
  onChange: (v: TechnologyTemplate) => void;
  onRename: (id: string) => void;
  /** Allowed units (from GET /api/units) offered in each row's unit picker. */
  unitOptions?: string[];
  /** Resolves a flow's canonical unit — the default shown when a row is blank. */
  streamUnitOf?: (id: string) => string | undefined;
  /** Horizon context for the inline temporal editors. */
  baseYear?: number;
  periods?: number[];
}) {
  const setIo = (i: number, patch: Partial<IoRow>) =>
    onChange({ ...value, io: value.io.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const addIo = () => onChange({ ...value, io: [...value.io, { target: "", role: "input", coefficient: 1 }] });
  const delIo = (i: number) => onChange({ ...value, io: value.io.filter((_, j) => j !== i) });
  // A target's per-year coefficient lives in the role's wide map keyed by target.
  const ioByYear = (r: IoRow): ByYear | undefined => (value[IO_TFIELD[r.role]] ?? {})[r.target];
  const setIoCoeff = (i: number, r: IoRow, scalar: number, by: ByYear | undefined) => {
    const field = IO_TFIELD[r.role];
    const map = { ...(value[field] ?? {}) };
    if (by && Object.keys(by).length && r.target) map[r.target] = by;
    else delete map[r.target];
    onChange({
      ...value,
      io: value.io.map((x, j) => (j === i ? { ...x, coefficient: scalar } : x)),
      [field]: map,
    });
  };

  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>Technology (recipe)</h2>
      <Row>
        <Field label="id" meta="technology_id">
          <input
            style={inputStyle}
            value={value.technology_id}
            onChange={(e) => {
              onChange({ ...value, technology_id: e.target.value });
              onRename(e.target.value);
            }}
          />
        </Field>
        <Field label="lifespan (yr)" meta="lifespan">
          <input style={{ ...inputStyle, width: 90 }} type="number" value={value.lifespan} onChange={(e) => onChange({ ...value, lifespan: num(e.target.value) })} />
        </Field>
        <Field label="capex /cap" meta="capex">
          <TemporalField scalar={value.capex} byYear={value.capex_by_year} baseYear={baseYear} periods={periods}
            label={`${value.technology_id} · capex`}
            onChange={(s, by) => onChange({ ...value, capex: s, capex_by_year: by })} />
        </Field>
        <Field label="opex /unit" meta="opex">
          <TemporalField scalar={value.opex} byYear={value.opex_by_year} baseYear={baseYear} periods={periods}
            label={`${value.technology_id} · opex`}
            onChange={(s, by) => onChange({ ...value, opex: s, opex_by_year: by })} />
        </Field>
        <Field label="available from" meta="introduction_year">
          <input style={{ ...inputStyle, width: 90 }} type="number" placeholder="any" value={value.introduction_year ?? ""}
            onChange={(e) => onChange({ ...value, introduction_year: e.target.value === "" ? null : Math.round(num(e.target.value)) })} />
        </Field>
        <Field label="available to" meta="phase_out_year">
          <input style={{ ...inputStyle, width: 90 }} type="number" placeholder="any" value={value.phase_out_year ?? ""}
            onChange={(e) => onChange({ ...value, phase_out_year: e.target.value === "" ? null : Math.round(num(e.target.value)) })} />
        </Field>
      </Row>

      <h3 style={{ margin: "8px 0 6px", fontSize: "0.85rem" }}>
        Flows <span className="muted">(inputs · outputs · impacts)</span>
        <button className="ghost" style={{ marginLeft: 8 }} onClick={addIo}>
          ＋ add flow
        </button>
      </h3>
      <table className="grid" style={{ width: "100%", fontSize: "0.78rem" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--muted)" }}>
            <Th label="target" meta="target" width="26%" />
            <Th label="role" meta="role" />
            <Th label="coef" meta="coefficient" />
            <Th label="unit" meta="coefficient_unit" />
            <Th label="product?" meta="is_product" />
            <Th label="blend group" meta="group" />
            <Th label="min" meta="share_min" />
            <Th label="max" meta="share_max" />
            <th />
          </tr>
        </thead>
        <tbody>
          {value.io.map((r, i) => (
            <tr key={i}>
              <td>
                <SearchableSelect
                  value={r.target}
                  options={flowIds}
                  onChange={(v) => setIo(i, { target: v })}
                  onCreate={
                    r.role === "impact"
                      ? (name) => setIo(i, { target: name })
                      : (name) => {
                          onAddFlow(name);
                          setIo(i, { target: name });
                        }
                  }
                  placeholder={r.role === "impact" ? "impact id" : "flow"}
                />
              </td>
              <td>
                <SearchSelect value={r.role} onChange={(v) => setIo(i, { role: v as IoRow["role"] })}
                  options={[{ value: "input" }, { value: "output" }, { value: "impact" }]} />
              </td>
              <td>
                <TemporalField scalar={r.coefficient} byYear={ioByYear(r)} baseYear={baseYear} periods={periods}
                  label={`${value.technology_id} · ${r.target || r.role} coefficient`}
                  onChange={(s, by) => setIoCoeff(i, r, s, by)} />
              </td>
              <td style={{ minWidth: 84 }}>
                <SearchableSelect
                  value={r.unit ?? ""}
                  options={[...new Set([r.unit ?? "", ...unitOptions].filter(Boolean))]}
                  onChange={(v) => setIo(i, { unit: v.trim() || null })}
                  placeholder={streamUnitOf?.(r.target) || "flow unit"}
                />
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
                <input style={{ ...inputStyle, width: 56 }} type="number" min={0} max={1} value={r.share_min ?? ""} onChange={(e) => setIo(i, { share_min: e.target.value === "" ? null : num(e.target.value) })} />
              </td>
              <td>
                <input style={{ ...inputStyle, width: 56 }} type="number" min={0} max={1} value={r.share_max ?? ""} onChange={(e) => setIo(i, { share_max: e.target.value === "" ? null : num(e.target.value) })} />
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
      {value.io.length === 0 && <p className="muted" style={{ fontSize: "0.78rem" }}>No flows yet — a technology needs at least one product output.</p>}
      <RecipePreview ioRows={value.io} unitOf={streamUnitOf} />
    </section>
  );
}

// ── Asset (facility) + MACC measures ────────────────────────────────────────
export function AssetEditor({
  value,
  techIds,
  flowIds,
  embeddedTech,
  onChange,
  onRename,
}: {
  value: AssetComponent;
  techIds: string[];
  flowIds: string[];
  /** Optional inline recipe editor for the asset's technology (1:1 feel). */
  embeddedTech?: React.ReactNode;
  onChange: (v: AssetComponent) => void;
  onRename: (id: string) => void;
}) {
  const setLever = (i: number, patch: Partial<LeverTemplate>) =>
    onChange({ ...value, measures: value.measures.map((m, j) => (j === i ? { ...m, ...patch } : m)) });
  const addLever = () =>
    onChange({
      ...value,
      measures: [
        ...value.measures,
        {
          lever_id: `lever_${value.measures.length + 1}`,
          label: "",
          type: "energy_efficiency",
          target: flowIds[0] ?? "",
          lifetime: 15,
          blocks: [{ reduction: 0.05, capex_per_capacity: 0, opex_per_capacity: 0 }],
        },
      ],
    });
  const delLever = (i: number) => onChange({ ...value, measures: value.measures.filter((_, j) => j !== i) });

  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>Asset (facility)</h2>
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
        Levers <span className="muted">(MACC retrofits of this asset)</span>
        <button className="ghost" style={{ marginLeft: 8 }} onClick={addLever}>
          ＋ add lever
        </button>
      </h3>
      {value.measures.map((m, i) => (
        <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 4, padding: 10, marginBottom: 8 }}>
          <Row>
            <Field label="id">
              <input style={inputStyle} value={m.lever_id} onChange={(e) => setLever(i, { lever_id: e.target.value })} />
            </Field>
            <Field label="label">
              <input style={inputStyle} value={m.label} onChange={(e) => setLever(i, { label: e.target.value })} />
            </Field>
            <Field label="type">
              <SearchSelect value={m.type} onChange={(v) => setLever(i, { type: v as LeverTemplate["type"] })}
                options={[{ value: "energy_efficiency" }, { value: "emission_reduction" }, { value: "environmental" }]} />
            </Field>
            <Field label="target">
              <div style={{ minWidth: 140 }}>
                <SearchableSelect value={m.target} options={flowIds} onChange={(v) => setLever(i, { target: v })} onCreate={(name) => setLever(i, { target: name })} placeholder="flow / impact" />
              </div>
            </Field>
            <Field label="lifetime">
              <input style={{ ...inputStyle, width: 70 }} type="number" value={m.lifetime} onChange={(e) => setLever(i, { lifetime: num(e.target.value) })} />
            </Field>
            <button className="ghost" style={{ alignSelf: "flex-end" }} onClick={() => delLever(i)} title="remove lever">
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
                    <input style={{ ...inputStyle, width: 70 }} type="number" step="0.01" value={b.reduction} onChange={(e) => setLever(i, { blocks: m.blocks.map((x, j) => (j === bi ? { ...x, reduction: num(e.target.value) } : x)) })} />
                  </td>
                  <td>
                    <input style={{ ...inputStyle, width: 90 }} type="number" value={b.capex_per_capacity} onChange={(e) => setLever(i, { blocks: m.blocks.map((x, j) => (j === bi ? { ...x, capex_per_capacity: num(e.target.value) } : x)) })} />
                  </td>
                  <td>
                    <input style={{ ...inputStyle, width: 90 }} type="number" value={b.opex_per_capacity} onChange={(e) => setLever(i, { blocks: m.blocks.map((x, j) => (j === bi ? { ...x, opex_per_capacity: num(e.target.value) } : x)) })} />
                  </td>
                  <td>
                    <button className="ghost" onClick={() => setLever(i, { blocks: m.blocks.filter((_, j) => j !== bi) })} title="remove block">
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="ghost" style={{ marginTop: 4 }} onClick={() => setLever(i, { blocks: [...m.blocks, { reduction: 0.02, capex_per_capacity: 0, opex_per_capacity: 0 }] })}>
            ＋ add block
          </button>
        </div>
      ))}
      {value.measures.length === 0 && <p className="muted" style={{ fontSize: "0.78rem" }}>No levers — this asset has no MACC retrofits.</p>}
    </section>
  );
}

// ── Standalone lever (reusable) ───────────────────────────────────────────────
export function LeverEditor({
  value,
  flowIds,
  onChange,
  onRename,
  baseYear = 2025,
  periods,
}: {
  value: LeverTemplate;
  flowIds: string[];
  onChange: (v: LeverTemplate) => void;
  onRename: (id: string) => void;
  /** Horizon context for the inline temporal block-cost editors. */
  baseYear?: number;
  periods?: number[];
}) {
  const setBlock = (bi: number, patch: Partial<LeverTemplate["blocks"][number]>) =>
    onChange({ ...value, blocks: value.blocks.map((x, j) => (j === bi ? { ...x, ...patch } : x)) });
  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>Lever <span className="muted" style={{ fontSize: "0.8rem" }}>(reusable)</span></h2>
      <Row>
        <Field label="id" meta="lever_id">
          <input style={inputStyle} value={value.lever_id} onChange={(e) => { onChange({ ...value, lever_id: e.target.value }); onRename(e.target.value); }} />
        </Field>
        <Field label="label" meta="label">
          <input style={inputStyle} value={value.label} onChange={(e) => onChange({ ...value, label: e.target.value })} />
        </Field>
        <Field label="type" meta="lever_type">
          <SearchSelect value={value.type} onChange={(v) => onChange({ ...value, type: v as LeverTemplate["type"] })}
            options={[{ value: "energy_efficiency" }, { value: "emission_reduction" }, { value: "environmental" }]} />
        </Field>
        <Field label="target" meta="target">
          <div style={{ minWidth: 150 }}>
            <SearchableSelect value={value.target} options={flowIds} onChange={(v) => onChange({ ...value, target: v })} onCreate={(name) => onChange({ ...value, target: name })} placeholder="flow / impact" />
          </div>
        </Field>
        <Field label="lifetime" meta="lifetime">
          <input style={{ ...inputStyle, width: 70 }} type="number" value={value.lifetime} onChange={(e) => onChange({ ...value, lifetime: num(e.target.value) })} />
        </Field>
      </Row>
      <h3 style={{ margin: "8px 0 6px", fontSize: "0.85rem" }}>
        Cost curve <span className="muted">(piecewise blocks)</span>
        <button className="ghost" style={{ marginLeft: 8 }} onClick={() => onChange({ ...value, blocks: [...value.blocks, { reduction: 0.02, capex_per_capacity: 0, opex_per_capacity: 0 }] })}>＋ add block</button>
      </h3>
      <table className="grid" style={{ fontSize: "0.78rem" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--muted)" }}><th>block</th><Th label="reduction" meta="reduction" /><Th label="capex /cap" meta="capex_per_capacity" /><Th label="opex /cap" meta="opex_per_capacity" /><th /></tr>
        </thead>
        <tbody>
          {value.blocks.map((b, bi) => (
            <tr key={bi}>
              <td className="muted">{bi}</td>
              <td><input style={{ ...inputStyle, width: 70 }} type="number" step="0.01" value={b.reduction} onChange={(e) => onChange({ ...value, blocks: value.blocks.map((x, j) => (j === bi ? { ...x, reduction: num(e.target.value) } : x)) })} /></td>
              <td><TemporalField scalar={b.capex_per_capacity} byYear={b.capex_per_capacity_by_year} baseYear={baseYear} periods={periods}
                label={`${value.lever_id} · block ${bi} capex`}
                onChange={(s, by) => setBlock(bi, { capex_per_capacity: s, capex_per_capacity_by_year: by })} /></td>
              <td><TemporalField scalar={b.opex_per_capacity} byYear={b.opex_per_capacity_by_year} baseYear={baseYear} periods={periods}
                label={`${value.lever_id} · block ${bi} opex`}
                onChange={(s, by) => setBlock(bi, { opex_per_capacity: s, opex_per_capacity_by_year: by })} /></td>
              <td><button className="ghost" onClick={() => onChange({ ...value, blocks: value.blocks.filter((_, j) => j !== bi) })}>✕</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {value.blocks.length === 0 && <p className="muted" style={{ fontSize: "0.78rem" }}>No blocks — a lever needs at least one cost-curve step.</p>}
    </section>
  );
}

// ── MACC (a group/bundle of levers) ───────────────────────────────────────────
// A marginal-abatement-cost curve: one bar per lever block, width ∝ the
// reduction it delivers, height ∝ its marginal cost (capex per unit reduced),
// sorted cheapest-first. Negative-cost ("no-regret") blocks sit below the axis.
export function MaccChart({ measures }: { measures: LeverTemplate[] }) {
  const blocks = measures
    .flatMap((m) =>
      m.blocks.map((b) => ({
        name: m.label || m.lever_id,
        width: b.reduction,
        cost: b.reduction > 0 ? b.capex_per_capacity / b.reduction : 0,
      })),
    )
    .filter((b) => b.width > 0)
    .sort((a, b) => a.cost - b.cost);
  if (blocks.length === 0)
    return <p className="muted" style={{ fontSize: "0.78rem" }}>Bundle levers (with blocks) to see the MACC curve.</p>;

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
  /** All standalone levers available to bundle. */
  measures: { id: string; label: string }[];
  /** Full templates (for the MACC chart). */
  allMeasures: LeverTemplate[];
  onChange: (v: MaccGroup) => void;
  onRename: (id: string) => void;
}) {
  const toggle = (mid: string, on: boolean) =>
    onChange({ ...value, measures: on ? [...value.measures, mid] : value.measures.filter((m) => m !== mid) });
  const bundled = allMeasures.filter((m) => value.measures.includes(m.lever_id));
  return (
    <section>
      <h2 style={{ margin: "0 0 12px" }}>MACC <span className="muted" style={{ fontSize: "0.8rem" }}>(group of levers)</span></h2>
      <Row>
        <Field label="id" meta="macc_id">
          <input style={inputStyle} value={value.macc_id} onChange={(e) => { onChange({ ...value, macc_id: e.target.value }); onRename(e.target.value); }} />
        </Field>
        <Field label="label" meta="label">
          <input style={inputStyle} value={value.label} onChange={(e) => onChange({ ...value, label: e.target.value })} />
        </Field>
      </Row>
      <h3 style={{ margin: "8px 0 6px", fontSize: "0.85rem" }}>MACC curve</h3>
      <MaccChart measures={bundled} />
      <h3 style={{ margin: "12px 0 6px", fontSize: "0.85rem" }}>Levers in this MACC</h3>
      {measures.length === 0 && <p className="muted" style={{ fontSize: "0.78rem" }}>No levers yet — add individual levers first.</p>}
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
  flowIds,
  onChange,
  onRename,
}: {
  value: GroupComponent;
  componentNames: string[];
  flowIds: string[];
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
              <SearchableSelect value={c.component} options={componentNames} onChange={(v) => onChange({ ...value, children: value.children.map((x, j) => (j === i ? { ...x, component: v } : x)) })} hint="build a asset/group first" />
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
        Links <span className="muted">(internal wiring — e.g. GT → ST on steam)</span>
        <button className="ghost" style={{ marginLeft: 8 }} disabled={value.children.length < 2} onClick={() => onChange({ ...value, links: [...value.links, { source: aliases[0] ?? "", target: aliases[1] ?? "", flow: flowIds[0] ?? "", lag_years: 0 }] })}>
          ＋ add link
        </button>
      </h3>
      {value.links.map((cn, i) => (
        <Row key={i}>
          <Field label="from">
            <SearchSelect value={cn.source} onChange={(v) => onChange({ ...value, links: value.links.map((x, j) => (j === i ? { ...x, source: v } : x)) })}
              options={aliases.map((a) => ({ value: a }))} />
          </Field>
          <Field label="to">
            <SearchSelect value={cn.target} onChange={(v) => onChange({ ...value, links: value.links.map((x, j) => (j === i ? { ...x, target: v } : x)) })}
              options={aliases.map((a) => ({ value: a }))} />
          </Field>
          <Field label="flow">
            <SearchSelect value={cn.flow} onChange={(v) => onChange({ ...value, links: value.links.map((x, j) => (j === i ? { ...x, flow: v } : x)) })}
              options={flowIds.map((a) => ({ value: a }))} />
          </Field>
          <Field label="lag (yr)">
            <input style={{ ...inputStyle, width: 64 }} type="number" value={cn.lag_years} onChange={(e) => onChange({ ...value, links: value.links.map((x, j) => (j === i ? { ...x, lag_years: num(e.target.value) } : x)) })} />
          </Field>
          <button className="ghost" style={{ alignSelf: "flex-end" }} onClick={() => onChange({ ...value, links: value.links.filter((_, j) => j !== i) })}>✕</button>
        </Row>
      ))}
    </section>
  );
}
