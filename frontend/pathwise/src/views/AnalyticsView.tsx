import { useState } from "react";
import { MaccDesigner } from "../components/MaccDesigner";
import { RailList, type RailItem } from "../layout/RailList";
import { Resizer } from "../layout/Resizer";
import type { RunResult, Workbook } from "../types";

type Cat = "overview" | "impacts" | "energy" | "transitions" | "measures" | "macc";

interface Props {
  workbook: Workbook;
  result: RunResult | null;
  leftW: number;
  setLeftW: (w: number) => void;
}

/** Analytics — its own category rail; the main shows the chart/table for the
 *  chosen category. (Design-time MACC works without a run.) */
export function AnalyticsView({ workbook, result, leftW, setLeftW }: Props) {
  const [cat, setCat] = useState<Cat>("overview");
  const items: RailItem[] = [
    { id: "overview", label: "Overview" },
    { id: "impacts", label: "Impacts" },
    { id: "energy", label: "Energy & flows" },
    { id: "transitions", label: "Transitions" },
    { id: "measures", label: "Measures" },
    { id: "macc", label: "MACC" },
  ];

  return (
    <div className="body-row">
      <RailList
        title="Analytics"
        items={items}
        activeId={cat}
        onSelect={(id) => setCat(id as Cat)}
        width={leftW}
      />
      <Resizer width={leftW} setWidth={setLeftW} side="left" />
      <main className="main-area">
        <div className="view">
          {cat === "macc" ? (
            <MaccDesigner workbook={workbook} />
          ) : !result ? (
            <p className="muted">Run the model (▶ top-left) to populate analytics.</p>
          ) : (
            <Category cat={cat} result={result} />
          )}
        </div>
      </main>
    </div>
  );
}

function Bars({ rows }: { rows: { label: string; value: number }[] }) {
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 1);
  return (
    <div className="bars">
      {rows.map((r, i) => (
        <div key={i} className="bar-row">
          <span className="bar-label">{r.label}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${(Math.abs(r.value) / max) * 100}%` }} />
          </span>
          <span className="bar-val">{r.value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

function Category({ cat, result }: { cat: Cat; result: RunResult }) {
  if (cat === "overview") {
    return (
      <div className="card">
        <h3>Result</h3>
        <p>
          Status <strong>{result.status}</strong>
          {result.objective != null && (
            <>
              {" "}
              · net cost <strong>{result.objective.toLocaleString()}</strong>
            </>
          )}
        </p>
        {result.outputs.demand_slack.length > 0 && (
          <p className="error">⚠ demand not fully met: {result.outputs.demand_slack.length} item(s)</p>
        )}
      </div>
    );
  }
  if (cat === "impacts") {
    const periods = [...new Set(result.summary.impacts.map((s) => s.period))].sort();
    const names = [...new Set(result.summary.impacts.map((s) => s.impact))].sort();
    const at = (p: number, i: string) =>
      result.summary.impacts.find((s) => s.period === p && s.impact === i)?.total ?? 0;
    return (
      <div className="card">
        <h3>Environmental impacts by year</h3>
        <table>
          <thead>
            <tr>
              <th>impact</th>
              {periods.map((p) => (
                <th key={p}>{p}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {names.map((i) => (
              <tr key={i}>
                <td>{i}</td>
                {periods.map((p) => (
                  <td key={p}>{at(p, i).toFixed(1)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (cat === "energy") {
    const mk = result.outputs.markets.map((m) => ({
      label: `${m.market} (${m.commodity})`,
      value: m.by_period.reduce((s, b) => s + b.buy, 0),
    }));
    return (
      <div className="card">
        <h3>Market purchases (total)</h3>
        {mk.length ? <Bars rows={mk} /> : <p className="muted">No market purchases.</p>}
        <h3>Flows</h3>
        <ul>
          {result.outputs.flows.map((f, i) => (
            <li key={i}>
              {f.from} → {f.to} · {f.commodity} · {f.value.toFixed(0)} ({f.period})
            </li>
          ))}
        </ul>
      </div>
    );
  }
  if (cat === "transitions") {
    return (
      <div className="card">
        <h3>Technology transitions</h3>
        {result.outputs.transitions.length ? (
          <ul>
            {result.outputs.transitions.map((t, i) => (
              <li key={i}>
                {t.process} → {t.to_technology} in {t.period}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No transitions chosen.</p>
        )}
      </div>
    );
  }
  // measures
  return (
    <div className="card">
      <h3>Measures adopted (MACC upgrades)</h3>
      {result.outputs.measures.length ? (
        <ul>
          {result.outputs.measures.map((m, i) => (
            <li key={i}>
              {m.measure} @ {m.process} ({m.type}) — {(m.adoption * 100).toFixed(0)}% in {m.period}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No measures adopted.</p>
      )}
    </div>
  );
}
