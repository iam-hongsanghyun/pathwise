// Targets & constraints — one place to set, scoped by system / sector / company /
// facility, the optimisation's production targets and limits. Pure UI over the
// existing backend sheets (demand, min_production, impact_caps, investment_budget,
// company_config); edits mutate the workbook and the host debounce-syncs them.

import { useMemo, useState } from "react";
import { type Column, DataTable } from "../features/controls/DataTable";
import { SearchSelect } from "../features/controls/SearchSelect";
import { impactIds, productIds, scopeOptions } from "../lib/scope";
import type { Row, Workbook } from "../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const setSheet = (wb: Workbook, sheet: string, rows: Row[]): Workbook => ({ ...wb, [sheet]: rows });
const numCol = (
  key: string,
  label: string,
  opts: { integer?: boolean; nullable?: boolean; metaKey?: string } = {},
): Column<Row> => ({
  key,
  label,
  type: "number",
  metaKey: opts.metaKey,
  nullable: opts.nullable,
  integer: opts.integer,
  get: (r) => (typeof r[key] === "number" ? (r[key] as number) : s(r[key])),
  set: (r, v) => {
    if (v.trim() === "") return { ...r, [key]: opts.nullable ? null : 0 };
    const n = Number(v) || 0;
    return { ...r, [key]: opts.integer ? Math.round(n) : n };
  },
});
const enumCol = (key: string, label: string, options: string[], metaKey?: string): Column<Row> => ({
  key, label, type: "enum", options, metaKey, get: (r) => s(r[key]), set: (r, v) => ({ ...r, [key]: v }),
});
const boolCol = (key: string, label: string): Column<Row> => ({
  key, label, type: "boolean", get: (r) => r[key] === true, set: (r, v) => ({ ...r, [key]: v === "true" }),
});

export function TargetsTabView({
  workbook,
  setWorkbook,
}: {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
}) {
  const scopes = useMemo(() => scopeOptions(workbook), [workbook]);
  const products = useMemo(() => productIds(workbook), [workbook]);
  const impacts = useMemo(() => impactIds(workbook), [workbook]);
  const baseYear = useMemo(() => {
    const ys = (workbook.periods ?? []).map((r) => Number(r.year)).filter(Number.isFinite);
    return ys.length ? Math.min(...ys) : 2025;
  }, [workbook]);
  const [scope, setScope] = useState<string>(scopes[0]?.value ?? "all");
  const scopeLabel = scopes.find((o) => o.value === scope)?.label ?? scope;

  // ── one scoped sheet section ─────────────────────────────────────────────────
  function Section({ sheet, title, hint, columns, blank }: {
    sheet: string; title: string; hint: string; columns: Column<Row>[]; blank: () => Row;
  }) {
    const all = workbook[sheet] ?? [];
    const mine = all.filter((r) => s(r.company) === scope);
    const writeMine = (next: Row[]) =>
      setWorkbook(setSheet(workbook, sheet, [...all.filter((r) => s(r.company) !== scope), ...next]));
    const del: Column<Row> = {
      key: "_del", label: "", type: "readonly", width: 28,
      get: () => "✕",
      onClick: (r) => setWorkbook(setSheet(workbook, sheet, all.filter((x) => x !== r))),
    };
    return (
      <section style={{ marginBottom: 22 }}>
        <h3 style={{ margin: "0 0 2px", fontSize: "0.92rem" }}>{title}</h3>
        <p className="muted" style={{ fontSize: "0.74rem", margin: "0 0 8px" }}>{hint}</p>
        <button className="ghost" style={{ marginBottom: 8 }} onClick={() => writeMine([...mine, { company: scope, ...blank() }])}>
          ＋ add
        </button>
        <DataTable
          rows={mine}
          columns={[...columns, del]}
          onChange={writeMine}
          rowKey={(r) => String(mine.indexOf(r))}
          empty="No rows for this scope yet — ＋ add one."
        />
      </section>
    );
  }

  // company objective lives in company_config (per company); meaningless for "all".
  const objective = s((workbook.company_config ?? []).find((r) => s(r.company) === scope)?.objective) || "cost";
  const setObjective = (v: string) => {
    const rows = workbook.company_config ?? [];
    const exists = rows.some((r) => s(r.company) === scope);
    const next = exists
      ? rows.map((r) => (s(r.company) === scope ? { ...r, objective: v } : r))
      : [...rows, { company: scope, objective: v }];
    setWorkbook(setSheet(workbook, "company_config", next));
  };

  return (
    <div className="body-row">
      <main className="main-area" style={{ overflow: "auto", padding: "16px 22px", maxWidth: 920 }}>
        <h2 style={{ margin: "0 0 4px" }}>Targets &amp; constraints</h2>
        <p className="muted" style={{ fontSize: "0.78rem", margin: "0 0 14px" }}>
          Production targets and limits for the optimisation, scoped to part of the model.
          Pick a scope; each row below applies to it.
        </p>

        <label className="inspector-field" style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 18, maxWidth: 460 }}>
          <span style={{ fontSize: "0.8rem", fontWeight: 600 }}>Scope</span>
          <div style={{ flex: 1 }}>
            <SearchSelect value={scope} onChange={setScope} options={scopes} />
          </div>
        </label>

        <Section
          sheet="demand" title="Production targets (demand)"
          hint={`How much of a product ${scopeLabel} must deliver each year (a floor in cost mode, a ceiling in profit mode).`}
          columns={[enumCol("commodity_id", "product", products, "amount"), numCol("year", "year", { integer: true }), numCol("amount", "amount", { metaKey: "amount" })]}
          blank={() => ({ commodity_id: products[0] ?? "", year: baseYear, amount: 100 })}
        />
        <Section
          sheet="min_production" title="Minimum production"
          hint="A hard floor on delivered product (always enforced, unlike demand)."
          columns={[enumCol("commodity_id", "product", products, "amount"), numCol("year", "year", { integer: true }), numCol("amount", "amount", { metaKey: "amount" })]}
          blank={() => ({ commodity_id: products[0] ?? "", year: baseYear, amount: 0 })}
        />
        <Section
          sheet="impact_caps" title="Emission caps"
          hint="A per-year limit on an impact (e.g. tCO2e). Soft = exceedance allowed at a penalty; intensity = limit is per unit product."
          columns={[
            enumCol("impact_id", "impact", impacts), numCol("year", "year", { integer: true }),
            numCol("limit", "limit"), boolCol("soft", "soft?"), numCol("penalty", "penalty", { nullable: true }), boolCol("intensity", "intensity?"),
          ]}
          blank={() => ({ impact_id: impacts[0] ?? "", year: baseYear, limit: 0, soft: true })}
        />
        <Section
          sheet="investment_budget" title="Investment budget"
          hint="A per-year ceiling on capital spend (currency)."
          columns={[numCol("year", "year", { integer: true }), numCol("limit", "limit")]}
          blank={() => ({ year: baseYear, limit: 0 })}
        />

        {scope !== "all" && (
          <section style={{ marginBottom: 22 }}>
            <h3 style={{ margin: "0 0 2px", fontSize: "0.92rem" }}>Objective</h3>
            <p className="muted" style={{ fontSize: "0.74rem", margin: "0 0 8px" }}>
              Whether {scopeLabel} minimises cost (demand is a floor) or maximises profit (demand is a ceiling).
            </p>
            <div style={{ maxWidth: 280 }}>
              <SearchSelect
                value={objective}
                onChange={setObjective}
                options={[{ value: "cost", label: "Minimise cost" }, { value: "profit", label: "Maximise profit" }]}
              />
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
