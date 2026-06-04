import { useState } from "react";
import { DetailPanel } from "../layout/DetailPanel";
import { LeftRail } from "../layout/LeftRail";
import { Resizer } from "../layout/Resizer";
import { WorkbookTable } from "../components/WorkbookTable";
import type { ConfigBundle, Selection, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  config: ConfigBundle | null;
  leftW: number;
  setLeftW: (w: number) => void;
}

/** Data view — the editable tables. Left tree picks a sheet (table) or an item
 *  (detail editor); the main panel shows whichever is selected. */
export function DataView({ workbook, setWorkbook, config, leftW, setLeftW }: Props) {
  const [activeSheet, setActiveSheet] = useState("processes");
  const [selected, setSelected] = useState<Selection | null>(null);
  const schema = config?.domains[0]?.schema ?? {};

  return (
    <div className="body-row">
      <LeftRail
        workbook={workbook}
        selected={selected}
        activeSheet={activeSheet}
        onGroup={(s) => {
          setActiveSheet(s);
          setSelected(null);
        }}
        onItem={(s) => {
          setActiveSheet(s.sheet);
          setSelected(s);
        }}
        width={leftW}
      />
      <Resizer width={leftW} setWidth={setLeftW} side="left" />
      <main className="main-area">
        <div className="view">
          {selected ? (
            <DetailPanel
              workbook={workbook}
              selected={selected}
              schema={schema}
              onChange={setWorkbook}
              onClose={() => setSelected(null)}
            />
          ) : (
            <WorkbookTable
              rows={workbook[activeSheet] ?? []}
              onChange={(rows) => setWorkbook({ ...workbook, [activeSheet]: rows })}
            />
          )}
        </div>
      </main>
    </div>
  );
}
