import type { Cell, Row } from "../types";

interface Props {
  rows: Row[];
  columns?: string[];
  onChange: (rows: Row[]) => void;
  maxRows?: number;
}

/** Editable grid for one workbook sheet, with add/delete row. */
export function WorkbookTable({ rows, columns, onChange, maxRows = 200 }: Props) {
  const cols = columns ?? (rows.length ? Object.keys(rows[0]) : []);
  if (!cols.length) {
    return <div className="muted">No columns. Add a row to start.</div>;
  }

  const edit = (i: number, c: string, value: string) => {
    onChange(rows.map((r, j) => (j === i ? { ...r, [c]: coerce(value) } : r)));
  };
  const addRow = () => onChange([...rows, Object.fromEntries(cols.map((c) => [c, null]))]);
  const delRow = (i: number) => onChange(rows.filter((_, j) => j !== i));

  return (
    <div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c}>{c}</th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, maxRows).map((row, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c}>
                    <input
                      value={row[c] == null ? "" : String(row[c])}
                      onChange={(e) => edit(i, c, e.target.value)}
                    />
                  </td>
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
