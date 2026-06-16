import { LineChart } from "./LineChart";
import type { MaccResultBlock } from "../../types";

/** Result view for a greedy-MACC run: the emission pathway (BAU vs target vs
 *  achieved), per-option abatement deployed over time, cumulative CAPEX, and a
 *  per-year table. Mirrors the dedicated PortfolioResult view — MILP timelines
 *  are empty for a MACC run, so this stands in for the standard analytics. */
export function MaccResult({ macc }: { macc: MaccResultBlock }) {
  const rows = macc.by_year;
  const years = rows.map((r) => r.year);
  const last = rows[rows.length - 1];
  const unit = macc.impact_id === "CO2" ? "Mt" : "";

  const emissionSeries = [
    { label: "BAU", values: rows.map((r) => r.bau) },
    { label: "Target", values: rows.map((r) => r.target) },
    { label: "Achieved", values: rows.map((r) => r.actual_emissions) },
  ];
  const deploySeries = macc.options.map((o) => ({
    label: o.label || o.option_id,
    values: rows.map((r) => r.deployed[o.option_id] ?? 0),
  }));
  const capexSeries = [{ label: "cumulative CAPEX", values: rows.map((r) => r.cumulative_capex) }];

  const fmt = (v: number, d = 2) => v.toLocaleString(undefined, { maximumFractionDigits: d });

  return (
    <div className="view">
      <div className="card">
        <h3>MACC (greedy abatement) · result</h3>
        <p className="muted">
          Cheapest-first deployment against the emission target, carried forward irreversibly.
        </p>
        <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap", marginTop: ".5rem" }}>
          <Stat label={`Residual ${last?.year ?? ""}`} value={`${fmt(last?.actual_emissions ?? 0)} ${unit}`} />
          <Stat label={`Target ${last?.year ?? ""}`} value={`${fmt(last?.target ?? 0)} ${unit}`} />
          <Stat label="Cumulative CAPEX" value={fmt(macc.cumulative_capex, 1)} />
          <Stat label="Options deployed" value={String(macc.options.length)} />
        </div>
      </div>

      <div className="card">
        <h3>Emission pathway</h3>
        <LineChart years={years} series={emissionSeries} unit={unit} />
      </div>

      <div className="card">
        <h3>Abatement deployed by option (cumulative)</h3>
        <LineChart years={years} series={deploySeries} unit={unit} />
      </div>

      <div className="card">
        <h3>Cumulative CAPEX over time</h3>
        <LineChart years={years} series={capexSeries} />
      </div>

      <div className="card">
        <h3>Per-year deployment</h3>
        <div style={{ overflowX: "auto" }}>
          <table className="grid-table">
            <thead>
              <tr>
                <th>Year</th>
                <th>BAU</th>
                <th>Target</th>
                <th>Achieved</th>
                <th>Shortfall</th>
                <th>Cum. CAPEX</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.year}>
                  <td>{r.year}</td>
                  <td>{fmt(r.bau)}</td>
                  <td>{fmt(r.target)}</td>
                  <td>{fmt(r.actual_emissions)}</td>
                  <td>{fmt(r.shortfall)}</td>
                  <td>{fmt(r.cumulative_capex, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="muted" style={{ fontSize: ".8rem" }}>{label}</div>
      <div style={{ fontSize: "1.3rem", fontWeight: 600 }}>{value}</div>
    </div>
  );
}
