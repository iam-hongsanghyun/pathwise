// Project tab — the named workspace that bundles the three layers: project-
// specific Components + Facilities + Value Chain. Name it, export the whole thing
// as one self-contained file, or import one. The name lives on the shared
// workbook's `project` sheet so it travels with the model (and into the bundle).

import { useEffect, useRef, useState } from "react";
import { useDialogs } from "../features/controls/Dialog";
import { SearchSelect } from "../features/controls/SearchSelect";
import { type LibrarySummary, listSessionComponentLibraries } from "../lib/api/components";
import { PROJECT_BUNDLE_FORMAT, type ProjectBundle, downloadProject, importProject } from "../lib/api/project";
import { type ExampleModel, listExamples, loadExample } from "../lib/api/session";
import { getUnits } from "../lib/api/units";
import { modelCurrency, modelDiscount, setModelCurrency, setModelDiscount } from "../lib/caps";
import type { Workbook } from "../types";

interface Props {
  sessionId: string | null;
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  adoptServerModel: (wb: Workbook) => void;
  setError: (e: string | null) => void;
  /** Switch the run method (e.g. an example that declares `backend: "simulate"`). */
  onBackend?: (backend: string) => void;
}

const projectName = (wb: Workbook): string => {
  const v = wb.project?.[0]?.name;
  return v == null ? "" : String(v);
};

export function ProjectView({
  sessionId,
  workbook,
  setWorkbook,
  adoptServerModel,
  setError,
  onBackend,
}: Props) {
  const { confirm, node: dialogNode } = useDialogs();
  const fileRef = useRef<HTMLInputElement>(null);
  const [projLibs, setProjLibs] = useState<LibrarySummary[]>([]);
  const [examples, setExamples] = useState<ExampleModel[]>([]);
  const [busy, setBusy] = useState(false);

  const name = projectName(workbook);
  const setName = (next: string) => setWorkbook({ ...workbook, project: [{ name: next }] });

  // The project's own (session-scoped) component libraries, for the overview count.
  useEffect(() => {
    if (!sessionId) return;
    listSessionComponentLibraries(sessionId)
      .then(setProjLibs)
      .catch(() => setProjLibs([]));
  }, [sessionId, workbook]);

  // Bundled examples — each can be opened as the starting point for a project.
  useEffect(() => {
    listExamples()
      .then(setExamples)
      .catch(() => setExamples([]));
  }, []);

  const nodes = workbook.nodes?.length ?? 0;
  const machines = workbook.machines?.length ?? 0;
  const connections = workbook.connections?.length ?? 0;

  // Project-wide economics (stored on the model `meta` sheet, so they travel).
  const currency = modelCurrency(workbook);
  const discount = modelDiscount(workbook);
  const years = (workbook.periods ?? []).map((r) => Number(r.year)).filter(Number.isFinite);
  const baseYear = years.length ? Math.min(...years) : null;
  const endYear = years.length ? Math.max(...years) : null;
  // Currency choices come from the unit system's `currency` dimension (units.yaml),
  // so they can't drift from the converter. Phase 3 will source this from the
  // project's own unit registry.
  const [currencyOpts, setCurrencyOpts] = useState<string[]>(["USD", "EUR", "KRW"]);
  useEffect(() => {
    let alive = true;
    getUnits()
      .then((u) => {
        const allowed = u.config.dimensions?.currency?.allowed;
        if (alive && allowed?.length) setCurrencyOpts(allowed);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  const currencyChoices = currencyOpts.includes(currency) ? currencyOpts : [currency, ...currencyOpts];

  async function onExport() {
    if (!sessionId) return;
    setError(null);
    setBusy(true);
    try {
      await downloadProject(sessionId, name);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onImportFile(file: File) {
    if (!sessionId) return;
    let bundle: ProjectBundle;
    try {
      bundle = JSON.parse(await file.text()) as ProjectBundle;
    } catch {
      setError("That file isn't valid JSON — pick a .pathwise.json project bundle.");
      return;
    }
    if (bundle?.format !== PROJECT_BUNDLE_FORMAT) {
      setError("That file isn't a pathwise project bundle.");
      return;
    }
    const okToReplace = await confirm({
      title: "Import project",
      message: `Replace the current project with “${bundle.name || "Untitled"}”? This overwrites your working model and project components.`,
      danger: true,
      confirmLabel: "Import",
    });
    if (!okToReplace) return;
    setError(null);
    setBusy(true);
    try {
      const res = await importProject(sessionId, bundle);
      adoptServerModel(res.model);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onLoadExample(exampleId: string) {
    if (!sessionId) return;
    const ex = examples.find((e) => e.id === exampleId);
    const okToReplace = await confirm({
      title: "Open example",
      message: `Start a project from “${ex?.label ?? exampleId}”? This replaces your current working model.`,
      danger: true,
      confirmLabel: "Open",
    });
    if (!okToReplace) return;
    setError(null);
    setBusy(true);
    try {
      const model = await loadExample(sessionId, exampleId);
      adoptServerModel(model);
      // Honour the example's declared run method (e.g. steel_lcia → simulate,
      // petrochemical → macc) so it opens ready to run as intended.
      if (ex?.backend) onBackend?.(ex.backend);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="body-row">
      <main className="main-area" style={{ overflow: "auto", padding: "16px 22px", maxWidth: 720 }}>
        <div className="eyebrow">project</div>
        <h2 className="view-title">Project</h2>
        <p className="view-lead">
          A project is the whole named workspace — its own components, facilities and value chain.
          Name it, then export it as one self-contained file or import one.
        </p>

        <section style={{ marginBottom: 22 }}>
          <h3 className="section-title">Name</h3>
          <input
            className="field-input"
            style={{ width: "100%", maxWidth: 360 }}
            value={name}
            placeholder="Untitled project"
            onChange={(e) => setName(e.target.value)}
          />
        </section>

        <section style={{ marginBottom: 22 }}>
          <h3 className="section-title">Economics</h3>
          <p className="detail-note" style={{ marginBottom: 8 }}>
            Project-wide settings — stored on the model, so they travel with the bundle and drive
            every run.
          </p>
          <div className="field-grid" style={{ maxWidth: 360, alignItems: "center", gap: "8px 12px" }}>
            <span className="muted">currency</span>
            <SearchSelect
              value={currency}
              onChange={(v) => v && setWorkbook(setModelCurrency(workbook, v))}
              options={currencyChoices.map((c) => ({ value: c }))}
            />
            <span className="muted">discount rate</span>
            <input
              className="field-input"
              type="number"
              step="0.01"
              min={0}
              max={0.99}
              value={discount}
              onChange={(e) => setWorkbook(setModelDiscount(workbook, Math.max(0, Number(e.target.value) || 0)))}
            />
            <span className="muted">horizon</span>
            <span>{baseYear != null ? `${baseYear}–${endYear} (annual)` : "set periods in the model"}</span>
          </div>
          <p className="muted" style={{ fontSize: ".74rem", marginTop: 8 }}>
            Currency is the unit every monetary value is shown in (relabels only; cross-rates live in
            the unit registry). Discount rate sets NPV. Runs are annual — one snapshot per period.
          </p>
        </section>

        <section style={{ marginBottom: 22 }}>
          <h3 className="section-title">Start from an example</h3>
          <p className="detail-note" style={{ marginBottom: 8 }}>
            Open a bundled example as a project — its full value chain, facilities and components.
            You can then rename it, edit it, and export it as your own bundle.
          </p>
          <div style={{ maxWidth: 360 }}>
            <SearchSelect
              value=""
              onChange={(v) => v && void onLoadExample(v)}
              options={examples.map((e) => ({ value: e.id, label: e.label }))}
              placeholder="open an example…"
            />
          </div>
        </section>

        <section style={{ marginBottom: 22 }}>
          <h3 className="section-title">Bundle</h3>
          <p className="detail-note" style={{ marginBottom: 8 }}>
            Export bundles the model with every component it uses — project-specific and the base
            components it references — so it re-opens anywhere. Import replaces the current project.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="run-button" disabled={busy || !sessionId} onClick={onExport}>
              ↓ Export project
            </button>
            <button
              className="ghost"
              disabled={busy || !sessionId}
              onClick={() => fileRef.current?.click()}
            >
              ↑ Import project
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="application/json,.json"
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) void onImportFile(f);
              }}
            />
          </div>
        </section>

        <section>
          <h3 className="section-title">Contents</h3>
          <div className="field-grid" style={{ maxWidth: 300 }}>
            <span className="muted">project components</span>
            <span>
              {projLibs.length} {projLibs.length === 1 ? "library" : "libraries"}
            </span>
            <span className="muted">facility nodes</span>
            <span>{nodes}</span>
            <span className="muted">machines</span>
            <span>{machines}</span>
            <span className="muted">connections</span>
            <span>{connections}</span>
          </div>
        </section>
      </main>
      {dialogNode}
    </div>
  );
}
