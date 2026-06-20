// A small column-driven editable table: rows are entities, columns describe how
// to read/write one field each. Used by the Component builder's bucket view so a
// user can edit many items' scalar fields side-by-side in the main panel. Cell
// edits return a fresh rows array via onChange (immutable). Number cells reuse
// the same empty→null idiom as the hand-written editors.

import { InfoTooltip } from "./InfoTooltip";
import { SearchSelect } from "./SearchSelect";
import { fieldMeta } from "../component/fieldMeta";

export interface Column<T> {
  key: string;
  label: string;
  /** Data key to source the (i) tooltip + unit from (see fieldMeta). */
  metaKey?: string;
  type?: "text" | "number" | "enum" | "readonly" | "boolean";
  options?: string[]; // for enum
  width?: number | string;
  /** number only: empty input → null instead of 0. */
  nullable?: boolean;
  /** number only: round to an integer. */
  integer?: boolean;
  get: (row: T) => string | number | boolean | null | undefined;
  /** Omitted for readonly columns. */
  set?: (row: T, value: string) => T;
  /** readonly only: click the cell (e.g. drill into the row's leaf). */
  onClick?: (row: T) => void;
}

const cellStyle: React.CSSProperties = {
  padding: "3px 5px",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-button)",
  background: "var(--surface)",
  font: "inherit",
  fontSize: "0.76rem",
};

export function DataTable<T>({
  rows,
  columns,
  onChange,
  rowKey,
  empty,
}: {
  rows: T[];
  columns: Column<T>[];
  onChange: (rows: T[]) => void;
  rowKey: (row: T) => string;
  empty?: string;
}) {
  const setCell = (i: number, col: Column<T>, raw: string) =>
    onChange(rows.map((r, j) => (j === i && col.set ? col.set(r, raw) : r)));

  if (rows.length === 0) return <p className="muted" style={{ fontSize: "0.78rem" }}>{empty ?? "Nothing here yet."}</p>;

  return (
    <table className="grid" style={{ width: "100%", fontSize: "0.76rem" }}>
      <thead>
        <tr style={{ textAlign: "left", color: "var(--muted)" }}>
          {columns.map((c) => {
            const m = c.metaKey ? fieldMeta(c.metaKey) : undefined;
            return (
              <th key={c.key} style={{ width: c.width }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                  {c.label}
                  {m?.info && <InfoTooltip text={m.info} unit={m.unit} />}
                </span>
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={rowKey(r)}>
            {columns.map((c) => {
              const v = c.get(r);
              if (c.type === "readonly")
                return (
                  <td key={c.key}>
                    {c.onClick ? (
                      <button className="link-cell" onClick={() => c.onClick?.(r)}>{v ?? ""}</button>
                    ) : (
                      <span>{v ?? ""}</span>
                    )}
                  </td>
                );
              if (c.type === "enum")
                return (
                  <td key={c.key}>
                    <SearchSelect value={String(v ?? "")} onChange={(nv) => setCell(i, c, nv)} options={(c.options ?? []).map((o) => ({ value: o }))} />
                  </td>
                );
              if (c.type === "boolean")
                return (
                  <td key={c.key} style={{ textAlign: "center" }}>
                    <input
                      type="checkbox"
                      checked={v === true || v === "true" || v === 1}
                      onChange={(e) => setCell(i, c, e.target.checked ? "true" : "")}
                    />
                  </td>
                );
              return (
                <td key={c.key}>
                  <input
                    style={{ ...cellStyle, width: c.type === "number" ? 88 : 120 }}
                    type={c.type === "number" ? "number" : "text"}
                    value={v == null || typeof v === "boolean" ? "" : v}
                    onChange={(e) => setCell(i, c, e.target.value)}
                  />
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
