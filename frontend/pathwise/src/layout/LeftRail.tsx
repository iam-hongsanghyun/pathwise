import { useState } from "react";
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

/** Sheets whose rows carry an `enabled` flag (left-rail include checkbox). */
const TOGGLEABLE = new Set(["technologies", "processes", "markets", "storage"]);

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

/** Sheets hidden from the rail — IO lives inside each Technology, not as its own
 *  group; legacy/internal sheets are not user-facing. */
const HIDDEN = new Set([
  "io",
  "process_inputs",
  "process_outputs",
  "tech_impacts",
  "node_layout",
  "meta",
]);

interface Props {
  workbook: Workbook;
  selected: Selection | null;
  activeSheet: string;
  onGroup?: (sheet: string) => void;
  onItem: (s: Selection) => void;
  onToggle?: (sheet: string, idCol: string, id: string, enabled: boolean) => void;
  onToggleAll?: (sheet: string, idCol: string, enabled: boolean) => void;
  onToggleIds?: (sheet: string, idCol: string, ids: string[], enabled: boolean) => void;
  onAdd?: (sheet: string) => void;
  draggable?: boolean;
  width?: number;
}

/** Left rail — the single navigator: every sheet is a group (click → table in
 *  main; `+` adds a row); entity sheets expand to items (click → detail; toggle
 *  the checkbox to include/exclude in the optimisation). Each item nests its own
 *  temporal datasets (`↳ attr · by year`) directly beneath it. */
export function LeftRail({
  workbook,
  selected,
  activeSheet,
  onGroup,
  onItem,
  onToggle,
  onToggleAll,
  onToggleIds,
  onAdd,
  draggable,
  width,
}: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggleCollapse = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  const placed = new Set((workbook.node_layout ?? []).map((r) => String(r.id)));
  const baselineTechs = new Set(
    (workbook.processes ?? []).map((r) => String(r.baseline_technology ?? "")),
  );
  const targetTechs = new Set((workbook.transitions ?? []).map((r) => String(r.to_technology ?? "")));
  const all = Object.keys(workbook).filter((s) => !HIDDEN.has(s));
  const staticSheets = [
    ...ORDER.filter((s) => s in workbook && !HIDDEN.has(s)),
    ...all.filter((s) => !ORDER.includes(s) && !s.includes("_t__")),
  ];
  const temporalSheets = all.filter((s) => s.includes("_t__"));

  const isEnabled = (r: Record<string, unknown>) => r.enabled !== false && r.enabled !== "false";

  const renderItem = (sheet: string, ent: { idCol: string; kind?: NodeKind }, r: Record<string, unknown>, i: number) => {
    const id = String(r[ent.idCol] ?? "");
    if (!id) return null;
    const sel = selected?.sheet === sheet && selected.id === id ? " is-active" : "";
    const isTech = sheet === "technologies";
    const canDrag = Boolean(draggable && (ent.kind || isTech));
    const payload = ent.kind ? nodeId(ent.kind, id) : `tech:${id}`;
    const toggleable = TOGGLEABLE.has(sheet) && Boolean(onToggle);
    const enabled = isEnabled(r);
    // Status dot: ● active (placed / baseline tech), ○ alternative (transition
    // target, not baseline). Excluded items are dimmed.
    let dot = "";
    if (ent.kind && placed.has(nodeId(ent.kind, id))) dot = "dot-active";
    else if (isTech && baselineTechs.has(id)) dot = "dot-active";
    else if (isTech && targetTechs.has(id)) dot = "dot-alt";
    else if (canDrag) dot = "dot-avail";
    // Temporal series are NOT nested here — selecting the item shows them in the
    // bottom panel, and they also live in the "Temporal datasets" group below.
    return (
      <div className={`rail-item-row${enabled ? "" : " is-excluded"}`} key={`${id}-${i}`}>
        {toggleable && (
          <input
            type="checkbox"
            className="rail-check"
            checked={enabled}
            title={enabled ? "included — uncheck to exclude from the model" : "excluded — check to include"}
            onChange={(e) => onToggle?.(sheet, ent.idCol, id, e.target.checked)}
          />
        )}
        <button
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
      </div>
    );
  };

  // Facilities are shown as a Group (conglomerate) → Company (operator) →
  // Facility tree. The upper Group level is only shown when it actually differs
  // from the company (e.g. shipping's Group Company); otherwise it's Company →
  // Facility (e.g. steel: POSCO → its plants).
  const renderFacilityTree = (ent: { idCol: string; kind?: NodeKind }, rows: Record<string, unknown>[]) => {
    const tree = new Map<string, Map<string, { r: Record<string, unknown>; i: number }[]>>();
    rows.forEach((r, i) => {
      const company = String(r.company ?? "—") || "—";
      const group = String(r.group ?? "") || company;
      if (!tree.has(group)) tree.set(group, new Map());
      const byCompany = tree.get(group)!;
      if (!byCompany.has(company)) byCompany.set(company, []);
      byCompany.get(company)!.push({ r, i });
    });
    const showGroup = [...tree.entries()].some(
      ([g, byC]) => !(byC.size === 1 && byC.has(g)),
    );
    const idsOf = (items: { r: Record<string, unknown> }[]) =>
      items.map(({ r }) => String(r[ent.idCol] ?? "")).filter(Boolean);
    const allEnabled = (items: { r: Record<string, unknown> }[]) => items.every(({ r }) => isEnabled(r));
    return [...tree.entries()].map(([group, byCompany]) => {
      const gKey = `group:${group}`;
      const gOpen = !collapsed.has(gKey);
      const gItems = [...byCompany.values()].flat();
      return (
        <div key={group}>
          {showGroup && (
            <div className="rail-head-row">
              {onToggleIds && (
                <input
                  type="checkbox"
                  className="rail-check"
                  checked={allEnabled(gItems)}
                  title="include / exclude this group in the model"
                  onChange={(e) => onToggleIds("processes", ent.idCol, idsOf(gItems), e.target.checked)}
                />
              )}
              <button
                className="rail-grouphead"
                onClick={() => toggleCollapse(gKey)}
                title={gOpen ? "collapse" : "expand"}
              >
                {gOpen ? "▾" : "▸"} {group}
              </button>
            </div>
          )}
          {(!showGroup || gOpen) &&
            [...byCompany.entries()].map(([company, items]) => {
              const cKey = `company:${group}|${company}`;
              const cOpen = !collapsed.has(cKey);
              // Skip the company header when it would just repeat the group
              // (the company is its own group company) — render facilities directly.
              const showCompany = !showGroup || company !== group;
              return (
                <div key={company} className={showGroup ? "rail-indent" : ""}>
                  {showCompany && (
                    <div className="rail-head-row">
                      {onToggleIds && (
                        <input
                          type="checkbox"
                          className="rail-check"
                          checked={allEnabled(items)}
                          title="include / exclude this company in the model"
                          onChange={(e) =>
                            onToggleIds("processes", ent.idCol, idsOf(items), e.target.checked)
                          }
                        />
                      )}
                      <button
                        className="rail-subhead"
                        onClick={() => toggleCollapse(cKey)}
                        title={cOpen ? "collapse" : "expand"}
                      >
                        {cOpen ? "▾" : "▸"} {company}
                      </button>
                    </div>
                  )}
                  {(!showCompany || cOpen) &&
                    items.map(({ r, i }) => renderItem("processes", ent, r, i))}
                </div>
              );
            })}
        </div>
      );
    });
  };

  const renderGroup = (sheet: string) => {
    const rows = workbook[sheet] ?? [];
    const ent = ENTITY[sheet];
    const groupActive = activeSheet === sheet && !selected ? " is-active" : "";
    const toggleable = TOGGLEABLE.has(sheet) && Boolean(onToggleAll) && ent;
    const allOn = toggleable && rows.length > 0 && rows.every(isEnabled);
    return (
      <div className="rail-group" key={sheet}>
        <div className="rail-head-row">
          {toggleable && ent && (
            <input
              type="checkbox"
              className="rail-check"
              checked={allOn}
              title={allOn ? "deselect all" : "select all"}
              onChange={(e) => onToggleAll?.(sheet, ent.idCol, e.target.checked)}
            />
          )}
          <button className={`rail-head${groupActive}`} onClick={() => onGroup?.(sheet)}>
            {LABEL[sheet] ?? sheet} <span className="rail-count">{rows.length}</span>
          </button>
          {ent && onAdd && (
            <button className="rail-add" title={`add a ${LABEL[sheet] ?? sheet} row`} onClick={() => onAdd(sheet)}>
              +
            </button>
          )}
        </div>
        {ent &&
          (sheet === "processes"
            ? renderFacilityTree(ent, rows)
            : rows.map((r, i) => renderItem(sheet, ent, r, i)))}
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
