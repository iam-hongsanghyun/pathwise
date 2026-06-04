import type { RunResult } from "../types";

interface Props {
  result: RunResult;
}

/** Optimisation result: cost, per-pollutant trajectories, the chosen
 *  technologies (transitions) and adopted measures (MACC upgrades), and flows. */
export function ResultsView({ result }: Props) {
  const invalid = result.status === "invalid";
  const impactPeriods = [...new Set(result.summary.impacts.map((s) => s.period))].sort();
  const impactNames = [...new Set(result.summary.impacts.map((s) => s.impact))].sort();
  const lookup = (p: number, i: string) =>
    result.summary.impacts.find((s) => s.period === p && s.impact === i)?.total ?? 0;

  return (
    <section className="results">
      <h2>
        Result — {result.status}
        {result.objective != null && (
          <span className="muted"> · cost {result.objective.toLocaleString()}</span>
        )}
      </h2>

      {(result.validation.errors.length > 0 || result.validation.warnings.length > 0) && (
        <div className={invalid ? "validation bad" : "validation ok"}>
          {result.validation.errors.map((e, i) => (
            <div key={`e${i}`} className="error">
              ✗ {e}
            </div>
          ))}
          {result.validation.warnings.map((w, i) => (
            <div key={`w${i}`} className="muted">
              ⚠ {w}
            </div>
          ))}
        </div>
      )}

      {!invalid && (
        <>
          {impactNames.length > 0 && (
            <>
              <h3>Environmental impacts</h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>impact</th>
                      {impactPeriods.map((p) => (
                        <th key={p}>{p}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {impactNames.map((i) => (
                      <tr key={i}>
                        <td>{i}</td>
                        {impactPeriods.map((p) => (
                          <td key={p}>{lookup(p, i).toFixed(1)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {result.outputs.transitions.length > 0 && (
            <>
              <h3>Technology transitions (change)</h3>
              <ul>
                {result.outputs.transitions.map((t, i) => (
                  <li key={i}>
                    {t.process} → {t.to_technology} in {t.period}
                  </li>
                ))}
              </ul>
            </>
          )}

          {result.outputs.measures.length > 0 && (
            <>
              <h3>Measures adopted (upgrade / MACC)</h3>
              <ul>
                {result.outputs.measures.map((m, i) => (
                  <li key={i}>
                    {m.measure} @ {m.process} ({m.type}) — {(m.adoption * 100).toFixed(0)}% in {m.period}
                  </li>
                ))}
              </ul>
            </>
          )}

          {result.outputs.storage.length > 0 && (
            <>
              <h3>Storage</h3>
              <ul>
                {result.outputs.storage.map((s, i) => (
                  <li key={i}>
                    {s.storage} ({s.commodity}) — built {s.capacity.toFixed(0)}; levels{" "}
                    {s.by_period.map((b) => `${b.period}:${b.level.toFixed(0)}`).join(", ")}
                  </li>
                ))}
              </ul>
            </>
          )}

          {result.outputs.demand_slack.length > 0 && (
            <div className="error">⚠ demand not fully met: {result.outputs.demand_slack.map((s) => s.key).join(", ")}</div>
          )}
        </>
      )}
    </section>
  );
}
