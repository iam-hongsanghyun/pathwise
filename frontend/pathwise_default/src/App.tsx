import { useEffect, useMemo, useState } from "react";
import {
  exportXlsx,
  getConfig,
  parseWorkbook,
  runToCompletion,
  validate,
} from "./api";
import { WorkbookTable } from "./components/WorkbookTable";
import type {
  ConfigBundle,
  DomainCapability,
  RunResult,
  Scenario,
  ValidationResult,
  Workbook,
} from "./types";

const FEATURE_LABELS: Record<string, string> = {
  include_transitions: "Technology transitions",
  include_measures: "MACC measures",
  include_new_build: "New builds",
  include_carbon_price: "Carbon price",
  include_capex: "Capital cost",
};

export function App() {
  const [config, setConfig] = useState<ConfigBundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [domainId, setDomainId] = useState<string>("");
  const [workbook, setWorkbook] = useState<Workbook>({});
  const [activeSheet, setActiveSheet] = useState<string>("");
  const [scenario, setScenario] = useState<Scenario>(defaultScenario());
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [running, setRunning] = useState<string | null>(null);

  useEffect(() => {
    getConfig()
      .then((cfg) => {
        setConfig(cfg);
        setDomainId(cfg.defaults.domain);
        setScenario((s) => ({ ...s, domain: cfg.defaults.domain, economics: { ...s.economics, discount_rate: cfg.defaults.discountRate } }));
      })
      .catch((e) => setError(String(e)));
  }, []);

  const domain: DomainCapability | undefined = useMemo(
    () => config?.domains.find((d) => d.name === domainId),
    [config, domainId],
  );

  const sheetNames = Object.keys(workbook);

  async function onUpload(file: File) {
    setError(null);
    try {
      const wb = await parseWorkbook(file);
      setWorkbook(wb);
      setActiveSheet(Object.keys(wb)[0] ?? "");
      setResult(null);
      setValidation(null);
    } catch (e) {
      setError(String(e));
    }
  }

  async function onValidate() {
    setError(null);
    try {
      setValidation(await validate(workbook, { ...scenario, domain: domainId }, { domain: domainId }));
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
        { ...scenario, domain: domainId },
        { domain: domainId },
        (status) => setRunning(status),
      );
      setResult(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(null);
    }
  }

  async function onExport() {
    if (!result) return;
    const blob = await exportXlsx(result);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "pathwise_result.xlsx";
    a.click();
    URL.revokeObjectURL(url);
  }

  if (error && !config) return <div className="app error">Failed to load: {error}</div>;
  if (!config) return <div className="app">Loading…</div>;

  return (
    <div className="app">
      <header>
        <h1>pathwise</h1>
        <span className="muted">
          v{config.version} · build {config.buildId}
        </span>
      </header>

      <section className="controls">
        <label>
          Sector
          <select value={domainId} onChange={(e) => setDomainId(e.target.value)}>
            {config.domains.map((d) => (
              <option key={d.name} value={d.name}>
                {d.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          Workbook
          <input
            type="file"
            accept=".xlsx"
            onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])}
          />
        </label>

        <label>
          Target set
          <input
            value={scenario.selection.target_set ?? ""}
            placeholder="e.g. Tier1"
            onChange={(e) => setScenario({ ...scenario, selection: { target_set: e.target.value } })}
          />
        </label>

        <label>
          Discount rate
          <input
            type="number"
            step="0.01"
            value={scenario.economics.discount_rate}
            onChange={(e) =>
              setScenario({
                ...scenario,
                economics: { ...scenario.economics, discount_rate: Number(e.target.value) },
              })
            }
          />
        </label>

        <label>
          CAPEX
          <select
            value={scenario.economics.capex_convention}
            onChange={(e) =>
              setScenario({
                ...scenario,
                economics: { ...scenario.economics, capex_convention: e.target.value as "annuity" | "npv" },
              })
            }
          >
            <option value="annuity">Annuity (CRF)</option>
            <option value="npv">NPV lump</option>
          </select>
        </label>
      </section>

      <section className="features">
        {Object.entries(FEATURE_LABELS).map(([key, label]) => (
          <label key={key} className="checkbox">
            <input
              type="checkbox"
              checked={scenario.features[key] ?? true}
              onChange={(e) =>
                setScenario({ ...scenario, features: { ...scenario.features, [key]: e.target.checked } })
              }
            />
            {label}
          </label>
        ))}
      </section>

      <section className="actions">
        <button onClick={onValidate} disabled={sheetNames.length === 0}>
          Validate
        </button>
        <button onClick={onRun} disabled={sheetNames.length === 0 || running != null}>
          {running ? `Running… (${running})` : "Run optimisation"}
        </button>
        <button onClick={onExport} disabled={!result}>
          Export .xlsx
        </button>
      </section>

      {error && <div className="error">{error}</div>}
      {validation && <ValidationView v={validation} />}

      {sheetNames.length > 0 && (
        <section className="workbook">
          <div className="tabs">
            {sheetNames.map((s) => (
              <button
                key={s}
                className={s === activeSheet ? "tab active" : "tab"}
                onClick={() => setActiveSheet(s)}
              >
                {domain?.schema[s]?.label ?? s}
              </button>
            ))}
          </div>
          {activeSheet && (
            <WorkbookTable
              sheet={activeSheet}
              rows={workbook[activeSheet]}
              onChange={(rows) => setWorkbook({ ...workbook, [activeSheet]: rows })}
            />
          )}
        </section>
      )}

      {result && <ResultsView result={result} />}
    </div>
  );
}

function ValidationView({ v }: { v: ValidationResult }) {
  return (
    <div className={v.ok ? "validation ok" : "validation bad"}>
      <strong>{v.ok ? "Valid ✓" : "Validation errors"}</strong>
      <ul>
        {v.errors.map((e, i) => (
          <li key={`e${i}`} className="error-item">
            {e}
          </li>
        ))}
        {v.warnings.map((w, i) => (
          <li key={`w${i}`} className="warn-item">
            {w}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ResultsView({ result }: { result: RunResult }) {
  const term = result.terminology;
  return (
    <section className="results">
      <h2>
        Result — {result.status}
        {result.objective != null && (
          <span className="muted"> · objective {result.objective.toLocaleString()}</span>
        )}
      </h2>

      <h3>Per-{term.period ?? "period"} summary</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{term.period ?? "Period"}</th>
              <th>Energy (MJ)</th>
              <th>Emissions (tCO2e)</th>
              <th>Intensity (gCO2e/MJ)</th>
            </tr>
          </thead>
          <tbody>
            {result.summary.periods.map((p) => (
              <tr key={p.period}>
                <td>{p.period}</td>
                <td>{p.energy_mj.toLocaleString()}</td>
                <td>{p.emissions_tco2e.toFixed(2)}</td>
                <td>{p.intensity_gco2e_per_mj.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {result.outputs.transitions.length > 0 && (
        <>
          <h3>{term.technology ?? "Technology"} transitions</h3>
          <ul>
            {result.outputs.transitions.map((t, i) => (
              <li key={i}>
                {t.asset} → {t.to_technology} in {t.period}
              </li>
            ))}
          </ul>
        </>
      )}

      {result.outputs.slack.length > 0 && (
        <div className="warn-item">
          ⚠ Slack used (target/demand could not be fully met):{" "}
          {result.outputs.slack.map((s) => `${s.kind}@${s.group}/${s.period}`).join(", ")}
        </div>
      )}
    </section>
  );
}

function defaultScenario(): Scenario {
  return {
    name: "scenario",
    domain: "shipping",
    selection: { target_set: "Tier1" },
    economics: { discount_rate: 0.08, base_period: 2025, capex_convention: "annuity" },
    features: {
      include_transitions: true,
      include_measures: true,
      include_new_build: true,
      include_carbon_price: true,
      include_capex: true,
    },
  };
}
