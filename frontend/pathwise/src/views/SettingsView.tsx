import type { Row, Workbook } from "../types";
import { WorkbookTable } from "../components/WorkbookTable";

interface Props {
  workbook: Workbook;
  onChange: (wb: Workbook) => void;
  discount: number;
  onDiscount: (v: number) => void;
}

/** Scenario + per-company settings: objective (profit/cost), discount, budgets. */
export function SettingsView({ workbook, onChange, discount, onDiscount }: Props) {
  const set = (sheet: string, rows: Row[]) => onChange({ ...workbook, [sheet]: rows });
  return (
    <div className="view">
      <section className="card">
        <h3>Scenario</h3>
        <label>
          Discount rate{" "}
          <input
            type="number"
            step="0.01"
            value={discount}
            onChange={(e) => onDiscount(Number(e.target.value))}
          />
        </label>
      </section>

      <section>
        <h3>Per-company objective</h3>
        <p className="muted">
          <code>cost</code> = meet demand at least cost; <code>profit</code> = maximise profit
          (sell up to demand, produce less if unprofitable).
        </p>
        <WorkbookTable
          rows={workbook.company_config ?? []}
          columns={["company", "objective"]}
          onChange={(r) => set("company_config", r)}
        />
      </section>

      <section>
        <h3>Investment budget</h3>
        <WorkbookTable
          rows={workbook.investment_budget ?? []}
          columns={["company", "year", "limit"]}
          onChange={(r) => set("investment_budget", r)}
        />
      </section>

      <section>
        <h3>Minimum production</h3>
        <WorkbookTable
          rows={workbook.min_production ?? []}
          columns={["company", "commodity_id", "year", "amount"]}
          onChange={(r) => set("min_production", r)}
        />
      </section>
    </div>
  );
}
