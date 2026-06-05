import { useState } from "react";
import { DetailPanel } from "../layout/DetailPanel";
import { LeftRail } from "../layout/LeftRail";
import { Resizer } from "../layout/Resizer";
import { FlowCanvas } from "../components/designer/FlowCanvas";
import { WorkbookTable } from "../components/WorkbookTable";
import type { ConfigBundle, Row, Selection, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  config: ConfigBundle | null;
  leftW: number;
  setLeftW: (w: number) => void;
}

/** Id column per entity sheet — used when adding a row from the `+` button. */
const ID_COL: Record<string, string> = {
  processes: "process_id",
  commodities: "commodity_id",
  markets: "market_id",
  storage: "storage_id",
  technologies: "technology_id",
  measures: "measure_id",
  impacts: "impact_id",
};

/** Model view — the SINGLE editing surface (folds in the old Data view). The
 *  process map shows the initial system; the left tree navigates every
 *  component, and the bottom dock edits whatever is selected — a group/temporal
 *  table or one item's detail. Drag a component (or a technology → new facility)
 *  onto the canvas; the optimiser transitions/upgrades/outsources from here. */
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
    let n = rows.length + 1;
    let id = `${base}_${n}`;
    const taken = new Set(rows.map((r) => String(r[idCol] ?? "")));
    while (taken.has(id)) id = `${base}_${++n}`;
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
          Initial system · drag a component (or a technology → new facility) onto the canvas. Click a
          group / ↳temporal in the tree to edit its table, or an item for its detail — below.
        </div>
        <div className="canvas-pane">
          <FlowCanvas workbook={workbook} onChange={setWorkbook} onSelect={openItem} />
        </div>
        {dockOpen && (
          <div className="editor-dock">
            <div className="dock-head">
              <strong>{selected ? selected.id : activeSheet}</strong>
              <span className="rail-count">{selected ? selected.sheet : "table"}</span>
              <span className="spacer" />
              <button className="ghost" onClick={closeDock} title="close editor">
                ✕
              </button>
            </div>
            <div className="dock-body">
              {selected ? (
                <DetailPanel
                  workbook={workbook}
                  selected={selected}
                  schema={schema}
                  onChange={setWorkbook}
                  onClose={closeDock}
                />
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
    </div>
  );
}
