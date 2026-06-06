import { useState } from "react";
import { DetailPanel } from "../layout/DetailPanel";
import { LeftRail } from "../layout/LeftRail";
import { Resizer } from "../layout/Resizer";
import { FlowCanvas } from "../components/designer/FlowCanvas";
import { SimpleView } from "../components/SimpleView";
import { FlowView } from "../components/FlowView";
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
  // Remove this item's temporal series: drop its column from the sheet; if no
  // other item uses the sheet, drop the sheet. The static value (right) remains.
  const removeSeries = (ts: string) => {
    const stripped = (workbook[ts] ?? []).map((r) => {
      const { [selected.id]: _drop, ...rest } = r;
      return rest;
    });
    const stillUsed = stripped.some((r) => Object.keys(r).some((k) => k !== "year"));
    const next = { ...workbook };
    if (stillUsed) next[ts] = stripped;
    else delete next[ts];
    onChange(next);
  };
  return (
    <div className="table-wrap" style={{ maxWidth: 640 }}>
      <table>
        <thead>
          <tr>
            <th>year</th>
            {sheets.map((ts) => (
              <th key={ts}>
                {attrOf(ts)}{" "}
                <button
                  className="ghost ts-del"
                  title={`remove the ${attrOf(ts)} time series (revert to static)`}
                  onClick={() => removeSeries(ts)}
                >
                  ✕
                </button>
              </th>
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
  const [mode, setMode] = useState<"canvas" | "simple" | "flow">("canvas");
  const [rightW, setRightW] = useState(300);
  const [dockH, setDockH] = useState(260);
  const schema = config?.domains[0]?.schema ?? {};

  // Table columns = schema columns ∪ keys present in the rows, so optional
  // columns (e.g. impact_caps `intensity` / `soft` / `penalty`) are always
  // editable even when the rows don't yet carry them.
  const columnsFor = (sheet: string): string[] | undefined => {
    const schemaCols = Object.keys(
      (schema as Record<string, { columns?: Record<string, unknown> }>)[sheet]?.columns ?? {},
    );
    if (!schemaCols.length) return undefined;
    const rowCols = new Set((workbook[sheet] ?? []).flatMap((r) => Object.keys(r)));
    return [...new Set([...schemaCols, ...rowCols])];
  };

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

  const toggleAll = (sheet: string, _idCol: string, enabled: boolean) =>
    setWorkbook({
      ...workbook,
      [sheet]: (workbook[sheet] ?? []).map((r) => ({ ...r, enabled })),
    });

  const toggleIds = (sheet: string, idCol: string, ids: string[], enabled: boolean) => {
    const set = new Set(ids);
    setWorkbook({
      ...workbook,
      [sheet]: (workbook[sheet] ?? []).map((r) =>
        set.has(String(r[idCol] ?? "")) ? { ...r, enabled } : r,
      ),
    });
  };

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
        onToggleAll={toggleAll}
        onToggleIds={toggleIds}
        onAdd={addRow}
        draggable
        width={leftW}
      />
      <Resizer width={leftW} setWidth={setLeftW} side="left" />
      <main className="main-area">
        <div className="model-banner">
          <div className="view-toggle">
            {(["canvas", "simple", "flow"] as const).map((m) => (
              <button key={m} className={`tab${mode === m ? " active" : ""}`} onClick={() => setMode(m)}>
                {m[0].toUpperCase() + m.slice(1)}
              </button>
            ))}
          </div>
          {mode === "canvas" &&
            "Drag a component onto the canvas; drag a node handle to another to connect. Click an item to edit."}
          {mode === "simple" &&
            "Inputs → facilities → outputs. Drag a section's corner to resize; click an item to edit."}
          {mode === "flow" &&
            "Process route by stage (● current · ○ alternative). Toggle aggregated / per-facility; click a technology to edit."}
        </div>
        <div className="canvas-pane">
          {mode === "canvas" && <FlowCanvas workbook={workbook} onChange={setWorkbook} onSelect={openItem} />}
          {mode === "simple" && <SimpleView workbook={workbook} onSelect={openItem} />}
          {mode === "flow" && <FlowView workbook={workbook} onSelect={openItem} />}
        </div>
        {dockOpen && (
          <div className="editor-dock" style={{ flex: `0 0 ${dockH}px` }}>
            <Resizer width={dockH} setWidth={setDockH} side="top" min={80} max={700} />
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
                    columns={columnsFor(activeSheet)}
                    onChange={(rows) => setWorkbook({ ...workbook, [activeSheet]: rows })}
                  />
                )
              )}
            </div>
          </div>
        )}
      </main>
      {selected && (
        <>
          <Resizer width={rightW} setWidth={setRightW} side="right" min={200} max={600} />
          <aside
            className="right-rail"
            aria-label="Static values"
            style={{ width: rightW, flex: `0 0 ${rightW}px` }}
          >
            <DetailPanel
              workbook={workbook}
              selected={selected}
              schema={schema}
              onChange={setWorkbook}
              onClose={() => setSelected(null)}
            />
          </aside>
        </>
      )}
    </div>
  );
}
