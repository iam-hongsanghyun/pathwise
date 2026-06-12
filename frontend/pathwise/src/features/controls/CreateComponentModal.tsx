import { useState } from "react";
import { optionsFor, type RefTarget } from "../../lib/references";
import type { Cell, Row, Workbook } from "../../types";
import { SearchableSelect } from "./SearchableSelect";

export type SchemaMap = Record<
  string,
  { label?: string; columns?: Record<string, { label?: string; required?: boolean; desc?: string }> }
>;

interface Props {
  /** The id the user typed into a reference dropdown. */
  name: string;
  /** Candidate sheets the component could live on (facility OR technology…). */
  targets: RefTarget[];
  schema: SchemaMap;
  workbook: Workbook;
  /** Save → create the row on `sheet` (the caller also sets the reference). */
  onSave: (sheet: string, row: Row) => void;
  /** Cancel → no component; the caller just keeps the typed name (shown red
   *  until the component is added later). */
  onCancel: () => void;
}

function coerce(value: string): Cell {
  if (value === "") return null;
  if (value === "true") return true;
  if (value === "false") return false;
  const n = Number(value);
  return Number.isNaN(n) || value.trim() === "" ? value : n;
}

/** Popup to create the component a reference points at, right where it is
 *  first mentioned — Save adds the row, Cancel keeps just the name for later. */
export function CreateComponentModal({ name, targets, schema, workbook, onSave, onCancel }: Props) {
  const [target, setTarget] = useState<RefTarget>(targets[0]);
  const [row, setRow] = useState<Row>({});
  const meta = schema[target.sheet]?.columns ?? {};
  const cols = Object.keys(meta).filter((c) => c !== target.idCol);
  const ordered = [...cols.filter((c) => meta[c]?.required), ...cols.filter((c) => !meta[c]?.required)];
  const switchTarget = (t: RefTarget) => {
    setTarget(t);
    setRow({});
  };
  const set = (c: string, v: string) => setRow({ ...row, [c]: coerce(v) });

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="detail-head">
          <strong>
            Add “{name}” as a new {target.label}
          </strong>
          <button className="ghost" onClick={onCancel} title="cancel — keep just the name">
            ✕
          </button>
        </div>
        {targets.length > 1 && (
          <div className="view-toggle" style={{ marginBottom: 8 }}>
            {targets.map((t) => (
              <button
                key={t.sheet}
                className={`tab${t.sheet === target.sheet ? " active" : ""}`}
                onClick={() => switchTarget(t)}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
        <div className="inspector-form">
          {ordered.map((c) => {
            const m = meta[c] ?? {};
            const value = row[c] == null ? "" : String(row[c]);
            const opts = optionsFor(workbook, target.sheet, c, row);
            return (
              <label
                key={c}
                className={`inspector-field ${m.required ? "field-required" : "field-optional"}`}
              >
                <span>
                  {m.label ?? c}
                  {m.desc ? (
                    <span className="col-info" data-tip={m.desc}>
                      ⓘ
                    </span>
                  ) : null}
                </span>
                {opts ? (
                  <SearchableSelect value={value} options={opts} onChange={(v) => set(c, v)} />
                ) : (
                  <input value={value} onChange={(e) => set(c, e.target.value)} />
                )}
              </label>
            );
          })}
        </div>
        <div className="modal-actions">
          <button onClick={() => onSave(target.sheet, { [target.idCol]: name, ...row })}>
            Save {target.label}
          </button>
          <button className="ghost" onClick={onCancel}>
            Cancel (just keep the name)
          </button>
        </div>
      </div>
    </div>
  );
}
