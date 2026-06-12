import { useState } from "react";
import {
  emptyHint,
  measureLinkedViaSet,
  optionsFor,
  refTargets,
  type RefTarget,
} from "../../lib/references";
import type { Cell, Row, Workbook } from "../../types";
import { AppliesToPicker } from "../controls/AppliesToPicker";
import { CreateComponentModal, type SchemaMap } from "../controls/CreateComponentModal";
import { InfoTip } from "../controls/InfoTip";
import { SearchableSelect } from "../controls/SearchableSelect";

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
  /** Full schema + whole-workbook updater — enables creating a missing
   *  component (on another sheet) straight from a reference dropdown. */
  schema?: SchemaMap;
  onWorkbook?: (wb: Workbook) => void;
}

/** Editable grid for one workbook sheet: required columns first (bold), the
 *  rest grey; reference columns are searchable dropdowns of existing
 *  components — typing a new name offers to create the component on the spot
 *  (Save) or keep just the name for later (Cancel, shown red until it exists). */
export function WorkbookTable({
  rows,
  columns,
  onChange,
  maxRows = 200,
  workbook,
  sheet,
  columnMeta,
  schema,
  onWorkbook,
}: Props) {
  const [creating, setCreating] = useState<{
    i: number;
    c: string;
    name: string;
    targets: RefTarget[];
  } | null>(null);
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
    // applies_to gets explicit facility + technology pickers (one must be
    // chosen unless a measure is reached through a linked MACC set).
    if (workbook && sheet && (sheet === "measures" || sheet === "measure_links") && c === "applies_to") {
      const canCreate = Boolean(schema && onWorkbook);
      return (
        <AppliesToPicker
          value={value}
          workbook={workbook}
          onChange={(v) => edit(i, c, v)}
          missingIsOk={sheet === "measures" && measureLinkedViaSet(workbook, row)}
          onCreateFacility={
            canCreate
              ? (name) =>
                  setCreating({
                    i,
                    c,
                    name,
                    targets: [{ sheet: "processes", idCol: "process_id", label: "facility" }],
                  })
              : undefined
          }
          onCreateTechnology={
            canCreate
              ? (name) =>
                  setCreating({
                    i,
                    c,
                    name,
                    targets: [{ sheet: "technologies", idCol: "technology_id", label: "technology" }],
                  })
              : undefined
          }
        />
      );
    }
    const opts = workbook && sheet ? optionsFor(workbook, sheet, c, row) : null;
    if (opts) {
      const targets = workbook && sheet ? refTargets(sheet, c, row) : [];
      const canCreate = targets.length > 0 && Boolean(schema && onWorkbook);
      return (
        <SearchableSelect
          value={value}
          options={opts}
          broken={value !== "" && !opts.includes(value)}
          hint={sheet ? emptyHint(sheet, c) : undefined}
          onChange={(v) => edit(i, c, v)}
          onCreate={canCreate ? (name) => setCreating({ i, c, name, targets }) : undefined}
        />
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
                >
                  {meta(c).label ?? c}
                  {meta(c).desc ? (
                    <InfoTip
                      tip={`${meta(c).desc} ${meta(c).required ? "(required)" : "(optional)"}`}
                    />
                  ) : null}
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
      {creating && workbook && sheet && schema && onWorkbook && (
        <CreateComponentModal
          name={creating.name}
          targets={creating.targets}
          schema={schema}
          workbook={workbook}
          onSave={(tsheet, newRow) => {
            onWorkbook({
              ...workbook,
              [tsheet]: [...(workbook[tsheet] ?? []), newRow],
              [sheet]: rows.map((r, j) =>
                j === creating.i ? { ...r, [creating.c]: creating.name } : r,
              ),
            });
            setCreating(null);
          }}
          onCancel={() => {
            edit(creating.i, creating.c, creating.name);
            setCreating(null);
          }}
        />
      )}
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
