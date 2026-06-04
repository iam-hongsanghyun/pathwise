import type { Row, Workbook } from "../types";
import { WorkbookTable } from "./WorkbookTable";

const TRANS_COLS = ["from_technology", "to_technology", "action", "capex_per_capacity", "compatible"];
const TECH_COLS = ["technology_id", "lifespan", "introduction_year", "actions", "capex", "renewal", "opex"];

interface Props {
  workbook: Workbook;
  onChange: (wb: Workbook) => void;
}

/** Define what each technology can do (replace/renew/continue, availability,
 *  costs) and the permitted transitions + reuse compatibility. The optimiser
 *  uses these to decide whether to CHANGE a machine (transition). */
export function TransitionDesigner({ workbook, onChange }: Props) {
  const set = (sheet: string, rows: Row[]) => onChange({ ...workbook, [sheet]: rows });
  return (
    <div>
      <h3>Technologies & availability</h3>
      <p className="muted">
        <code>actions</code> = comma list of <code>replace,renew,continue</code>;{" "}
        <code>lifespan</code>/<code>introduction_year</code> bound when a tech is usable.
      </p>
      <WorkbookTable
        rows={workbook.technologies ?? []}
        columns={TECH_COLS}
        onChange={(r) => set("technologies", r)}
      />
      <h3>Permitted transitions</h3>
      <p className="muted">
        <code>compatible = true</code> ⇒ neighbouring machines can be reused after the swap;{" "}
        <code>false</code> ⇒ a replacement forces connected machines to change too (modelled in a
        later step).
      </p>
      <WorkbookTable
        rows={workbook.transitions ?? []}
        columns={TRANS_COLS}
        onChange={(r) => set("transitions", r)}
      />
    </div>
  );
}
