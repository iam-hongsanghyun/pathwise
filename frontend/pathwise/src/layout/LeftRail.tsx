import type { Selection, Workbook } from "../types";

const GROUPS: { label: string; sheet: string; idCol: string }[] = [
  { label: "Facilities", sheet: "processes", idCol: "process_id" },
  { label: "Streams", sheet: "commodities", idCol: "commodity_id" },
  { label: "Markets", sheet: "markets", idCol: "market_id" },
  { label: "Storage", sheet: "storage", idCol: "storage_id" },
  { label: "Technologies", sheet: "technologies", idCol: "technology_id" },
  { label: "Measures", sheet: "measures", idCol: "measure_id" },
  { label: "Impacts", sheet: "impacts", idCol: "impact_id" },
];

interface Props {
  workbook: Workbook;
  selected: Selection | null;
  onSelect: (s: Selection) => void;
}

/** Left rail — a grouped, clickable model tree for navigation/selection. */
export function LeftRail({ workbook, selected, onSelect }: Props) {
  return (
    <aside className="left-rail" aria-label="Model tree">
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
              const active =
                selected?.sheet === g.sheet && selected.id === id ? " is-active" : "";
              return (
                <button
                  key={`${id}-${i}`}
                  className={`rail-item${active}`}
                  onClick={() => onSelect({ sheet: g.sheet, idCol: g.idCol, id })}
                  title={id}
                >
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
