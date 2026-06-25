import { useState } from "react";
import { LineChart } from "../features/charts/LineChart";
import { MaccDesigner } from "../features/macc/MaccDesigner";
import { MaccResult } from "../features/charts/MaccResult";
import { LcaResult } from "../features/charts/LcaResult";
import { FrontierResult } from "../features/charts/FrontierResult";
import { PortfolioResult } from "../features/charts/PortfolioResult";
import { TopologyCanvas } from "../features/topology/TopologyCanvas";
import { HierarchyMap } from "../features/topology/HierarchyMap";
import { RouteAnalytics } from "../features/fleet/RouteAnalytics";
import { AccordionSidebar, type AccordionSection } from "../layout/AccordionSidebar";
import { downloadResultSqlite, downloadResultXlsx } from "../lib/api/session";
import type { RailItem } from "../layout/RailList";
import type { RunMeta, RunResult, Workbook } from "../types";

type Cat = "overview" | "map" | "routes" | "consumption" | "cost" | "impacts" | "transitions" | "levers" | "macc";

const CAT_LABEL: Record<Cat, string> = {
  overview: "Overview",
  map: "Process map",
  routes: "Transport routes",
  consumption: "Flow consumption",
  cost: "Cost over time",
  impacts: "Impacts",
  transitions: "Transitions",
  levers: "Levers",
  macc: "MACC",
};

/** The consistent view header every view shows at the top of its main panel.
 *  When a result is present it also offers to download it (which marks the
 *  stored run "exported", so a cache clear keeps it). */
function AnalyticsHead({ title, result }: { title: string; result?: RunResult | null }) {
  return (
    <div
      className="view-head"
      style={{ padding: "16px 16px 0", display: "flex", alignItems: "baseline", gap: 12 }}
    >
      <div className="eyebrow">analytics</div>
      <span className="view-status" style={{ flex: 1 }}>{title}</span>
      {result && (
        <span style={{ display: "flex", gap: 6 }}>
          <button className="ghost" title="Download as .xlsx (keeps this run on clear)" onClick={() => void downloadResultXlsx(result)}>⬇ xlsx</button>
          <button className="ghost" title="Download as .sqlite (keeps this run on clear)" onClick={() => void downloadResultSqlite(result)}>⬇ sqlite</button>
        </span>
      )}
    </div>
  );
}

/** The run-history list: re-open a past run, with a badge for the exported ones
 *  (the ones a cache clear keeps). */
function RunHistory({
  runs,
  currentRunId,
  onLoadRun,
}: {
  runs: RunMeta[];
  currentRunId?: string;
  onLoadRun: (runId: string) => void;
}) {
  if (!runs.length) {
    return <div className="rail-empty" style={{ padding: 10 }}>No runs yet — ▶ run the model.</div>;
  }
  return (
    <div className="rail-group">
      {runs.map((r) => (
        <button
          key={r.runId}
          className={`rail-item${r.runId === currentRunId ? " is-active" : ""}`}
          style={{ width: "100%", display: "flex", justifyContent: "space-between", gap: 8 }}
          title={`${r.createdAt}${r.objective != null ? ` · obj ${r.objective.toLocaleString()}` : ""}`}
          onClick={() => onLoadRun(r.runId)}
        >
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {r.createdAt.slice(0, 16).replace("T", " ")} · {r.status}
          </span>
          {r.exported && <span className="pw-pill" title="exported — kept on clear">★</span>}
        </button>
      ))}
    </div>
  );
}

interface Props {
  workbook: Workbook;
  result: RunResult | null;
  runs: RunMeta[];
  onLoadRun: (runId: string) => void;
  leftW: number;
  setLeftW: (w: number) => void;
}

/** Analytics — category accordion sidebar + tailored main; the process map animates over
 *  years via the bottom slider, with consumption and cost as time series. */
export function AnalyticsView({ workbook, result, runs, onLoadRun, leftW, setLeftW }: Props) {
  const [cat, setCat] = useState<Cat>("overview");
  const [railOpen, setRailOpen] = useState(false);
  // The run-history section, appended to every variant's sidebar so a past run can
  // be re-opened (and its exported state seen) from anywhere in analytics.
  const runsSection: AccordionSection = {
    id: "runs",
    title: `Runs${runs.length ? ` (${runs.length})` : ""}`,
    defaultOpen: false,
    grow: false,
    body: <RunHistory runs={runs} currentRunId={result?.runId} onLoadRun={onLoadRun} />,
  };
  const withRuns = (secs: AccordionSection[]): AccordionSection[] => [...secs, runsSection];
  const years = [...new Set((result?.summary.periods ?? []).map((p) => p.period))].sort((a, b) => a - b);
  const [year, setYear] = useState<number | null>(null);
  const activeYear = year ?? years[years.length - 1] ?? 0;

  // A portfolio-backend result carries its own block.
  const pf = result?.outputs.portfolio;
  if (pf) {
    return (
      <div className="body-row">
        <AccordionSidebar
          open={railOpen}
          setOpen={setRailOpen}
          width={leftW}
          setWidth={setLeftW}
          min={160}
          max={360}
          sections={withRuns([{
            id: "analytics",
            title: "Analytics",
            defaultOpen: false,
            grow: false,
            body: (
              <button className="rail-item is-active" style={{ width: "100%" }}>Portfolio</button>
            ),
          }])}
        />
        <main className="main-area">
          <AnalyticsHead title="Portfolio" result={result} />
          <PortfolioResult portfolio={pf} />
        </main>
      </div>
    );
  }

  // A frontier run carries the cost–impact Pareto curve.
  const frontier = result?.outputs.frontier;
  if (frontier) {
    return (
      <div className="body-row">
        <AccordionSidebar
          open={railOpen}
          setOpen={setRailOpen}
          width={leftW}
          setWidth={setLeftW}
          min={160}
          max={360}
          sections={withRuns([{
            id: "analytics",
            title: "Analytics",
            defaultOpen: false,
            grow: false,
            body: (
              <button className="rail-item is-active" style={{ width: "100%" }}>Frontier</button>
            ),
          }])}
        />
        <main className="main-area">
          <AnalyticsHead title="Cost–impact frontier" result={result} />
          <FrontierResult frontier={frontier} />
        </main>
      </div>
    );
  }

  // A simulate (LCA what-if) result carries an `lca` block.
  const lca = result?.outputs.lca;
  if (lca) {
    return (
      <div className="body-row">
        <AccordionSidebar
          open={railOpen}
          setOpen={setRailOpen}
          width={leftW}
          setWidth={setLeftW}
          min={160}
          max={360}
          sections={withRuns([{
            id: "analytics",
            title: "Analytics",
            defaultOpen: false,
            grow: false,
            body: (
              <button className="rail-item is-active" style={{ width: "100%" }}>LCA</button>
            ),
          }])}
        />
        <main className="main-area">
          <AnalyticsHead title="Lifecycle assessment" result={result} />
          <LcaResult result={result} />
        </main>
      </div>
    );
  }

  // MACC result.
  const macc = result?.outputs.macc;
  if (macc) {
    return (
      <div className="body-row">
        <AccordionSidebar
          open={railOpen}
          setOpen={setRailOpen}
          width={leftW}
          setWidth={setLeftW}
          min={160}
          max={360}
          sections={withRuns([{
            id: "analytics",
            title: "Analytics",
            defaultOpen: false,
            grow: false,
            body: (
              <button className="rail-item is-active" style={{ width: "100%" }}>MACC</button>
            ),
          }])}
        />
        <main className="main-area">
          <AnalyticsHead title="MACC" result={result} />
          <MaccResult macc={macc} />
        </main>
      </div>
    );
  }

  // Surface the transport-routes map only when the solve produced physical routes.
  const hasRoutes = (result?.outputs.fleet?.length ?? 0) > 0;
  const items: RailItem[] = [
    { id: "overview", label: "Overview" },
    { id: "map", label: "Process map (by year)" },
    ...(hasRoutes ? [{ id: "routes", label: "Transport routes (map)" }] : []),
    { id: "consumption", label: "Flow consumption" },
    { id: "cost", label: "Cost over time" },
    { id: "impacts", label: "Impacts" },
    { id: "transitions", label: "Transitions" },
    { id: "levers", label: "Levers" },
    { id: "macc", label: "MACC" },
  ];

  return (
    <div className="body-row">
      <AccordionSidebar
        open={railOpen}
        setOpen={setRailOpen}
        width={leftW}
        setWidth={setLeftW}
        min={160}
        max={360}
        sections={withRuns([{
          id: "analytics",
          title: "Analytics",
          defaultOpen: false,
          grow: false,
          body: (
            <div className="rail-group">
              {items.map((it) => (
                <button
                  key={it.id}
                  className={`rail-item${it.id === cat ? " is-active" : ""}`}
                  onClick={() => setCat(it.id as Cat)}
                >
                  {it.label}
                </button>
              ))}
            </div>
          ),
        }])}
      />
      <main className="main-area">
        <AnalyticsHead title={result ? CAT_LABEL[cat] : "run the model to populate"} result={result} />
        {cat === "macc" ? (
          <div className="view">
            <MaccDesigner workbook={workbook} />
          </div>
        ) : !result ? (
          <div className="view">
            <p className="muted">Run the model (▶ top-left) to populate analytics.</p>
          </div>
        ) : cat === "routes" ? (
          <RouteAnalytics workbook={workbook} result={result} />
        ) : cat === "map" ? (
          (workbook.nodes?.length ?? 0) > 0 ? (
            <HierarchyMap workbook={workbook} result={result} />
          ) : (
            <>
              <div className="year-slider" style={{ borderBottom: "1px solid var(--border)", borderTop: "none" }}>
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
              <div className="topology-wrap">
                <TopologyCanvas workbook={workbook} result={result} year={activeYear} />
              </div>
            </>
          )
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
          {result.outputs.transitions.length} transition(s), {result.outputs.levers.length} lever
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
    const names = [...new Set(result.summary.flow.map((s) => s.flow))]
      .filter((c) => result.summary.flow.some((s) => s.flow === c && s.consumed > 1e-6))
      .sort();
    const series = names.map((c) => ({
      label: c,
      values: years.map(
        (y) => result.summary.flow.find((s) => s.flow === c && s.period === y)?.consumed ?? 0,
      ),
    }));
    return (
      <div className="card">
        <h3>Flow consumption over time</h3>
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
      <h3>Levers adopted (MACC upgrades)</h3>
      {result.outputs.levers.length ? (
        <ul>
          {result.outputs.levers.map((m, i) => (
            <li key={i}>
              {m.lever} @ {m.process} ({m.type}) — {(m.adoption * 100).toFixed(0)}% in {m.period}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No levers adopted.</p>
      )}
    </div>
  );
}
