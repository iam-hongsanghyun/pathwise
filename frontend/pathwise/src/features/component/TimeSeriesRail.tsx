// Per-year time-series editor for the selected component. The user CHOOSES which
// attributes vary over time (for a technology, each recipe coefficient / emission,
// not just capex/opex); each chosen attribute is an editable line chart (x = year)
// where clicking a point edits its value inline.

import { useState } from "react";
import { SearchSelect } from "../controls/SearchSelect";
import { YearSeriesChart } from "./YearSeriesChart";
import type {
  ByYear,
  CommodityTemplate,
  LeverTemplate,
  TechnologyTemplate,
} from "../../lib/api/components";

interface Series {
  key: string;
  label: string;
  metaKey?: string;
  values: ByYear;
  /** Scalar value a newly-added year is prefilled with. */
  fallback: number;
}

// Renders each chosen series as its own editable line chart (x = year); click a
// point to edit its value inline. `toolbar` carries the attribute picker (tech).
function TimeSeriesTable({
  title,
  hint,
  series,
  onChange,
  toolbar,
}: {
  title: string;
  hint?: string;
  series: Series[];
  onChange: (updates: Record<string, ByYear>) => void;
  /** Optional controls (e.g. the attribute picker) rendered beside the title. */
  toolbar?: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
        <strong style={{ fontSize: "0.8rem" }}>{title}</strong>
        {toolbar}
        {hint && <span className="muted" style={{ fontSize: "0.72rem" }}>{hint}</span>}
      </div>
      {series.length === 0 ? (
        <p className="muted" style={{ fontSize: "0.74rem", margin: "2px 0" }}>
          Pick an attribute above to vary it over time.
        </p>
      ) : (
        series.map((s) => (
          <YearSeriesChart
            key={s.key}
            label={s.label}
            values={s.values}
            fallback={s.fallback}
            onChange={(by) => onChange({ [s.key]: by })}
          />
        ))
      )}
    </div>
  );
}

// ── Technology: cost + every recipe coefficient / emission, user-selectable ────

const IO_FIELD = {
  in: "input_intensity_by_year",
  out: "output_yield_by_year",
  imp: "direct_impact_by_year",
} as const;
type IoRole = keyof typeof IO_FIELD;

function TechTimeSeries({ value, onChange }: { value: TechnologyTemplate; onChange: (v: TechnologyTemplate) => void }) {
  // Every attribute that COULD vary by year: the two costs + each io coefficient.
  const candidates: Series[] = [
    { key: "cap", label: "capex /cap", metaKey: "capex", values: value.capex_by_year ?? {}, fallback: value.capex },
    { key: "opx", label: "opex /unit", metaKey: "opex", values: value.opex_by_year ?? {}, fallback: value.opex },
  ];
  for (const r of value.io) {
    const role: IoRole = r.role === "output" ? "out" : r.role === "impact" ? "imp" : "in";
    candidates.push({
      key: `${role}:${r.target}`,
      label: `${r.target} (${r.role})`,
      metaKey: "coefficient",
      values: (value[IO_FIELD[role]] ?? {})[r.target] ?? {},
      fallback: r.coefficient,
    });
  }

  // Active = has values, OR the user added it this session (an empty column to fill).
  const [added, setAdded] = useState<Set<string>>(new Set());
  const isActive = (s: Series) => Object.keys(s.values).length > 0 || added.has(s.key);
  const active = candidates.filter(isActive);
  const inactive = candidates.filter((s) => !isActive(s));

  const writeKey = (next: TechnologyTemplate, key: string, byYear: ByYear): TechnologyTemplate => {
    if (key === "cap") return { ...next, capex_by_year: byYear };
    if (key === "opx") return { ...next, opex_by_year: byYear };
    const i = key.indexOf(":");
    const field = IO_FIELD[key.slice(0, i) as IoRole];
    const target = key.slice(i + 1);
    const map = { ...(next[field] ?? {}) };
    if (Object.keys(byYear).length === 0) delete map[target];
    else map[target] = byYear;
    return { ...next, [field]: map };
  };
  const apply = (updates: Record<string, ByYear>) => {
    let next = value;
    for (const [key, byYear] of Object.entries(updates)) next = writeKey(next, key, byYear);
    onChange(next);
  };
  const remove = (key: string) => {
    setAdded((p) => { const n = new Set(p); n.delete(key); return n; });
    onChange(writeKey(value, key, {})); // clear its overrides
  };

  return (
    <TimeSeriesTable
      title="By year"
      hint="overrides the scalar for the chosen attributes"
      series={active}
      onChange={apply}
      toolbar={
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {active.map((s) => (
            <span key={s.key} className="chip" style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: "0.7rem", padding: "1px 6px", border: "1px solid var(--border-strong)", borderRadius: "var(--radius-pill)" }}>
              {s.label}
              <button className="ghost" title="stop varying this" style={{ padding: 0, lineHeight: 1 }} onClick={() => remove(s.key)}>✕</button>
            </span>
          ))}
          {inactive.length > 0 && (
            <span style={{ minWidth: 150 }}>
              <SearchSelect
                value=""
                onChange={(k) => k && setAdded((p) => new Set(p).add(k))}
                options={inactive.map((s) => ({ value: s.key, label: s.label }))}
                placeholder="＋ add attribute…"
              />
            </span>
          )}
        </span>
      }
    />
  );
}

type RailProps =
  | { kind: "tech"; value: TechnologyTemplate; onChange: (v: TechnologyTemplate) => void }
  | { kind: "stream"; value: CommodityTemplate; onChange: (v: CommodityTemplate) => void }
  | { kind: "lever"; value: LeverTemplate; onChange: (v: LeverTemplate) => void };

/** Per-year editor for the selected single item's trajectories. */
export function TimeSeriesRail(p: RailProps) {
  if (p.kind === "tech") return <TechTimeSeries value={p.value} onChange={p.onChange} />;
  if (p.kind === "lever") {
    // lever — one table per block (block cost is per-capacity, scaled at placement)
    const m = p.value;
    const setBlock = (bi: number, patch: Partial<LeverTemplate["blocks"][number]>) =>
      p.onChange({ ...m, blocks: m.blocks.map((b, j) => (j === bi ? { ...b, ...patch } : b)) });
    return (
      <>
        {m.blocks.length === 0 && <p className="muted" style={{ fontSize: "0.74rem" }}>No cost-curve blocks yet.</p>}
        {m.blocks.map((b, bi) => (
          <TimeSeriesTable
            key={bi}
            title={`Block ${bi} cost by year`}
            hint={`reduction ${b.reduction}`}
            series={[
              { key: "capex", label: "capex /cap", metaKey: "capex_per_capacity", values: b.capex_per_capacity_by_year ?? {}, fallback: b.capex_per_capacity },
              { key: "opex", label: "opex /cap", metaKey: "opex_per_capacity", values: b.opex_per_capacity_by_year ?? {}, fallback: b.opex_per_capacity },
            ]}
            onChange={(u) =>
              setBlock(bi, {
                ...("capex" in u ? { capex_per_capacity_by_year: u.capex } : {}),
                ...("opex" in u ? { opex_per_capacity_by_year: u.opex } : {}),
              })
            }
          />
        ))}
      </>
    );
  }
  if (p.kind === "stream") {
    const c = p.value;
    return (
      <TimeSeriesTable
        title="Price by year"
        hint="overrides the scalar price / sale price"
        series={[
          { key: "price", label: "price", metaKey: "price", values: c.price_by_year ?? {}, fallback: c.price ?? 0 },
          { key: "sale_price", label: "sale price", metaKey: "sale_price", values: c.sale_price_by_year ?? {}, fallback: c.sale_price ?? 0 },
        ]}
        onChange={(u) =>
          p.onChange({
            ...c,
            ...("price" in u ? { price_by_year: u.price } : {}),
            ...("sale_price" in u ? { sale_price_by_year: u.sale_price } : {}),
          })
        }
      />
    );
  }
  return null;
}
