import { optionsFor } from "../graph/references";
import type { Cell, Selection, Workbook } from "../types";

type SchemaMap = Record<string, { label?: string; columns?: Record<string, { label?: string }> }>;

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
                <span>{labelOf(c)}</span>
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
