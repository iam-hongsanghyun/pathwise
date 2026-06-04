import type { Row } from "../types";

interface Props {
  sheet: string;
  rows: Row[];
  onChange: (rows: Row[]) => void;
  maxRows?: number;
}

/** A simple editable grid for one workbook sheet (plain HTML inputs). */
export function WorkbookTable({ sheet, rows, onChange, maxRows = 50 }: Props) {
  if (rows.length === 0) {
    return (
      <div className="muted">
        <em>{sheet}</em> is empty.
      </div>
    );
  }
  const columns = Object.keys(rows[0]);
  const shown = rows.slice(0, maxRows);

  const edit = (rowIdx: number, col: string, value: string) => {
    const next = rows.map((r, i) => (i === rowIdx ? { ...r, [col]: coerce(value) } : r));
    onChange(next);
  };

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c}>
                  <input
                    value={row[c] == null ? "" : String(row[c])}
                    onChange={(e) => edit(i, c, e.target.value)}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > maxRows && <div className="muted">… {rows.length - maxRows} more rows</div>}
    </div>
  );
}

/** Coerce an input string back to number/boolean/null where it round-trips cleanly. */
function coerce(value: string): unknown {
  if (value === "") return null;
  if (value === "true") return true;
  if (value === "false") return false;
  const num = Number(value);
  return Number.isNaN(num) || value.trim() === "" ? value : num;
}
