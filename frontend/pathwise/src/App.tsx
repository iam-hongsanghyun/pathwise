import { useEffect, useState } from "react";
import { getConfig, runToCompletion } from "./api";
import { ActivityBar, type View } from "./layout/ActivityBar";
import { AnalyticsView } from "./views/AnalyticsView";
import { ModelView } from "./views/ModelView";
import { SettingsView } from "./views/SettingsView";
import type { ConfigBundle, RunResult, Workbook } from "./types";
import { downloadResult, downloadWorkbook, exampleWorkbook, parseWorkbookFile } from "./workbook";

export function App() {
  const [config, setConfig] = useState<ConfigBundle | null>(null);
  const [workbook, setWorkbook] = useState<Workbook>(exampleWorkbook());
  const [view, setView] = useState<View>("model");
  const [discount, setDiscount] = useState(0.08);
  const [result, setResult] = useState<RunResult | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [leftW, setLeftW] = useState(232);

  useEffect(() => {
    getConfig()
      .then(setConfig)
      .catch((e) => setError(String(e)));
  }, []);

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
      const res = await runToCompletion(
        workbook,
        { domain: "process", economics: { discount_rate: discount } },
        { domain: "process" },
        setRunning,
      );
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
            Model
            <input
              type="file"
              accept=".xlsx"
              onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])}
            />
          </label>
          <button className="ghost" onClick={() => setWorkbook(exampleWorkbook())}>
            Example
          </button>
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
          <SettingsView discount={discount} onDiscount={setDiscount} leftW={leftW} setLeftW={setLeftW} />
        )}
      </div>
    </div>
  );
}
