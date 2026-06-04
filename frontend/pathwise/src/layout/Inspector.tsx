import type { Cell, Row, Selection, Workbook } from "../types";

type SchemaMap = Record<string, { label?: string; columns?: Record<string, { label?: string }> }>;

interface Props {
  workbook: Workbook;
  selected: Selection | null;
  schema: SchemaMap;
  onChange: (wb: Workbook) => void;
  onClear: () => void;
}

function coerce(value: string): Cell {
  if (value === "") return null;
  if (value === "true") return true;
  if (value === "false") return false;
  const n = Number(value);
  return Number.isNaN(n) || value.trim() === "" ? value : n;
}

/** Right rail — edit the selected entity's properties (schema-labelled form). */
export function Inspector({ workbook, selected, schema, onChange, onClear }: Props) {
  if (!selected) {
    return (
      <aside className="right-rail" aria-label="Inspector">
        <div className="rail-group">
          <h4>Inspector</h4>
          <div className="muted" style={{ padding: "4px 12px" }}>
            Select a node in the tree or canvas to edit it.
          </div>
        </div>
      </aside>
    );
  }

  const rows = workbook[selected.sheet] ?? [];
  const idx = rows.findIndex((r) => String(r[selected.idCol] ?? "") === selected.id);
  const row: Row | undefined = idx >= 0 ? rows[idx] : undefined;
  const cols = Object.keys(schema[selected.sheet]?.columns ?? {});
  const allCols = [...new Set([...cols, ...(row ? Object.keys(row) : [])])];
  const labelOf = (c: string) => schema[selected.sheet]?.columns?.[c]?.label ?? c;

  const edit = (col: string, value: string) => {
    const next = rows.map((r, i) => (i === idx ? { ...r, [col]: coerce(value) } : r));
    onChange({ ...workbook, [selected.sheet]: next });
  };
  const remove = () => {
    onChange({ ...workbook, [selected.sheet]: rows.filter((_, i) => i !== idx) });
    onClear();
  };

  return (
    <aside className="right-rail" aria-label="Inspector">
      <div className="rail-group">
        <h4>
          {selected.id} <span className="rail-count">{selected.sheet}</span>
        </h4>
        {row ? (
          <div className="inspector-form">
            {allCols.map((c) => (
              <label key={c} className="inspector-field">
                <span>{labelOf(c)}</span>
                <input
                  value={row[c] == null ? "" : String(row[c])}
                  onChange={(e) => edit(c, e.target.value)}
                />
              </label>
            ))}
            <button className="ghost" onClick={remove}>
              Delete
            </button>
          </div>
        ) : (
          <div className="muted" style={{ padding: "4px 12px" }}>
            Row not found.
          </div>
        )}
      </div>
    </aside>
  );
}
