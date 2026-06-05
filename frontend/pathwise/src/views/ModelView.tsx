import { useState } from "react";
import { DetailPanel } from "../layout/DetailPanel";
import { LeftRail } from "../layout/LeftRail";
import { Resizer } from "../layout/Resizer";
import { FlowCanvas } from "../components/designer/FlowCanvas";
import { WorkbookTable } from "../components/WorkbookTable";
import type { Cell, ConfigBundle, Row, Selection, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  config: ConfigBundle | null;
  leftW: number;
  setLeftW: (w: number) => void;
}

const ID_COL: Record<string, string> = {
  processes: "process_id",
  commodities: "commodity_id",
  markets: "market_id",
  storage: "storage_id",
  technologies: "technology_id",
  measures: "measure_id",
  impacts: "impact_id",
};

const coerce = (v: string): Cell =>
  v === "" ? null : Number.isNaN(Number(v)) || v.trim() === "" ? v : Number(v);

/** Bottom dock when an item is selected: ALL the time series this item owns
 *  (`<sheet>_t__<attr>` columns named after the item) in ONE table — a `year`
 *  row index with one editable column per temporal attribute. */
function ItemTimeSeries({
  workbook,
  selected,
  onChange,
}: {
  workbook: Workbook;
  selected: Selection;
  onChange: (wb: Workbook) => void;
}) {
  const sheets = Object.keys(workbook).filter(
    (k) => k.startsWith(`${selected.sheet}_t__`) && (workbook[k] ?? []).some((r) => selected.id in r),
  );
  if (!sheets.length) {
    return (
      <div className="muted" style={{ padding: "8px 4px" }}>
        No time series for <strong>{selected.id}</strong>. In the panel on the right, click
        <em> ⟳ temporal</em> on any value to make it vary by year.
      </div>
    );
  }
  const attrOf = (ts: string) => ts.split("_t__")[1];
  const years = [
    ...new Set(sheets.flatMap((ts) => (workbook[ts] ?? []).map((r) => Number(r.year)))),
  ].sort((a, b) => a - b);
  const valueAt = (ts: string, year: number) => {
    const row = (workbook[ts] ?? []).find((r) => Number(r.year) === year);
    return row && row[selected.id] != null ? String(row[selected.id]) : "";
  };
  const editCell = (ts: string, year: number, value: string) =>
    onChange({
      ...workbook,
      [ts]: (workbook[ts] ?? []).map((r) =>
        Number(r.year) === year ? { ...r, [selected.id]: coerce(value) } : r,
      ),
    });
  return (
    <div className="table-wrap" style={{ maxWidth: 640 }}>
      <table>
        <thead>
          <tr>
            <th>year</th>
            {sheets.map((ts) => (
              <th key={ts}>{attrOf(ts)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {years.map((y) => (
            <tr key={y}>
              <td>{y}</td>
              {sheets.map((ts) => (
                <td key={ts}>
                  <input value={valueAt(ts, y)} onChange={(e) => editCell(ts, y, e.target.value)} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Model view — the single editing surface. Canvas (top) + the selected item's
 *  STATIC values in the right rail and its TIME SERIES in the bottom dock, shown
 *  together; selecting a group/temporal in the tree shows its table in the dock. */
export function ModelView({ workbook, setWorkbook, config, leftW, setLeftW }: Props) {
  const [selected, setSelected] = useState<Selection | null>(null);
  const [activeSheet, setActiveSheet] = useState<string | null>(null);
  const schema = config?.domains[0]?.schema ?? {};

  const openItem = (s: Selection) => {
    setSelected(s);
    setActiveSheet(null);
  };
  const openGroup = (s: string) => {
    setActiveSheet(s);
    setSelected(null);
  };
  const closeDock = () => {
    setSelected(null);
    setActiveSheet(null);
  };

  const toggle = (sheet: string, idCol: string, id: string, enabled: boolean) =>
    setWorkbook({
      ...workbook,
      [sheet]: (workbook[sheet] ?? []).map((r) =>
        String(r[idCol] ?? "") === id ? { ...r, enabled } : r,
      ),
    });

  const addRow = (sheet: string) => {
    const idCol = ID_COL[sheet] ?? "id";
    const rows = workbook[sheet] ?? [];
    const base = `new_${sheet.replace(/s$/, "")}`;
    let k = rows.length + 1;
    let id = `${base}_${k}`;
    const taken = new Set(rows.map((r) => String(r[idCol] ?? "")));
    while (taken.has(id)) id = `${base}_${++k}`;
    const blank: Row = { [idCol]: id };
    setWorkbook({ ...workbook, [sheet]: [...rows, blank] });
    openItem({ sheet, idCol, id });
  };

  const dockOpen = selected != null || activeSheet != null;

  return (
    <div className="body-row">
      <LeftRail
        workbook={workbook}
        selected={selected}
        activeSheet={activeSheet ?? ""}
        onItem={openItem}
        onGroup={openGroup}
        onToggle={toggle}
        onAdd={addRow}
        draggable
        width={leftW}
      />
      <Resizer width={leftW} setWidth={setLeftW} side="left" />
      <main className="main-area">
        <div className="model-banner">
          Drag a component (or a technology → new facility) onto the canvas; drag a node handle to
          another to connect. Select an item to edit its static values (right) and time series (below).
        </div>
        <div className="canvas-pane">
          <FlowCanvas workbook={workbook} onChange={setWorkbook} onSelect={openItem} />
        </div>
        {dockOpen && (
          <div className="editor-dock">
            <div className="dock-head">
              <strong>{selected ? selected.id : activeSheet}</strong>
              <span className="rail-count">{selected ? "time series" : "table"}</span>
              <span className="spacer" />
              <button className="ghost" onClick={closeDock} title="close editor">
                ✕
              </button>
            </div>
            <div className="dock-body">
              {selected ? (
                <ItemTimeSeries workbook={workbook} selected={selected} onChange={setWorkbook} />
              ) : (
                activeSheet && (
                  <WorkbookTable
                    rows={workbook[activeSheet] ?? []}
                    onChange={(rows) => setWorkbook({ ...workbook, [activeSheet]: rows })}
                  />
                )
              )}
            </div>
          </div>
        )}
      </main>
      {selected && (
        <aside className="right-rail" aria-label="Static values">
          <DetailPanel
            workbook={workbook}
            selected={selected}
            schema={schema}
            onChange={setWorkbook}
            onClose={() => setSelected(null)}
          />
        </aside>
      )}
    </div>
  );
}
