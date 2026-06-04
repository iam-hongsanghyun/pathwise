interface Props {
  discount: number;
  onDiscount: (v: number) => void;
}

/** Settings — scenario / run parameters only (model data is edited in Data).
 *  Snapshots are the planned PyPSA-style sub-annual resolution. */
export function SettingsView({ discount, onDiscount }: Props) {
  return (
    <div className="view">
      <section className="card">
        <h3>Economics</h3>
        <label className="inspector-field">
          <span>Discount rate</span>
          <input
            type="number"
            step="0.01"
            value={discount}
            onChange={(e) => onDiscount(Number(e.target.value))}
          />
        </label>
      </section>

      <section className="card">
        <h3>Snapshots (time resolution)</h3>
        <p className="muted">
          Current runs are <strong>annual</strong> (one snapshot per period). Weighted
          sub-annual snapshots (hourly→yearly, PyPSA-style) for intra-year price/storage
          dynamics are planned.
        </p>
        <label className="inspector-field">
          <span>Resolution</span>
          <select disabled value="annual">
            <option value="annual">Annual (per period)</option>
          </select>
        </label>
      </section>

      <section className="card">
        <h3>Solver</h3>
        <p className="muted">HiGHS via linopy. Per-company objective, budgets, and minimum
          production are edited in the Data tables.</p>
      </section>
    </div>
  );
}
