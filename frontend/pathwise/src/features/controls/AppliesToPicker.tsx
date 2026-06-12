import type { Workbook } from "../../types";
import { SearchableSelect } from "./SearchableSelect";

interface Props {
  value: string;
  workbook: Workbook;
  onChange: (v: string) => void;
  /** Open the create flow for a name typed into the facility / technology box. */
  onCreateFacility?: (name: string) => void;
  onCreateTechnology?: (name: string) => void;
  /** Neither box filled counts as a problem (red) — suppressed when the row is
   *  reached another way, e.g. a measure linked through a MACC set. */
  missingIsOk?: boolean;
}

const ids = (wb: Workbook, sheet: string, col: string) =>
  [...new Set((wb[sheet] ?? []).map((r) => String(r[col] ?? "")).filter(Boolean))].sort();

/** One stored target, two explicit pickers: choose a FACILITY (that plant
 *  only) or a TECHNOLOGY (every facility running it). Picking in one clears
 *  the other; choosing neither is flagged red. */
export function AppliesToPicker({
  value,
  workbook,
  onChange,
  onCreateFacility,
  onCreateTechnology,
  missingIsOk,
}: Props) {
  const facs = ids(workbook, "processes", "process_id");
  const techs = ids(workbook, "technologies", "technology_id");
  const isFac = facs.includes(value);
  const isTech = techs.includes(value);
  const broken = value !== "" && !isFac && !isTech;
  const missing = value === "" && !missingIsOk;
  return (
    <div className={`applies-pair${missing ? " is-missing" : ""}`}>
      <div className="applies-row">
        <span className="applies-tag">facility</span>
        <SearchableSelect
          value={isFac ? value : ""}
          options={facs}
          onChange={onChange}
          onCreate={onCreateFacility}
          hint="add a facility first"
          placeholder={missing ? "choose one…" : undefined}
        />
      </div>
      <div className="applies-row">
        <span className="applies-tag">technology</span>
        <SearchableSelect
          value={isTech || broken ? value : ""}
          options={techs}
          broken={broken}
          onChange={onChange}
          onCreate={onCreateTechnology}
          hint="add a technology first"
          placeholder={missing ? "…or one here" : undefined}
        />
      </div>
    </div>
  );
}
