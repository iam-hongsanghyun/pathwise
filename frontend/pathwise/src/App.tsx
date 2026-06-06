import { useEffect, useState } from "react";
import { getConfig, runToCompletion } from "./api";
import { ActivityBar, type View } from "./layout/ActivityBar";
import { AnalyticsView } from "./views/AnalyticsView";
import { ModelView } from "./views/ModelView";
import { SettingsView } from "./views/SettingsView";
import type { ConfigBundle, PortfolioConfig, RunResult, Workbook } from "./types";
import {
  downloadResult,
  downloadWorkbook,
  emptyWorkbook,
  type ExampleModel,
  listExamples,
  loadExample,
  parseWorkbookFile,
} from "./workbook";

export function App() {
  const [config, setConfig] = useState<ConfigBundle | null>(null);
  const [workbook, setWorkbook] = useState<Workbook>(emptyWorkbook());
  const [view, setView] = useState<View>("model");
  const [discount, setDiscount] = useState(0.08);
  const [objScope, setObjScope] = useState<"system" | "company" | "facility">("company");
  const [backend, setBackend] = useState("linopy");
  const [portfolio, setPortfolio] = useState<PortfolioConfig>({
    method: "mvo",
    reward_mode: "cost_reduction",
    asset_level: "facility",
    n_scenarios: 2000,
    volatility: 0,
    risk_aversion: 1,
    target_return: null,
    cvar_alpha: 0.95,
    views: [],
  });
  const [result, setResult] = useState<RunResult | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [leftW, setLeftW] = useState(232);
  const [examples, setExamples] = useState<ExampleModel[]>([]);

  useEffect(() => {
    getConfig()
      .then(setConfig)
      .catch((e) => setError(String(e)));
    listExamples()
      .then(setExamples)
      .catch(() => setExamples([]));
  }, []);

  async function onPickExample(id: string) {
    const model = examples.find((e) => e.id === id);
    if (!model) return;
    setError(null);
    try {
      setWorkbook(await loadExample(model.file));
      setResult(null);
      setView("model");
    } catch (e) {
      setError(String(e));
    }
  }

  async function onUpload(file: File) {
    setError(null);
    try {
      setWorkbook(await parseWorkbookFile(file));
      setResult(null);
    } catch (e) {
      setError(String(e));
    }
  }

  async function onRun() {
    setError(null);
    setResult(null);
    try {
      const scenario: Record<string, unknown> = {
        domain: "process",
        economics: { discount_rate: discount },
        optimisation_scope: objScope,
      };
      if (backend === "portfolio") {
        const v = portfolio.volatility;
        scenario.portfolio = {
          method: portfolio.method,
          reward_mode: portfolio.reward_mode,
          asset_level: portfolio.asset_level,
          n_scenarios: portfolio.n_scenarios,
          // A single UI volatility applies to every category; 0 ⇒ engine defaults.
          volatility:
            v > 0
              ? {
                  commodity_price: v,
                  sale_price: v,
                  impact_price: v,
                  opex: v,
                  capex: v,
                }
              : {},
          risk_aversion: portfolio.risk_aversion,
          target_return: portfolio.target_return,
          cvar_alpha: portfolio.cvar_alpha,
          bl_views: Object.fromEntries(portfolio.views.map((vw) => [vw.asset, vw.view])),
        };
      }
      const res = await runToCompletion(workbook, scenario, { domain: "process", backend }, setRunning);
      setResult(res);
      setView("analytics");
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(null);
    }
  }

  const shared = { workbook, setWorkbook, config, leftW, setLeftW };

  return (
    <div className="studio-shell">
      <ActivityBar view={view} onChange={setView} />
      <div className="workspace">
        <header className="topbar">
          <button className="run-button" onClick={onRun} disabled={running != null}>
            {running ? `▶ Running… (${running})` : "▶ Run"}
          </button>
          <div>
            <div className="eyebrow">facility transition optimiser</div>
            <h1>pathwise{config ? ` · build ${config.buildId}` : ""}</h1>
          </div>
          <span className="spacer" />
          <label>
            Example library
            <select
              value=""
              onChange={(e) => e.target.value && onPickExample(e.target.value)}
              disabled={examples.length === 0}
            >
              <option value="">{examples.length ? "Open a model…" : "no examples"}</option>
              {examples.map((m) => (
                <option key={m.id} value={m.id} title={m.description}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Upload
            <input
              type="file"
              accept=".xlsx"
              onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])}
            />
          </label>
          <button className="ghost" onClick={() => downloadWorkbook(workbook)}>
            Export model
          </button>
          <button className="ghost" onClick={() => result && downloadResult(result)} disabled={!result}>
            Export result
          </button>
        </header>

        {error && <div className="error" style={{ padding: "4px 16px" }}>{error}</div>}

        {view === "model" && <ModelView {...shared} />}
        {view === "analytics" && (
          <AnalyticsView workbook={workbook} result={result} leftW={leftW} setLeftW={setLeftW} />
        )}
        {view === "settings" && (
          <SettingsView
            discount={discount}
            onDiscount={setDiscount}
            objScope={objScope}
            onObjScope={setObjScope}
            config={config}
            backend={backend}
            onBackend={setBackend}
            portfolio={portfolio}
            onPortfolio={setPortfolio}
            leftW={leftW}
            setLeftW={setLeftW}
          />
        )}
      </div>
    </div>
  );
}
