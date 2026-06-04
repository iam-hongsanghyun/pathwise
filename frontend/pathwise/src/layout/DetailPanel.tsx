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
