import { useState } from "react";
import { LineChart } from "../components/LineChart";
import { MaccDesigner } from "../components/MaccDesigner";
import { TopologyChart } from "../components/TopologyChart";
import { RailList, type RailItem } from "../layout/RailList";
import { Resizer } from "../layout/Resizer";
import type { RunResult, Workbook } from "../types";

type Cat = "overview" | "map" | "consumption" | "cost" | "impacts" | "transitions" | "measures" | "macc";

interface Props {
  workbook: Workbook;
  result: RunResult | null;
  leftW: number;
  setLeftW: (w: number) => void;
}

/** Analytics — category rail + tailored main; the process map animates over
 *  years via the bottom slider, with consumption and cost as time series. */
export function AnalyticsView({ workbook, result, leftW, setLeftW }: Props) {
  const [cat, setCat] = useState<Cat>("overview");
  const years = [...new Set((result?.summary.periods ?? []).map((p) => p.period))].sort((a, b) => a - b);
  const [year, setYear] = useState<number | null>(null);
  const activeYear = year ?? years[years.length - 1] ?? 0;

  const items: RailItem[] = [
    { id: "overview", label: "Overview" },
    { id: "map", label: "Process map (by year)" },
    { id: "consumption", label: "Commodity consumption" },
    { id: "cost", label: "Cost over time" },
    { id: "impacts", label: "Impacts" },
    { id: "transitions", label: "Transitions" },
    { id: "measures", label: "Measures" },
    { id: "macc", label: "MACC" },
  ];

  return (
    <div className="body-row">
      <RailList title="Analytics" items={items} activeId={cat} onSelect={(id) => setCat(id as Cat)} width={leftW} />
      <Resizer width={leftW} setWidth={setLeftW} side="left" />
      <main className="main-area">
        {cat === "macc" ? (
          <div className="view">
            <MaccDesigner workbook={workbook} />
          </div>
        ) : !result ? (
          <div className="view">
            <p className="muted">Run the model (▶ top-left) to populate analytics.</p>
          </div>
        ) : cat === "map" ? (
          <>
            <div className="topology-wrap">
              <TopologyChart workbook={workbook} result={result} year={activeYear} />
            </div>
            <div className="year-slider">
              <span className="muted">Year</span>
              <input
                type="range"
                min={0}
                max={Math.max(years.length - 1, 0)}
                value={years.indexOf(activeYear)}
                onChange={(e) => setYear(years[Number(e.target.value)])}
              />
              <strong>{activeYear}</strong>
            </div>
          </>
        ) : (
          <div className="view">
            <Body cat={cat} result={result} years={years} />
          </div>
        )}
      </main>
    </div>
  );
}

function Body({ cat, result, years }: { cat: Cat; result: RunResult; years: number[] }) {
  if (cat === "overview") {
    return (
      <div className="card">
        <h3>Result · {result.status}</h3>
        {result.objective != null && <p>Net cost (NPV): <strong>{result.objective.toLocaleString()}</strong></p>}
        <p className="muted">
          {result.outputs.transitions.length} transition(s), {result.outputs.measures.length} measure
          adoption(s){result.outputs.demand_slack.length ? `, ${result.outputs.demand_slack.length} unmet demand` : ""}.
        </p>
      </div>
    );
  }
  if (cat === "cost") {
    const values = years.map((y) => result.summary.periods.find((p) => p.period === y)?.cost ?? 0);
    return (
      <div className="card">
        <h3>Cost over time (per year)</h3>
        <LineChart years={years} series={[{ label: "annual cost", values }]} />
      </div>
    );
  }
  if (cat === "consumption") {
    const names = [...new Set(result.summary.commodity.map((s) => s.commodity))]
      .filter((c) => result.summary.commodity.some((s) => s.commodity === c && s.consumed > 1e-6))
      .sort();
    const series = names.map((c) => ({
      label: c,
      values: years.map(
        (y) => result.summary.commodity.find((s) => s.commodity === c && s.period === y)?.consumed ?? 0,
      ),
    }));
    return (
      <div className="card">
        <h3>Commodity consumption over time</h3>
        {series.length ? <LineChart years={years} series={series} /> : <p className="muted">No consumption.</p>}
      </div>
    );
  }
  if (cat === "impacts") {
    const names = [...new Set(result.summary.impacts.map((s) => s.impact))].sort();
    const series = names.map((i) => ({
      label: i,
      values: years.map((y) => result.summary.impacts.find((s) => s.impact === i && s.period === y)?.total ?? 0),
    }));
    return (
      <div className="card">
        <h3>Environmental impacts over time</h3>
        {series.length ? <LineChart years={years} series={series} unit="" /> : <p className="muted">No impacts.</p>}
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
              <li key={i}>{t.process} → {t.to_technology} in {t.period}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">No transitions chosen.</p>
        )}
      </div>
    );
  }
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
