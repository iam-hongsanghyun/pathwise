import { emptyHint, optionsFor } from "../../lib/references";
import type { Cell, Row, Workbook } from "../../types";

/** Per-column metadata from the domain schema (label, required, description). */
export interface ColumnMeta {
  label?: string;
  required?: boolean;
  desc?: string;
}

interface Props {
  rows: Row[];
  columns?: string[];
  onChange: (rows: Row[]) => void;
  maxRows?: number;
  /** Enables reference dropdowns (with `sheet`) and required/desc styling. */
  workbook?: Workbook;
  sheet?: string;
  columnMeta?: Record<string, ColumnMeta>;
}

/** Editable grid for one workbook sheet: required columns first (bold), the
 *  rest grey; reference columns render as dropdowns of existing components —
 *  an EMPTY dropdown tells the user what to add first instead of inviting a
 *  broken free-text id. */
export function WorkbookTable({
  rows,
  columns,
  onChange,
  maxRows = 200,
  workbook,
  sheet,
  columnMeta,
}: Props) {
  const raw = columns ?? (rows.length ? Object.keys(rows[0]) : []);
  // Required columns lead (left), optional follow — in schema order.
  const cols = columnMeta
    ? [...raw.filter((c) => columnMeta[c]?.required), ...raw.filter((c) => !columnMeta[c]?.required)]
    : raw;
  if (!cols.length) {
    return <div className="muted">No columns. Add a row to start.</div>;
  }

  const edit = (i: number, c: string, value: string) => {
    onChange(rows.map((r, j) => (j === i ? { ...r, [c]: coerce(value) } : r)));
  };
  const addRow = () => onChange([...rows, Object.fromEntries(cols.map((c) => [c, null]))]);
  const delRow = (i: number) => onChange(rows.filter((_, j) => j !== i));

  const meta = (c: string): ColumnMeta => columnMeta?.[c] ?? {};

  const cell = (row: Row, i: number, c: string) => {
    const value = row[c] == null ? "" : String(row[c]);
    const opts = workbook && sheet ? optionsFor(workbook, sheet, c, row) : null;
    if (opts) {
      if (!opts.length && sheet) {
        // No valid targets exist yet — a free-text id here would only break
        // the model; tell the user what to create first.
        return (
          <select disabled title={emptyHint(sheet, c)}>
            <option>— {emptyHint(sheet, c)} —</option>
          </select>
        );
      }
      return (
        <select value={value} onChange={(e) => edit(i, c, e.target.value)}>
          <option value="">—</option>
          {value && !opts.includes(value) && <option value={value}>{value} (unknown)</option>}
          {opts.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      );
    }
    return <input value={value} onChange={(e) => edit(i, c, e.target.value)} />;
  };

  return (
    <div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {cols.map((c) => (
                <th
                  key={c}
                  className={
                    columnMeta ? (meta(c).required ? "col-required" : "col-optional") : undefined
                  }
                  title={[meta(c).desc, meta(c).required ? "(required)" : "(optional)"]
                    .filter(Boolean)
                    .join(" — ")}
                >
                  {meta(c).label ?? c}
                  {meta(c).desc ? <span className="col-info"> ⓘ</span> : null}
                </th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, maxRows).map((row, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c}>{cell(row, i, c)}</td>
                ))}
                <td>
                  <button className="ghost" onClick={() => delRow(i)} title="delete row">
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button className="ghost" onClick={addRow}>
        + row
      </button>
      {rows.length > maxRows && <span className="muted"> … {rows.length - maxRows} more</span>}
    </div>
  );
}

function coerce(value: string): Cell {
  if (value === "") return null;
  if (value === "true") return true;
  if (value === "false") return false;
  const n = Number(value);
  return Number.isNaN(n) || value.trim() === "" ? value : n;
}
