import { DRAG_MIME, nodeId, type NodeKind } from "../graph/model";
import type { Selection, Workbook } from "../types";

/** Entity sheets (id column) expand into clickable items; the placeable ones
 *  are draggable onto the Model canvas. */
const ENTITY: Record<string, { idCol: string; kind?: NodeKind }> = {
  processes: { idCol: "process_id", kind: "process" },
  commodities: { idCol: "commodity_id", kind: "commodity" },
  markets: { idCol: "market_id", kind: "market" },
  storage: { idCol: "storage_id", kind: "storage" },
  technologies: { idCol: "technology_id" },
  measures: { idCol: "measure_id" },
  impacts: { idCol: "impact_id" },
};

/** Preferred ordering; any other workbook sheets follow. */
const ORDER = [
  "processes",
  "commodities",
  "markets",
  "storage",
  "technologies",
  "measures",
  "impacts",
  "periods",
  "process_inputs",
  "process_outputs",
  "tech_impacts",
  "commodity_impacts",
  "edges",
  "measure_blocks",
  "transitions",
  "demand",
  "min_production",
  "impact_caps",
  "impact_prices",
  "commodity_prices",
  "market_prices",
  "investment_budget",
  "company_config",
];

const LABEL: Record<string, string> = {
  processes: "Facilities",
  commodities: "Streams",
  markets: "Markets",
  storage: "Storage",
  technologies: "Technologies",
  measures: "Measures",
  impacts: "Impacts",
};

interface Props {
  workbook: Workbook;
  selected: Selection | null;
  activeSheet: string;
  onGroup?: (sheet: string) => void;
  onItem: (s: Selection) => void;
  draggable?: boolean;
  width?: number;
}

/** Left rail — the single navigator: every sheet is a group (click → table in
 *  main); entity sheets expand to items (click → detail in main). */
export function LeftRail({ workbook, selected, activeSheet, onGroup, onItem, draggable, width }: Props) {
  const placed = new Set((workbook.node_layout ?? []).map((r) => String(r.id)));
  const sheets = [
    ...ORDER.filter((s) => s in workbook),
    ...Object.keys(workbook).filter((s) => s !== "node_layout" && s !== "meta" && !ORDER.includes(s)),
  ];

  return (
    <aside
      className="left-rail"
      aria-label="Model tree"
      style={width ? { width, flex: `0 0 ${width}px` } : undefined}
    >
      {sheets.map((sheet) => {
        const rows = workbook[sheet] ?? [];
        const ent = ENTITY[sheet];
        const groupActive = activeSheet === sheet && !selected ? " is-active" : "";
        return (
          <div className="rail-group" key={sheet}>
            <button className={`rail-head${groupActive}`} onClick={() => onGroup?.(sheet)}>
              {LABEL[sheet] ?? sheet} <span className="rail-count">{rows.length}</span>
            </button>
            {ent &&
              rows.map((r, i) => {
                const id = String(r[ent.idCol] ?? "");
                if (!id) return null;
                const active =
                  selected?.sheet === sheet && selected.id === id ? " is-active" : "";
                const isTech = sheet === "technologies";
                const canDrag = Boolean(draggable && (ent.kind || isTech));
                const payload = ent.kind ? nodeId(ent.kind, id) : `tech:${id}`;
                const onMap = ent.kind && placed.has(nodeId(ent.kind, id));
                return (
                  <button
                    key={`${id}-${i}`}
                    className={`rail-item${active}`}
                    draggable={canDrag}
                    onDragStart={
                      canDrag
                        ? (e) => {
                            e.dataTransfer.setData(DRAG_MIME, payload);
                            e.dataTransfer.effectAllowed = "copy";
                          }
                        : undefined
                    }
                    onClick={() => onItem({ sheet, idCol: ent.idCol, id })}
                    title={canDrag ? `${id} — drag onto the canvas` : id}
                  >
                    {onMap ? "● " : canDrag ? "○ " : ""}
                    {id}
                  </button>
                );
              })}
          </div>
        );
      })}
    </aside>
  );
}
