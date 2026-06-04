import { DRAG_MIME, nodeId, type NodeKind } from "../graph/model";
import type { Selection, Workbook } from "../types";

interface Group {
  label: string;
  sheet: string;
  idCol: string;
  kind?: NodeKind; // placeable on the map (draggable) when set
}

const GROUPS: Group[] = [
  { label: "Facilities", sheet: "processes", idCol: "process_id", kind: "process" },
  { label: "Streams", sheet: "commodities", idCol: "commodity_id", kind: "commodity" },
  { label: "Markets", sheet: "markets", idCol: "market_id", kind: "market" },
  { label: "Storage", sheet: "storage", idCol: "storage_id", kind: "storage" },
  { label: "Technologies", sheet: "technologies", idCol: "technology_id" },
  { label: "Measures", sheet: "measures", idCol: "measure_id" },
  { label: "Impacts", sheet: "impacts", idCol: "impact_id" },
];

interface Props {
  workbook: Workbook;
  selected: Selection | null;
  onSelect: (s: Selection) => void;
  /** When true (Model view), placeable items are draggable onto the canvas. */
  draggable?: boolean;
  width?: number;
}

/** Left rail — grouped model tree. Click to select; in the Model view, drag a
 *  facility/stream/market/storage onto the canvas to place it. */
export function LeftRail({ workbook, selected, onSelect, draggable, width }: Props) {
  const placed = new Set((workbook.node_layout ?? []).map((r) => String(r.id)));
  return (
    <aside
      className="left-rail"
      aria-label="Model tree"
      style={width ? { width, flex: `0 0 ${width}px` } : undefined}
    >
      {GROUPS.map((g) => {
        const rows = workbook[g.sheet] ?? [];
        return (
          <div className="rail-group" key={g.sheet}>
            <h4>
              {g.label} <span className="rail-count">{rows.length}</span>
            </h4>
            {rows.map((r, i) => {
              const id = String(r[g.idCol] ?? "");
              if (!id) return null;
              const active = selected?.sheet === g.sheet && selected.id === id ? " is-active" : "";
              const canDrag = Boolean(draggable && g.kind);
              const onMap = g.kind && placed.has(nodeId(g.kind, id));
              return (
                <button
                  key={`${id}-${i}`}
                  className={`rail-item${active}`}
                  draggable={canDrag}
                  onDragStart={
                    canDrag
                      ? (e) => {
                          e.dataTransfer.setData(DRAG_MIME, nodeId(g.kind as NodeKind, id));
                          e.dataTransfer.effectAllowed = "copy";
                        }
                      : undefined
                  }
                  onClick={() => onSelect({ sheet: g.sheet, idCol: g.idCol, id })}
                  title={canDrag ? `${id} — drag onto the canvas` : id}
                >
                  {onMap ? "● " : canDrag ? "○ " : ""}
                  {id}
                </button>
              );
            })}
            {rows.length === 0 && <div className="rail-empty muted">—</div>}
          </div>
        );
      })}
    </aside>
  );
}
