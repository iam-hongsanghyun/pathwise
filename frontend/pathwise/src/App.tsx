import { useEffect, useMemo, useState } from "react";
import { getConfig, runToCompletion } from "./api";
import { ActivityBar, type View } from "./layout/ActivityBar";
import { Inspector } from "./layout/Inspector";
import { LeftRail } from "./layout/LeftRail";
import { Resizer } from "./layout/Resizer";
import { FlowCanvas } from "./components/designer/FlowCanvas";
import { WorkbookTable } from "./components/WorkbookTable";
import { AnalyticsView } from "./views/AnalyticsView";
import { SettingsView } from "./views/SettingsView";
import type { ConfigBundle, RunResult, Selection, Workbook } from "./types";
import { downloadResult, downloadWorkbook, exampleWorkbook, parseWorkbookFile } from "./workbook";

export function App() {
  const [config, setConfig] = useState<ConfigBundle | null>(null);
  const [workbook, setWorkbook] = useState<Workbook>(exampleWorkbook());
  const [view, setView] = useState<View>("model");
  const [activeSheet, setActiveSheet] = useState<string>("processes");
  const [discount, setDiscount] = useState(0.08);
  const [result, setResult] = useState<RunResult | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [leftW, setLeftW] = useState(232);
  const [rightW, setRightW] = useState(260);
  const schema = config?.domains[0]?.schema ?? {};
  const railed = view === "model" || view === "data";

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
      setView("analytics");
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(null);
    }
  }

  // The Data view selection jumps the active sheet to the selected entity.
  function select(sel: Selection) {
    setSelected(sel);
    if (view === "data") setActiveSheet(sel.sheet);
  }

  return (
    <div className="studio-shell">
      <ActivityBar view={view} onChange={setView} />
      <div className="workspace">
        <header className="topbar">
          <button className="run-button" onClick={onRun} disabled={running != null}>
            {running ? `▶ Running… (${running})` : "▶ Run"}
          </button>
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
          <button className="ghost" onClick={() => result && downloadResult(result)} disabled={!result}>
            Export result
          </button>
        </header>

        {error && <div className="error" style={{ padding: "4px 16px" }}>{error}</div>}

        <div className="body-row">
          <LeftRail
            workbook={workbook}
            selected={selected}
            onSelect={select}
            draggable={view === "model"}
            width={leftW}
          />
          <Resizer width={leftW} setWidth={setLeftW} side="left" />

          <main className="main-area">
            {view === "model" && (
              <FlowCanvas workbook={workbook} onChange={setWorkbook} onSelect={setSelected} />
            )}

            {view === "data" && (
              <div className="view">
                <div className="sheet-tabs">
                  {sheets.map((sname) => (
                    <button
                      key={sname}
                      className={sname === activeSheet ? "tab active" : "tab"}
                      onClick={() => setActiveSheet(sname)}
                    >
                      {sname}
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

            {view === "analytics" && <AnalyticsView workbook={workbook} result={result} />}

            {view === "settings" && <SettingsView discount={discount} onDiscount={setDiscount} />}
          </main>

          {railed && (
            <>
              <Resizer width={rightW} setWidth={setRightW} side="right" />
              <Inspector
                workbook={workbook}
                selected={selected}
                schema={schema}
                onChange={setWorkbook}
                onClear={() => setSelected(null)}
                width={rightW}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
