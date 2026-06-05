import { optionsFor } from "../graph/references";
import type { Cell, Selection, Workbook } from "../types";

type SchemaMap = Record<
  string,
  { label?: string; columns?: Record<string, { label?: string; type?: string }> }
>;

interface Props {
  workbook: Workbook;
  selected: Selection;
  schema: SchemaMap;
  onChange: (wb: Workbook) => void;
  onClose: () => void;
  floating?: boolean;
}

function coerce(value: string): Cell {
  if (value === "") return null;
  if (value === "true") return true;
  if (value === "false") return false;
  const n = Number(value);
  return Number.isNaN(n) || value.trim() === "" ? value : n;
}

/** A commodity owns its emission factors: consuming `factor` per unit becomes
 *  real emission at the facility (emission = consumption × factor). Edited here
 *  as a commodity attribute (stored in the commodity_impacts sheet). */
function EmissionFactors({
  workbook,
  commodity,
  onChange,
}: {
  workbook: Workbook;
  commodity: string;
  onChange: (wb: Workbook) => void;
}) {
  const rows = workbook.commodity_impacts ?? [];
  const impacts = (workbook.impacts ?? []).map((r) => String(r.impact_id ?? "")).filter(Boolean);
  const mine = rows
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => String(r.commodity_id ?? "") === commodity);

  const setFactor = (idx: number, val: string) =>
    onChange({
      ...workbook,
      commodity_impacts: rows.map((r, i) =>
        i === idx ? { ...r, factor: val === "" ? null : Number(val) } : r,
      ),
    });
  const setImpact = (idx: number, val: string) =>
    onChange({
      ...workbook,
      commodity_impacts: rows.map((r, i) => (i === idx ? { ...r, impact_id: val } : r)),
    });
  const add = () =>
    onChange({
      ...workbook,
      commodity_impacts: [...rows, { commodity_id: commodity, impact_id: impacts[0] ?? "", factor: 0 }],
    });
  const del = (idx: number) =>
    onChange({ ...workbook, commodity_impacts: rows.filter((_, i) => i !== idx) });

  return (
    <div className="emission-factors">
      <div className="rail-count" style={{ marginTop: 8 }}>EMISSION FACTORS (per unit consumed)</div>
      {mine.map(({ r, i }) => (
        <div key={i} className="ef-row">
          <select value={String(r.impact_id ?? "")} onChange={(e) => setImpact(i, e.target.value)}>
            <option value="">—</option>
            {impacts.map((imp) => (
              <option key={imp} value={imp}>
                {imp}
              </option>
            ))}
          </select>
          <input
            value={r.factor == null ? "" : String(r.factor)}
            onChange={(e) => setFactor(i, e.target.value)}
          />
          <button className="ghost" onClick={() => del(i)} title="remove">
            ✕
          </button>
        </div>
      ))}
      <button className="ghost" onClick={add}>
        + factor
      </button>
    </div>
  );
}

/** A technology owns its I/O: inputs (streams it consumes), outputs (what it
 *  makes), and impacts (direct emissions). Edited here as part of the technology
 *  — there is no separate I/O table. Stored in the `io` sheet. */
function TechnologyIO({
  workbook,
  technology,
  onChange,
}: {
  workbook: Workbook;
  technology: string;
  onChange: (wb: Workbook) => void;
}) {
  const io = workbook.io ?? [];
  const streams = (workbook.commodities ?? []).map((r) => String(r.commodity_id ?? "")).filter(Boolean);
  const impacts = (workbook.impacts ?? []).map((r) => String(r.impact_id ?? "")).filter(Boolean);
  const mine = io.map((r, i) => ({ r, i })).filter(({ r }) => String(r.technology_id ?? "") === technology);

  const set = (idx: number, key: string, val: Cell) =>
    onChange({ ...workbook, io: io.map((r, i) => (i === idx ? { ...r, [key]: val } : r)) });
  const del = (idx: number) => onChange({ ...workbook, io: io.filter((_, i) => i !== idx) });
  const add = (role: "input" | "output" | "impact") =>
    onChange({
      ...workbook,
      io: [...io, { technology_id: technology, target: "", role, coefficient: role === "impact" ? 0 : 1 }],
    });

  const Section = ({ role, label }: { role: string; label: string }) => {
    const opts = role === "impact" ? impacts : streams;
    return (
      <>
        <div className="rail-count" style={{ marginTop: 6 }}>{label}</div>
        {mine
          .filter(({ r }) => String(r.role ?? "input") === role)
          .map(({ r, i }) => (
            <div key={i} className="ef-row">
              <select value={String(r.target ?? "")} onChange={(e) => set(i, "target", e.target.value)}>
                <option value="">—</option>
                {opts.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
              <input
                value={r.coefficient == null ? "" : String(r.coefficient)}
                title="per unit throughput (intensity = input ÷ output)"
                onChange={(e) => set(i, "coefficient", e.target.value === "" ? null : Number(e.target.value))}
              />
              <button className="ghost" onClick={() => del(i)} title="remove">
                ✕
              </button>
            </div>
          ))}
      </>
    );
  };

  return (
    <div className="emission-factors">
      <div className="rail-count" style={{ marginTop: 8 }}>TECHNOLOGY I/O (per unit throughput)</div>
      <Section role="input" label="inputs (consumes)" />
      <Section role="output" label="outputs (produces)" />
      <Section role="impact" label="direct impacts (emits)" />
      <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
        <button className="ghost" onClick={() => add("input")}>+ input</button>
        <button className="ghost" onClick={() => add("output")}>+ output</button>
        <button className="ghost" onClick={() => add("impact")}>+ impact</button>
      </div>
    </div>
  );
}

/** Detail editor for one entity — rendered in the main panel (Data) or as a
 *  floating card on the canvas (Model). Replaces the old right-rail inspector. */
export function DetailPanel({ workbook, selected, schema, onChange, onClose, floating }: Props) {
  const rows = workbook[selected.sheet] ?? [];
  const idx = rows.findIndex((r) => String(r[selected.idCol] ?? "") === selected.id);
  const row = idx >= 0 ? rows[idx] : undefined;
  const cols = Object.keys(schema[selected.sheet]?.columns ?? {});
  const allCols = [...new Set([...cols, ...(row ? Object.keys(row) : [])])];
  const labelOf = (c: string) => schema[selected.sheet]?.columns?.[c]?.label ?? c;

  const edit = (col: string, value: string) =>
    onChange({
      ...workbook,
      [selected.sheet]: rows.map((r, i) => (i === idx ? { ...r, [col]: coerce(value) } : r)),
    });

  // Promote a static attribute to a wide temporal table column for this item.
  const makeTemporal = (col: string) => {
    const tsheet = `${selected.sheet}_t__${col}`;
    const years = [...new Set((workbook.periods ?? []).map((r) => Number(r.year)))].sort((a, b) => a - b);
    const byYear = new Map((workbook[tsheet] ?? []).map((r) => [Number(r.year), r]));
    const base = row && typeof row[col] === "number" ? (row[col] as number) : 0;
    const trows = years.map((y) => {
      const ex = byYear.get(y) ?? { year: y };
      return { ...ex, [selected.id]: (ex[selected.id] as number) ?? base };
    });
    onChange({ ...workbook, [tsheet]: trows });
  };
  // Any numeric attribute can be promoted to a per-year time series — no
  // hardcoded whitelist (the `<sheet>_t__<attr>` table is created on demand).
  const numericType = (col: string) => {
    const t = schema[selected.sheet]?.columns?.[col]?.type;
    return t === "number" || t === "integer";
  };
  const canTemporal = (col: string) =>
    col !== selected.idCol &&
    col !== "year" &&
    (numericType(col) || (row != null && typeof row[col] === "number"));
  const remove = () => {
    onChange({ ...workbook, [selected.sheet]: rows.filter((_, i) => i !== idx) });
    onClose();
  };

  return (
    <div className={`detail-panel${floating ? " floating" : ""}`}>
      <div className="detail-head">
        <div>
          <strong>{selected.id}</strong> <span className="rail-count">{selected.sheet}</span>
        </div>
        <button className="ghost" onClick={onClose} title="close">
          ✕
        </button>
      </div>
      {row ? (
        <div className="inspector-form">
          {allCols.map((c) => {
            const opts = c === selected.idCol ? null : optionsFor(workbook, selected.sheet, c, row);
            const value = row[c] == null ? "" : String(row[c]);
            return (
              <label key={c} className="inspector-field">
                <span>
                  {labelOf(c)}
                  {canTemporal(c) && (
                    <button
                      className="make-temporal"
                      title="make this value vary by year (temporal)"
                      onClick={(e) => {
                        e.preventDefault();
                        makeTemporal(c);
                      }}
                    >
                      ⟳ temporal
                    </button>
                  )}
                </span>
                {opts ? (
                  <select value={value} onChange={(e) => edit(c, e.target.value)}>
                    <option value="">—</option>
                    {opts.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input value={value} onChange={(e) => edit(c, e.target.value)} />
                )}
              </label>
            );
          })}
          {selected.sheet === "commodities" && (
            <EmissionFactors workbook={workbook} commodity={selected.id} onChange={onChange} />
          )}
          {selected.sheet === "technologies" && (
            <TechnologyIO workbook={workbook} technology={selected.id} onChange={onChange} />
          )}
          <button className="ghost" onClick={remove}>
            Delete
          </button>
        </div>
      ) : (
        <div className="muted" style={{ padding: "8px 0" }}>
          Row not found.
        </div>
      )}
    </div>
  );
}
