// Bottom rail of the Component builder: edit a single item's per-year cost
// trajectories in one combined table (year rows × cost columns). Empty = the
// scalar value applies every year; adding a year prefills the current scalar so
// the user only adjusts the years that differ. Edits flow back through onChange.

import { InfoTooltip } from "../controls/InfoTooltip";
import { fieldMeta } from "./fieldMeta";
import { inputStyle } from "./editors";
import type {
  ByYear,
  CommodityTemplate,
  MeasureTemplate,
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

function yearsOf(series: Series[]): number[] {
  const ys = new Set<number>();
  for (const s of series) for (const y of Object.keys(s.values)) if (Number.isFinite(Number(y))) ys.add(Number(y));
  return [...ys].sort((a, b) => a - b);
}

// onChange carries the new ByYear for EVERY series it touches, applied in one
// update — so adding/removing a year (which changes all columns at once) can't
// clobber a sibling column via stale state.
function TimeSeriesTable({
  title,
  hint,
  series,
  onChange,
}: {
  title: string;
  hint?: string;
  series: Series[];
  onChange: (updates: Record<string, ByYear>) => void;
}) {
  const years = yearsOf(series);
  const setCell = (s: Series, y: number, raw: string) => {
    const next: ByYear = { ...s.values };
    if (raw.trim() === "") delete next[String(y)];
    else next[String(y)] = Number(raw) || 0;
    onChange({ [s.key]: next });
  };
  const removeYear = (y: number) => {
    const updates: Record<string, ByYear> = {};
    for (const s of series) {
      const n: ByYear = { ...s.values };
      delete n[String(y)];
      updates[s.key] = n;
    }
    onChange(updates);
  };
  const addYear = () => {
    const last = years[years.length - 1];
    const y = last ? last + 5 : 2030;
    const updates: Record<string, ByYear> = {};
    for (const s of series) updates[s.key] = { ...s.values, [String(y)]: s.fallback };
    onChange(updates);
  };

  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <strong style={{ fontSize: "0.8rem" }}>{title}</strong>
        <button className="ghost" onClick={addYear}>＋ year</button>
        {hint && <span className="muted" style={{ fontSize: "0.72rem" }}>{hint}</span>}
      </div>
      {years.length === 0 ? (
        <p className="muted" style={{ fontSize: "0.74rem", margin: "2px 0" }}>
          No per-year overrides — the scalar value applies every year. Add a year to vary it over time.
        </p>
      ) : (
        <table className="grid" style={{ fontSize: "0.76rem" }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--muted)" }}>
              <th style={{ width: 70 }}>year</th>
              {series.map((s) => {
                const m = s.metaKey ? fieldMeta(s.metaKey) : undefined;
                return (
                  <th key={s.key}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                      {s.label}
                      {m?.info && <InfoTooltip text={m.info} unit={m.unit} />}
                    </span>
                  </th>
                );
              })}
              <th />
            </tr>
          </thead>
          <tbody>
            {years.map((y) => (
              <tr key={y}>
                <td className="muted">{y}</td>
                {series.map((s) => (
                  <td key={s.key}>
                    <input
                      style={{ ...inputStyle, width: 90 }}
                      type="number"
                      placeholder={String(s.fallback)}
                      value={s.values[String(y)] ?? ""}
                      onChange={(e) => setCell(s, y, e.target.value)}
                    />
                  </td>
                ))}
                <td>
                  <button className="ghost" title="remove this year" onClick={() => removeYear(y)}>✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

type RailProps =
  | { kind: "tech"; value: TechnologyTemplate; onChange: (v: TechnologyTemplate) => void }
  | { kind: "stream"; value: CommodityTemplate; onChange: (v: CommodityTemplate) => void }
  | { kind: "measure"; value: MeasureTemplate; onChange: (v: MeasureTemplate) => void };

/** Per-year editor for the selected single item's cost/price trajectories. */
export function TimeSeriesRail(p: RailProps) {
  if (p.kind === "tech") {
    const t = p.value;
    return (
      <TimeSeriesTable
        title="Cost by year"
        hint="overrides the scalar capex / opex"
        series={[
          { key: "capex", label: "capex /cap", metaKey: "capex", values: t.capex_by_year ?? {}, fallback: t.capex },
          { key: "opex", label: "opex /unit", metaKey: "opex", values: t.opex_by_year ?? {}, fallback: t.opex },
        ]}
        onChange={(u) =>
          p.onChange({
            ...t,
            ...("capex" in u ? { capex_by_year: u.capex } : {}),
            ...("opex" in u ? { opex_by_year: u.opex } : {}),
          })
        }
      />
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
  // measure — one table per block (block cost is per-capacity, scaled at placement)
  const m = p.value;
  const setBlock = (bi: number, patch: Partial<MeasureTemplate["blocks"][number]>) =>
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
