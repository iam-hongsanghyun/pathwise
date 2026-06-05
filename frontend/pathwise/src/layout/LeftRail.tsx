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
  const baselineTechs = new Set(
    (workbook.processes ?? []).map((r) => String(r.baseline_technology ?? "")),
  );
  const targetTechs = new Set((workbook.transitions ?? []).map((r) => String(r.to_technology ?? "")));
  const all = Object.keys(workbook).filter((s) => s !== "node_layout" && s !== "meta");
  const staticSheets = [
    ...ORDER.filter((s) => s in workbook),
    ...all.filter((s) => !ORDER.includes(s) && !s.includes("_t__")),
  ];
  const temporalSheets = all.filter((s) => s.includes("_t__"));

  const temporalFor = (sheet: string, id: string): { ts: string; attr: string }[] =>
    temporalSheets
      .filter((ts) => ts.startsWith(`${sheet}_t__`))
      .filter((ts) => (workbook[ts] ?? []).some((r) => id in r))
      .map((ts) => ({ ts, attr: ts.split("_t__")[1] }));

  const renderGroup = (sheet: string) => {
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
            const sel = selected?.sheet === sheet && selected.id === id ? " is-active" : "";
            const isTech = sheet === "technologies";
            const canDrag = Boolean(draggable && (ent.kind || isTech));
            const payload = ent.kind ? nodeId(ent.kind, id) : `tech:${id}`;
            // Status dot: ● active (placed / baseline tech), ○ alternative (tech
            // that's a transition target but not a baseline).
            let dot = "";
            if (ent.kind && placed.has(nodeId(ent.kind, id))) dot = "dot-active";
            else if (isTech && baselineTechs.has(id)) dot = "dot-active";
            else if (isTech && targetTechs.has(id)) dot = "dot-alt";
            else if (canDrag) dot = "dot-avail";
            return (
              <button
                key={`${id}-${i}`}
                className={`rail-item${sel}`}
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
                title={
                  dot === "dot-alt" ? `${id} — alternative technology` : canDrag ? `${id} — drag onto the canvas` : id
                }
              >
                {dot && <span className={`dot ${dot}`} />}
                {id}
              </button>
            );
          })}
        {/* Temporal datasets nested under each component (static lives in detail). */}
        {ent &&
          rows.flatMap((r) => {
            const id = String(r[ent.idCol] ?? "");
            return id
              ? temporalFor(sheet, id).map(({ ts, attr }) => (
                  <button
                    key={`${id}-${attr}`}
                    className="rail-subitem"
                    onClick={() => onGroup?.(ts)}
                    title={`${id} · ${attr} (temporal)`}
                  >
                    ↳ {id} · {attr}
                  </button>
                ))
              : [];
          })}
      </div>
    );
  };

  return (
    <aside
      className="left-rail"
      aria-label="Model tree"
      style={width ? { width, flex: `0 0 ${width}px` } : undefined}
    >
      {staticSheets.map(renderGroup)}
      {temporalSheets.length > 0 && (
        <>
          <div className="rail-section">Temporal datasets</div>
          {temporalSheets.map(renderGroup)}
        </>
      )}
    </aside>
  );
}
