import { useEffect, useRef, useState } from "react";
import { getConfig } from "./lib/api/run";
import {
  clearCache,
  clearModel,
  downloadResultSqlite,
  ensureSession,
  exportModelUrl,
  putModel,
  replaceSheet,
  uploadWorkbook,
} from "./lib/api/session";
import { type LibraryEntry, type LibraryTier, importLibrary, listLibraries } from "./lib/api/libraries";
import { SearchSelect } from "./features/controls/SearchSelect";
import { ActivityBar, type View } from "./layout/ActivityBar";
import { AnalyticsView } from "./views/AnalyticsView";
import { ComponentTabView } from "./views/ComponentTabView";
import { SettingsView } from "./views/SettingsView";
import { ValueChainTabView } from "./views/ValueChainTabView";
import type { ConfigBundle, PortfolioConfig, RunResult, Workbook } from "./types";

export function App() {
  const [config, setConfig] = useState<ConfigBundle | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [workbook, setWorkbook] = useState<Workbook>({});
  // The last model state known to be on the backend; sheet-level reference
  // equality against this drives the debounced patch sync below.
  const synced = useRef<Workbook>({});
  const [view, setView] = useState<View>("valuechain");
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
  // Run status lives here (not in the view) so switching tabs mid-run doesn't
  // unmount the view and reset the ▶ Run button while the job is still going.
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [leftW, setLeftW] = useState(232);
  const [libraries, setLibraries] = useState<LibraryEntry[]>([]);

  // Boot: config handshake + a backend session (the model's source of truth).
  useEffect(() => {
    getConfig()
      .then(setConfig)
      .catch((e) => setError(String(e)));
    listLibraries()
      .then(setLibraries)
      .catch(() => setLibraries([]));
    ensureSession()
      .then(({ sessionId: sid, model }) => {
        synced.current = model;
        setSessionId(sid);
        setWorkbook(model);
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Bounded undo history of workbook states (model edits + server-side ops).
  const history = useRef<Workbook[]>([]);
  const pushHistory = (state: Workbook) => {
    if (Object.keys(state).length === 0) return; // skip the pre-boot blank
    history.current = [...history.current.slice(-19), state];
  };

  /** The single edit entry point: records undo history, then updates state
   *  (the debounced effect syncs the change to the backend session). */
  const updateWorkbook = (wb: Workbook) => {
    pushHistory(workbook);
    setWorkbook(wb);
  };

  const undo = () => {
    const prev = history.current.pop();
    if (prev) setWorkbook(prev); // sync effect pushes the restored state
  };

  // Ctrl/Cmd+Z anywhere outside a text field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.key === "z" && (e.metaKey || e.ctrlKey) && !e.shiftKey)) return;
      const tag = (e.target as HTMLElement | null)?.tagName ?? "";
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      e.preventDefault();
      undo();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Adopt a model the BACKEND already holds (upload / example / template). */
  const adoptServerModel = (model: Workbook) => {
    pushHistory(workbook); // server-side ops are undoable too
    synced.current = model;
    setWorkbook(model);
    setResult(null);
  };

  /** Push local edits to the session: per-sheet patches, or a full put when
   *  sheets were added/removed. Returns once the backend is current. */
  async function syncNow(): Promise<void> {
    if (!sessionId || workbook === synced.current) return;
    const prev = synced.current;
    const structural =
      Object.keys(workbook).some((s) => !(s in prev)) ||
      Object.keys(prev).some((s) => !(s in workbook));
    synced.current = workbook;
    if (structural) {
      await putModel(sessionId, workbook);
      return;
    }
    const changed = Object.entries(workbook).filter(([sheet, rows]) => prev[sheet] !== rows);
    await Promise.all(changed.map(([sheet, rows]) => replaceSheet(sessionId, sheet, rows)));
  }

  // Debounced edit sync — the browser is a thin cache; the session is truth.
  useEffect(() => {
    if (!sessionId || workbook === synced.current) return;
    const t = setTimeout(() => {
      syncNow().catch((e) => setError(String(e)));
    }, 600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workbook, sessionId]);

  /** Import a tiered library by its "tier/id" key. A library with a value chain
   *  rebuilds the session model (→ Value-chain view); a components-only library
   *  (the `base` building blocks) just stocks the session catalogue (→ Component
   *  view). Either way its components land in the Component view. */
  async function onPickLibrary(key: string) {
    if (!sessionId) return;
    const slash = key.indexOf("/");
    const tier = key.slice(0, slash) as LibraryTier;
    const id = key.slice(slash + 1);
    setError(null);
    try {
      const res = await importLibrary(sessionId, tier, id);
      adoptServerModel(res.model);
      setView(res.imported_value_chain ? "valuechain" : "component");
    } catch (e) {
      setError(String(e));
    }
  }

  async function onUpload(file: File) {
    if (!sessionId) return;
    setError(null);
    try {
      adoptServerModel(await uploadWorkbook(sessionId, file));
    } catch (e) {
      setError(String(e));
    }
  }

  /** A standard (joint) run result from the Value-Chain builder → Analytics. */
  function onJointResult(res: RunResult) {
    setResult(res);
    setView("analytics");
  }

  async function onNewModel() {
    if (!sessionId) return;
    setError(null);
    try {
      adoptServerModel(await clearModel(sessionId)); // undoable: history is pushed
    } catch (e) {
      setError(String(e));
    }
  }

  /** Wipe all working session data (sessions + session libraries) and adopt the
   *  fresh empty session the server returns. NOT undoable — clears the cache. */
  async function onClearCache() {
    setError(null);
    try {
      const { sessionId: sid, model } = await clearCache();
      setSessionId(sid);
      synced.current = model;
      setWorkbook(model);
      setResult(null);
      setBackend("linopy");
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="studio-shell">
      <ActivityBar view={view} onChange={setView} />
      <div className="workspace">
        <header className="topbar">
          <div>
            <div className="eyebrow">process value-chain optimiser</div>
            <h1>pathwise{config ? ` · build ${config.buildId}` : ""}</h1>
          </div>
          <button
            className="ghost"
            onClick={undo}
            title="undo the last model change (Ctrl/Cmd+Z)"
          >
            ↩ Undo
          </button>
          <button
            className="ghost"
            onClick={onNewModel}
            disabled={!sessionId}
            title="clear the session and start from an empty model (undoable)"
          >
            ✕ New model
          </button>
          <button
            className="ghost"
            onClick={onClearCache}
            title="wipe ALL working session data (sessions + session libraries) and start fresh — not undoable"
          >
            🧹 Clear cache
          </button>
          <span className="spacer" />
          <label>
            Library
            <span style={{ display: "inline-block", width: 300 }}>
              <SearchSelect
                value=""
                onChange={(v) => v && onPickLibrary(v)}
                disabled={libraries.length === 0}
                placeholder={libraries.length ? "Import a library…" : "no libraries"}
                options={libraries.map((l) => ({
                  value: `${l.tier}/${l.id}`,
                  label: `${l.tier[0].toUpperCase()}${l.tier.slice(1)} · ${l.label}${
                    l.has_value_chain ? "" : " (components)"
                  }`,
                }))}
              />
            </span>
          </label>
          <label>
            Upload
            <input
              type="file"
              accept=".xlsx"
              onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])}
            />
          </label>
          <button
            className="ghost"
            disabled={!sessionId}
            onClick={async () => {
              await syncNow().catch((e) => setError(String(e)));
              if (sessionId) window.location.assign(exportModelUrl(sessionId));
            }}
          >
            Export model
          </button>
          <button
            className="ghost"
            onClick={() => result && downloadResultSqlite(result).catch((e) => setError(String(e)))}
            disabled={!result}
            title="Download the full result as SQLite — one table per output, by year"
          >
            Export result
          </button>
        </header>

        {error && <div className="error" style={{ padding: "4px 16px" }}>{error}</div>}

        {view === "component" && <ComponentTabView sessionId={sessionId} />}
        {view === "valuechain" && (
          <ValueChainTabView
            workbook={workbook}
            setWorkbook={updateWorkbook}
            sessionId={sessionId}
            adoptServerModel={adoptServerModel}
            onJointResult={onJointResult}
            backend={backend}
            running={running}
            setRunning={setRunning}
            libraries={libraries}
            onPickLibrary={onPickLibrary}
          />
        )}
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
