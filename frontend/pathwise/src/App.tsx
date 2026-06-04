import { useEffect, useMemo, useState } from "react";
import { getConfig, runToCompletion } from "./api";
import { FacilityDesigner } from "./components/FacilityDesigner";
import { MaccDesigner } from "./components/MaccDesigner";
import { ResultsView } from "./components/ResultsView";
import { TransitionDesigner } from "./components/TransitionDesigner";
import { WorkbookTable } from "./components/WorkbookTable";
import type { ConfigBundle, RunResult, Workbook } from "./types";
import { downloadResult, downloadWorkbook, exampleWorkbook, parseWorkbookFile } from "./workbook";

type Tab = "designer" | "macc" | "transitions" | "tables" | "results";
const TABS: { id: Tab; label: string }[] = [
  { id: "designer", label: "Facility designer" },
  { id: "macc", label: "MACC" },
  { id: "transitions", label: "Transitions" },
  { id: "tables", label: "Tables" },
  { id: "results", label: "Results" },
];

export function App() {
  const [config, setConfig] = useState<ConfigBundle | null>(null);
  const [workbook, setWorkbook] = useState<Workbook>(exampleWorkbook());
  const [tab, setTab] = useState<Tab>("designer");
  const [activeSheet, setActiveSheet] = useState<string>("processes");
  const [discount, setDiscount] = useState(0.08);
  const [result, setResult] = useState<RunResult | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      setTab("results");
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(null);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>pathwise</h1>
        <span className="muted">
          process-network optimiser{config ? ` · v${config.version} · build ${config.buildId}` : ""}
        </span>
      </header>

      <section className="controls">
        <label>
          Model
          <input type="file" accept=".xlsx" onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])} />
        </label>
        <button className="ghost" onClick={() => setWorkbook(exampleWorkbook())}>
          Load example
        </button>
        <button className="ghost" onClick={() => downloadWorkbook(workbook)}>
          Export model
        </button>
        <label>
          Discount
          <input
            type="number"
            step="0.01"
            value={discount}
            onChange={(e) => setDiscount(Number(e.target.value))}
          />
        </label>
        <button onClick={onRun} disabled={running != null}>
          {running ? `Running… (${running})` : "Optimise"}
        </button>
        <button className="ghost" onClick={() => result && downloadResult(result)} disabled={!result}>
          Export result
        </button>
      </section>

      {error && <div className="error">{error}</div>}

      <nav className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={t.id === tab ? "tab active" : "tab"} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "designer" && <FacilityDesigner workbook={workbook} onChange={setWorkbook} />}
      {tab === "macc" && <MaccDesigner workbook={workbook} />}
      {tab === "transitions" && <TransitionDesigner workbook={workbook} onChange={setWorkbook} />}
      {tab === "tables" && (
        <div className="tables">
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
      {tab === "results" &&
        (result ? <ResultsView result={result} /> : <p className="muted">Run an optimisation to see results.</p>)}
    </div>
  );
}
