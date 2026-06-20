// Optimisation cockpit — define the whole run here: the OBJECTIVE (minimise cost /
// maximise profit, system-wide or per-company), a fully flexible list of CONSTRAINTS
// (any stream/impact/budget × any scope × produce-target / minimum / maximum), and
// the RUN button. Constraints are stored in their native backend sheets (demand,
// min_production, max_production, impact_caps, investment_budget); this view gathers
// them into one editable list and scatters edits back. Edits debounce-sync via the host.

import { useMemo, useState } from "react";
import { SearchSelect } from "../features/controls/SearchSelect";
import { impactIds, productIds, scopeOptions } from "../lib/scope";
import type { Row, Workbook } from "../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const n = (v: unknown): number => (v == null || v === "" ? 0 : Number(v) || 0);
const setSheets = (wb: Workbook, sheets: Record<string, Row[]>): Workbook => ({ ...wb, ...sheets });

type Kind = "production" | "emission" | "budget";

// (kind, type) → the backend sheet + which column holds the target id / the value.
const MAP: Record<string, { sheet: string; target?: string; value: string }> = {
  "production:produce": { sheet: "demand", target: "commodity_id", value: "amount" },
  "production:min": { sheet: "min_production", target: "commodity_id", value: "amount" },
  "production:max": { sheet: "max_production", target: "commodity_id", value: "amount" },
  "emission:cap": { sheet: "impact_caps", target: "impact_id", value: "limit" },
  "budget:cap": { sheet: "investment_budget", value: "limit" },
};
const CONSTRAINT_SHEETS = ["demand", "min_production", "max_production", "impact_caps", "investment_budget"];
const KIND_OPTS = [
  { value: "production", label: "Production" },
  { value: "emission", label: "Emission" },
  { value: "budget", label: "Budget" },
];
const TYPE_OPTS: Record<Kind, { value: string; label: string }[]> = {
  production: [
    { value: "produce", label: "Target (produce)" },
    { value: "min", label: "Minimum" },
    { value: "max", label: "Maximum" },
  ],
  emission: [{ value: "cap", label: "Cap (max)" }],
  budget: [{ value: "cap", label: "Cap (max)" }],
};

/** One row of the unified constraint list. `extra` carries sheet-specific columns
 *  (e.g. impact_caps' soft/penalty/intensity) so scatter round-trips them. */
interface UC {
  kind: Kind;
  type: string;
  target: string;
  scope: string;
  value: number;
  year: number;
  extra: Row;
}

const MAPPED_KEYS = new Set(["company", "year", "commodity_id", "impact_id", "amount", "limit"]);

function gather(wb: Workbook): UC[] {
  const out: UC[] = [];
  for (const [key, m] of Object.entries(MAP)) {
    const [kind, type] = key.split(":") as [Kind, string];
    for (const r of wb[m.sheet] ?? []) {
      const extra: Row = {};
      for (const [k, v] of Object.entries(r)) if (!MAPPED_KEYS.has(k)) extra[k] = v;
      out.push({
        kind,
        type,
        target: m.target ? s(r[m.target]) : "",
        scope: s(r.company) || "all",
        value: n(r[m.value]),
        year: n(r.year),
        extra,
      });
    }
  }
  return out;
}

/** Inverse of gather: regroup the unified list back into the native sheets. */
function scatter(rows: UC[]): Record<string, Row[]> {
  const out: Record<string, Row[]> = Object.fromEntries(CONSTRAINT_SHEETS.map((sh) => [sh, []]));
  for (const c of rows) {
    const m = MAP[`${c.kind}:${c.type}`];
    if (!m) continue;
    const row: Row = { ...c.extra, company: c.scope, year: c.year, [m.value]: c.value };
    if (m.target) row[m.target] = c.target;
    out[m.sheet].push(row);
  }
  return out;
}

export function TargetsTabView({
  workbook,
  setWorkbook,
  onRun,
  running,
  canRun,
}: {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  onRun: (scenario: Record<string, unknown>) => void;
  running: string | null;
  canRun: boolean;
}) {
  const scopes = useMemo(() => scopeOptions(workbook), [workbook]);
  const products = useMemo(() => productIds(workbook), [workbook]);
  const impacts = useMemo(() => impactIds(workbook), [workbook]);
  const years = useMemo(
    () => (workbook.periods ?? []).map((r) => Number(r.year)).filter(Number.isFinite),
    [workbook],
  );
  const baseYear = years.length ? Math.min(...years) : 2025;
  const endYear = years.length ? Math.max(...years) : baseYear;

  // ── Objective (goal × scope) ────────────────────────────────────────────────
  const [goal, setGoal] = useState<"cost" | "profit">("cost");
  const [perCompany, setPerCompany] = useState(false);

  // ── Constraints (unified) ───────────────────────────────────────────────────
  const rows = useMemo(() => gather(workbook), [workbook]);
  const commit = (next: UC[]) => setWorkbook(setSheets(workbook, scatter(next)));
  const patch = (i: number, p: Partial<UC>) =>
    commit(rows.map((r, j) => (j === i ? normalise({ ...r, ...p }) : r)));
  const add = () =>
    commit([
      ...rows,
      { kind: "production", type: "produce", target: products[0] ?? "", scope: "all", value: 100, year: baseYear, extra: {} },
    ]);
  const del = (i: number) => commit(rows.filter((_, j) => j !== i));

  // Keep type/target valid when the kind changes.
  function normalise(c: UC): UC {
    const types = TYPE_OPTS[c.kind].map((t) => t.value);
    const type = types.includes(c.type) ? c.type : types[0];
    let target = c.target;
    if (c.kind === "emission") target = impacts.includes(target) ? target : (impacts[0] ?? "");
    else if (c.kind === "production") target = products.includes(target) ? target : (products[0] ?? "");
    else target = "";
    return { ...c, type, target };
  }

  function run() {
    onRun({
      economics: { base_year: baseYear },
      horizon: { start: baseYear, end: endYear },
      optimisation_scope: perCompany ? "company" : "system",
      optimisation_mode: perCompany ? "independent" : "joint",
      objective: goal,
    });
  }

  const targetOpts = (k: Kind) => (k === "emission" ? impacts : k === "production" ? products : []);
  const cell: React.CSSProperties = { padding: "2px 4px" };
  const small = { minWidth: 120 };

  return (
    <div className="body-row">
      <main className="main-area" style={{ overflow: "auto", padding: "16px 22px", maxWidth: 980 }}>
        <div className="eyebrow">optimisation</div>
        <h2 className="view-title">Optimisation</h2>
        <p className="view-lead">
          Define the whole run here — the objective, any number of constraints, then ▶ Run.
        </p>

        {/* Objective */}
        <section style={{ marginBottom: 22 }}>
          <h3 className="section-title">Objective</h3>
          <div style={{ display: "flex", gap: 18, alignItems: "center", flexWrap: "wrap" }}>
            <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ fontSize: "0.8rem", fontWeight: 600 }}>Goal</span>
              <div style={small}>
                <SearchSelect
                  value={goal}
                  onChange={(v) => setGoal(v as "cost" | "profit")}
                  options={[
                    { value: "cost", label: "Minimise cost" },
                    { value: "profit", label: "Maximise profit" },
                  ]}
                />
              </div>
            </label>
            <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ fontSize: "0.8rem", fontWeight: 600 }}>Solve</span>
              <div style={small}>
                <SearchSelect
                  value={perCompany ? "company" : "system"}
                  onChange={(v) => setPerCompany(v === "company")}
                  options={[
                    { value: "system", label: "Whole system (one problem)" },
                    { value: "company", label: "Each company (independent)" },
                  ]}
                />
              </div>
            </label>
            <span className="muted" style={{ fontSize: "0.74rem" }}>
              horizon {baseYear}–{endYear}
            </span>
          </div>
        </section>

        {/* Constraints */}
        <section style={{ marginBottom: 22 }}>
          <h3 className="section-title" style={{ marginBottom: 2 }}>Constraints</h3>
          <p className="muted" style={{ fontSize: "0.74rem", margin: "0 0 8px" }}>
            Each row: pick what (a stream's production, an emission, or the budget), the scope it
            applies to, whether it's a target / minimum / maximum, the value and the year. Add as many
            as you like.
          </p>
          <button className="ghost" style={{ marginBottom: 8 }} onClick={add}>
            ＋ add constraint
          </button>
          {rows.length === 0 ? (
            <p className="muted" style={{ fontSize: "0.78rem" }}>No constraints yet — ＋ add one.</p>
          ) : (
            <table className="grid" style={{ width: "100%", fontSize: "0.76rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                  <th>what</th>
                  <th>target</th>
                  <th>scope</th>
                  <th>type</th>
                  <th>value</th>
                  <th>year</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td style={cell}>
                      <SearchSelect value={r.kind} onChange={(v) => patch(i, { kind: v as Kind })} options={KIND_OPTS} />
                    </td>
                    <td style={cell}>
                      {r.kind === "budget" ? (
                        <span className="muted">—</span>
                      ) : (
                        <SearchSelect
                          value={r.target}
                          onChange={(v) => patch(i, { target: v })}
                          options={targetOpts(r.kind).map((o) => ({ value: o }))}
                        />
                      )}
                    </td>
                    <td style={cell}>
                      <SearchSelect value={r.scope} onChange={(v) => patch(i, { scope: v })} options={scopes} />
                    </td>
                    <td style={cell}>
                      <SearchSelect value={r.type} onChange={(v) => patch(i, { type: v })} options={TYPE_OPTS[r.kind]} />
                    </td>
                    <td style={cell}>
                      <input
                        type="number"
                        value={r.value}
                        onChange={(e) => patch(i, { value: n(e.target.value) })}
                        style={{ width: 90, padding: "3px 5px", border: "1px solid var(--border-strong)", borderRadius: "var(--radius-button)", font: "inherit" }}
                      />
                    </td>
                    <td style={cell}>
                      <input
                        type="number"
                        value={r.year}
                        onChange={(e) => patch(i, { year: Math.round(n(e.target.value)) })}
                        style={{ width: 70, padding: "3px 5px", border: "1px solid var(--border-strong)", borderRadius: "var(--radius-button)", font: "inherit" }}
                      />
                    </td>
                    <td>
                      <button className="ghost" title="remove" onClick={() => del(i)}>✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* Run */}
        <section style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          <button className="run-button" onClick={run} disabled={running != null || !canRun}>
            {running ? `▶ ${running}…` : "▶ Run"}
          </button>
          <span className="muted" style={{ fontSize: "0.74rem", marginLeft: 10 }}>
            Solves {goal === "cost" ? "least-cost" : "max-profit"},{" "}
            {perCompany ? "per company" : "whole system"}, over {baseYear}–{endYear}.
          </span>
        </section>
      </main>
    </div>
  );
}
