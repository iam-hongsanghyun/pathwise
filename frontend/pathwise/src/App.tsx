import { useEffect, useMemo, useState } from "react";
import { getConfig, runToCompletion } from "./api";
import { ActivityBar, type View } from "./layout/ActivityBar";
import { Inspector } from "./layout/Inspector";
import { LeftRail } from "./layout/LeftRail";
import { FlowCanvas } from "./components/designer/FlowCanvas";
import { MaccDesigner } from "./components/MaccDesigner";
import { ResultsView } from "./components/ResultsView";
import { WorkbookTable } from "./components/WorkbookTable";
import { SettingsView } from "./views/SettingsView";
import type { ConfigBundle, RunResult, Selection, Workbook } from "./types";
import { downloadResult, downloadWorkbook, exampleWorkbook, parseWorkbookFile } from "./workbook";

export function App() {
  const [config, setConfig] = useState<ConfigBundle | null>(null);
  const [workbook, setWorkbook] = useState<Workbook>(exampleWorkbook());
  const [view, setView] = useState<View>("designer");
  const [activeSheet, setActiveSheet] = useState<string>("processes");
  const [discount, setDiscount] = useState(0.08);
  const [result, setResult] = useState<RunResult | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Selection | null>(null);
  const schema = config?.domains[0]?.schema ?? {};

  useEffect(() => {
    getConfig()
      .then(setConfig)
      .catch((e) => setError(String(e)));
  }, []);

  const sheets = useMemo(() => Object.keys(workbook), [workbook]);

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
      setView("results");
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(null);
    }
  }

  return (
    <div className="studio-shell">
      <ActivityBar view={view} onChange={setView} />
      <div className="workspace">
        <header className="topbar">
          <div>
            <div className="eyebrow">process-network optimiser</div>
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
          <button onClick={onRun} disabled={running != null}>
            {running ? `Running… (${running})` : "Optimise"}
          </button>
          <button className="ghost" onClick={() => result && downloadResult(result)} disabled={!result}>
            Export result
          </button>
        </header>

        {error && <div className="error" style={{ padding: "4px 16px" }}>{error}</div>}

        <div className="body-row">
          <LeftRail workbook={workbook} selected={selected} onSelect={setSelected} />

          <main className="main-area">
            {view === "designer" && (
              <FlowCanvas workbook={workbook} onChange={setWorkbook} onSelect={setSelected} />
            )}

            {view === "tables" && (
              <div className="view">
                <div className="sheet-tabs">
                  {sheets.map((s) => (
                    <button
                      key={s}
                      className={s === activeSheet ? "tab active" : "tab"}
                      onClick={() => setActiveSheet(s)}
                    >
                      {s}
                    </button>
                  ))}
                </div>
                {workbook[activeSheet] && (
                  <WorkbookTable
                    rows={workbook[activeSheet]}
                    onChange={(rows) => setWorkbook({ ...workbook, [activeSheet]: rows })}
                  />
                )}
              </div>
            )}

            {view === "macc" && (
              <div className="view">
                <MaccDesigner workbook={workbook} />
              </div>
            )}

            {view === "results" && (
              <div className="view">
                {result ? (
                  <ResultsView result={result} />
                ) : (
                  <p className="muted">Run an optimisation to see results.</p>
                )}
              </div>
            )}

            {view === "settings" && (
              <SettingsView
                workbook={workbook}
                onChange={setWorkbook}
                discount={discount}
                onDiscount={setDiscount}
              />
            )}
          </main>

          <Inspector
            workbook={workbook}
            selected={selected}
            schema={schema}
            onChange={setWorkbook}
            onClear={() => setSelected(null)}
          />
        </div>
      </div>
    </div>
  );
}
