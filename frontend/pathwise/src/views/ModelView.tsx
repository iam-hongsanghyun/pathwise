import { useState } from "react";
import { DetailPanel } from "../layout/DetailPanel";
import { LeftRail } from "../layout/LeftRail";
import { Resizer } from "../layout/Resizer";
import { FlowCanvas } from "../components/designer/FlowCanvas";
import type { ConfigBundle, Selection, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  config: ConfigBundle | null;
  leftW: number;
  setLeftW: (w: number) => void;
}

/** Model view — the INITIAL/current system on a process map. Drag components
 *  (incl. technologies → new facility) from the palette; the optimiser then
 *  transitions / upgrades / outsources from this baseline over the horizon. */
export function ModelView({ workbook, setWorkbook, config, leftW, setLeftW }: Props) {
  const [selected, setSelected] = useState<Selection | null>(null);
  const schema = config?.domains[0]?.schema ?? {};

  return (
    <div className="body-row">
      <LeftRail
        workbook={workbook}
        selected={selected}
        activeSheet=""
        onItem={setSelected}
        draggable
        width={leftW}
      />
      <Resizer width={leftW} setWidth={setLeftW} side="left" />
      <main className="main-area">
        <div className="model-banner">
          Initial system · drag a component (or a technology → new facility) onto the canvas; the
          optimiser transitions, upgrades, and outsources from here.
        </div>
        <FlowCanvas workbook={workbook} onChange={setWorkbook} onSelect={setSelected} />
        {selected && (
          <DetailPanel
            workbook={workbook}
            selected={selected}
            schema={schema}
            onChange={setWorkbook}
            onClose={() => setSelected(null)}
            floating
          />
        )}
      </main>
    </div>
  );
}
