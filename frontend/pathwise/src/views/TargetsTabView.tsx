// Optimisation cockpit — define the whole run here: the OBJECTIVE (minimise cost /
// maximise profit, system-wide or per-company), a fully flexible list of CONSTRAINTS
// (any stream/impact/budget × any scope × produce-target / minimum / maximum), and
// the RUN button. Constraints are stored in their native backend sheets (demand,
// min_production, max_production, impact_caps, investment_budget); this view gathers
// them into one editable list and scatters edits back. Edits debounce-sync via the host.

import { useMemo, useState } from "react";
import { SearchSelect } from "../features/controls/SearchSelect";
import { TemporalValue, type TemporalVal } from "../features/controls/TemporalValue";
import { commodityUnit, impactUnit, modelCurrency } from "../lib/caps";
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

/** One row of the unified constraint list — ONE per (kind, type, target, scope),
 *  with a value that is static (a number, every year) or temporal (by-year).
 *  `extra` carries sheet-specific columns (e.g. impact_caps' soft/penalty) so the
 *  round-trip preserves them. */
interface UC {
  kind: Kind;
  type: string;
  target: string;
  scope: string;
  value: TemporalVal;
  extra: Row;
}

const MAPPED_KEYS = new Set(["company", "year", "commodity_id", "impact_id", "amount", "limit"]);

/** Read the native sheets and COLLAPSE the per-year rows into one constraint each:
 *  a single year-less row → a static value; rows carrying years → a {year: value}
 *  temporal value. (This is what turns the old row-per-year table into one row.) */
function gather(wb: Workbook): UC[] {
  type G = { kind: Kind; type: string; target: string; scope: string; extra: Row; pts: { yr: number | null; v: number }[] };
  const groups = new Map<string, G>();
  for (const [key, m] of Object.entries(MAP)) {
    const [kind, type] = key.split(":") as [Kind, string];
    for (const r of wb[m.sheet] ?? []) {
      const extra: Row = {};
      for (const [k, v] of Object.entries(r)) if (!MAPPED_KEYS.has(k)) extra[k] = v;
      const target = m.target ? s(r[m.target]) : "";
      const scope = s(r.company) || "all";
      const gk = `${kind}:${type}|${scope}|${target}|${JSON.stringify(extra)}`;
      let g = groups.get(gk);
      if (!g) groups.set(gk, (g = { kind, type, target, scope, extra, pts: [] }));
      const yr = r.year == null || r.year === "" ? null : Math.round(n(r.year));
      g.pts.push({ yr, v: n(r[m.value]) });
    }
  }
  return [...groups.values()].map((g) => {
    const yearPts = g.pts.filter((p) => p.yr != null);
    let value: TemporalVal;
    if (yearPts.length) {
      const by: Record<string, number> = {};
      for (const p of yearPts) by[String(p.yr)] = p.v;
      value = by;
    } else {
      value = g.pts[0]?.v ?? 0;
    }
    return { kind: g.kind, type: g.type, target: g.target, scope: g.scope, extra: g.extra, value };
  });
}

/** Inverse of gather: a static value → one year-less row (the engine applies it to
 *  every year); a temporal value → one row per year. */
function scatter(rows: UC[]): Record<string, Row[]> {
  const out: Record<string, Row[]> = Object.fromEntries(CONSTRAINT_SHEETS.map((sh) => [sh, []]));
  for (const c of rows) {
    const m = MAP[`${c.kind}:${c.type}`];
    if (!m) continue;
    const base: Row = { ...c.extra, company: c.scope };
    if (m.target) base[m.target] = c.target;
    if (typeof c.value === "number") {
      out[m.sheet].push({ ...base, [m.value]: c.value });
    } else {
      for (const [yr, v] of Object.entries(c.value)) out[m.sheet].push({ ...base, year: Number(yr), [m.value]: v });
    }
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
  // "impact" minimises a (characterised) impact category instead of money; an
  // optional cost weight λ blends money back in (λ·cost + impact).
  const [goal, setGoal] = useState<"cost" | "profit" | "impact">("cost");
  const [objImpact, setObjImpact] = useState("");
  const [costWeight, setCostWeight] = useState(0);
  const [perCompany, setPerCompany] = useState(false);
  // Optional forced variant (authored in the Value chain): the optimiser pins its
  // changes and optimises the rest. "" = free optimisation.
  const [variant, setVariant] = useState("");
  const variants = useMemo(() => (workbook.variants ?? []) as Row[], [workbook]);

  // ── Constraints (unified) ───────────────────────────────────────────────────
  const rows = useMemo(() => gather(workbook), [workbook]);
  const commit = (next: UC[]) => setWorkbook(setSheets(workbook, scatter(next)));
  const patch = (i: number, p: Partial<UC>) =>
    commit(rows.map((r, j) => (j === i ? normalise({ ...r, ...p }) : r)));
  const add = () =>
    commit([
      ...rows,
      { kind: "production", type: "produce", target: products[0] ?? "", scope: "all", value: 100, extra: {} },
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
    const obj = goal === "impact" ? (objImpact || impacts[0] || "") : "";
    onRun({
      economics: { base_year: baseYear },
      horizon: { start: baseYear, end: endYear },
      optimisation_scope: perCompany ? "company" : "system",
      optimisation_mode: perCompany ? "independent" : "joint",
      // The base objective is always cost/profit; minimise-impact rides on top via
      // an impact_weight term, with cost_weight as the blend λ (0 ⇒ pure impact).
      objective: goal === "profit" ? "profit" : "cost",
      ...(goal === "impact"
        ? { objective_impact: obj, impact_weight: 1, cost_weight: costWeight }
        : {}),
      ...(variant ? { variant } : {}),
    });
  }

  const targetOpts = (k: Kind) => (k === "emission" ? impacts : k === "production" ? products : []);
  // The unit a constraint's value is measured in: a produced commodity's unit, the
  // capped impact's unit, or "currency" for an investment (capex) budget. Drives the
  // unit shown in the value cell + editor (TemporalValue appends "/yr").
  const unitFor = (c: UC): string =>
    c.kind === "emission"
      ? impactUnit(workbook, c.target)
      : c.kind === "production"
        ? commodityUnit(workbook, c.target)
        : modelCurrency(workbook);
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
                  onChange={(v) => setGoal(v as "cost" | "profit" | "impact")}
                  options={[
                    { value: "cost", label: "Minimise cost" },
                    { value: "profit", label: "Maximise profit" },
                    { value: "impact", label: "Minimise impact" },
                  ]}
                />
              </div>
            </label>
            {goal === "impact" && (
              <>
                <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <span style={{ fontSize: "0.8rem", fontWeight: 600 }}>Impact</span>
                  <div style={small}>
                    <SearchSelect
                      value={objImpact || impacts[0] || ""}
                      onChange={setObjImpact}
                      options={impacts.map((o) => ({ value: o }))}
                    />
                  </div>
                </label>
                <label style={{ display: "flex", gap: 6, alignItems: "center" }} title="λ — weight on monetary cost added to the impact objective (0 = pure impact minimisation)">
                  <span style={{ fontSize: "0.8rem", fontWeight: 600 }}>Cost weight λ</span>
                  <input
                    type="number"
                    step="0.001"
                    min={0}
                    style={{ width: 90 }}
                    value={costWeight}
                    onChange={(e) => setCostWeight(Math.max(0, Number(e.target.value) || 0))}
                  />
                </label>
              </>
            )}
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
            {variants.length > 0 && (
              <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{ fontSize: "0.8rem", fontWeight: 600 }}>Force variant</span>
                <div style={small}>
                  <SearchSelect
                    value={variant}
                    onChange={setVariant}
                    options={[
                      { value: "", label: "None (free optimise)" },
                      ...variants.map((v) => ({ value: s(v.variant_id), label: s(v.label) || s(v.variant_id) })),
                    ]}
                  />
                </div>
              </label>
            )}
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
            applies to, whether it's a target / minimum / maximum, and the value. The value is one
            number for the whole horizon, or click it to set a value <b>per year</b>.
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
                  <th>value (／yr)</th>
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
                      <TemporalValue
                        value={r.value}
                        onChange={(v) => patch(i, { value: v ?? 0 })}
                        label={`${r.kind}${r.target ? ` · ${r.target}` : ""} · ${r.scope}`}
                        unit={unitFor(r)}
                        baseYear={baseYear}
                        periods={years}
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
            Solves{" "}
            {goal === "cost"
              ? "least-cost"
              : goal === "profit"
                ? "max-profit"
                : `min-${objImpact || impacts[0] || "impact"}${costWeight ? ` (λ=${costWeight})` : ""}`}
            , {perCompany ? "per company" : "whole system"}, over {baseYear}–{endYear}.
          </span>
        </section>
      </main>
    </div>
  );
}
