// Simulate setup — the run cockpit shown when the method is `simulate` (an LCA
// what-if), in place of the optimisation targets/constraints editor. You pin the
// current configuration (the as-is baseline) and define VARIANTS: each a label
// plus a list of typed overrides (swap a machine's technology, change a price,
// set a carbon price, put a measure on the table). Optionally sweep a carbon
// price. The Run button compiles this into the scenario's `simulate` block.
//
// Baseline is fixed to "as-is" here; the optimise→simulate handoff (a frozen
// optimisation result as baseline, timed events) is the deferred §10 TODO in
// docs/proposals/simulation-backend.md.

import { useMemo, useState } from "react";
import { SearchSelect } from "../controls/SearchSelect";
import { impactIds } from "../../lib/scope";
import type { Row, Workbook } from "../../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const ids = (rows: Row[] | undefined, col: string): string[] =>
  [...new Set((rows ?? []).map((r) => s(r[col])).filter(Boolean))];

type OpType = "set_machine_tech" | "set_price" | "set_carbon_price" | "toggle_measure";
interface Override {
  op: OpType;
  machine?: string;
  technology?: string;
  commodity?: string;
  impact?: string;
  measure?: string;
  price?: number;
  on?: boolean;
}
interface Variant {
  label: string;
  overrides: Override[];
}

const OP_OPTS: { value: OpType; label: string }[] = [
  { value: "set_machine_tech", label: "Switch a machine's technology" },
  { value: "set_price", label: "Change a commodity price" },
  { value: "set_carbon_price", label: "Set a carbon price" },
  { value: "toggle_measure", label: "Enable a measure" },
];

export function SimulateSetup({
  workbook,
  onRun,
  running,
  canRun,
}: {
  workbook: Workbook;
  onRun: (scenario: Record<string, unknown>) => void;
  running: string | null;
  canRun: boolean;
}) {
  const machines = useMemo(
    () => [
      ...new Set([
        ...ids(workbook.machines, "machine_id"),
        ...ids((workbook.nodes ?? []).filter((n) => s(n.kind) === "machine"), "node_id"),
      ]),
    ],
    [workbook],
  );
  const techs = useMemo(() => ids(workbook.technologies, "technology_id"), [workbook]);
  const commodities = useMemo(() => ids(workbook.commodities, "commodity_id"), [workbook]);
  const impacts = useMemo(() => impactIds(workbook), [workbook]);
  const measures = useMemo(() => ids(workbook.measures, "measure_id"), [workbook]);
  const years = useMemo(
    () => (workbook.periods ?? []).map((r) => Number(r.year)).filter(Number.isFinite),
    [workbook],
  );
  const baseYear = years.length ? Math.min(...years) : 2025;
  const endYear = years.length ? Math.max(...years) : baseYear;

  const [variants, setVariants] = useState<Variant[]>([]);
  const [sweepOn, setSweepOn] = useState(false);
  const [sweep, setSweep] = useState({ impact: impacts[0] ?? "CO2", from: 0, to: 300, step: 25 });

  const defaultOverride = (): Override => ({
    op: "set_machine_tech",
    machine: machines[0] ?? "",
    technology: techs[0] ?? "",
  });
  const addVariant = () =>
    setVariants((vs) => [...vs, { label: `variant ${vs.length + 1}`, overrides: [defaultOverride()] }]);
  const patchVariant = (i: number, p: Partial<Variant>) =>
    setVariants((vs) => vs.map((v, j) => (j === i ? { ...v, ...p } : v)));
  const delVariant = (i: number) => setVariants((vs) => vs.filter((_, j) => j !== i));
  const patchOverride = (vi: number, oi: number, p: Partial<Override>) =>
    patchVariant(vi, {
      overrides: variants[vi].overrides.map((o, j) => (j === oi ? { ...o, ...p } : o)),
    });
  const addOverride = (vi: number) =>
    patchVariant(vi, { overrides: [...variants[vi].overrides, defaultOverride()] });
  const delOverride = (vi: number, oi: number) =>
    patchVariant(vi, { overrides: variants[vi].overrides.filter((_, j) => j !== oi) });

  function run() {
    const simulate: Record<string, unknown> = {
      baseline: { plan: "as-is" },
      variants: variants.map((v) => ({ label: v.label, overrides: v.overrides.map(serialise) })),
    };
    if (sweepOn) {
      simulate.policy_sweep = {
        lever: "carbon_price",
        impact: sweep.impact,
        from: sweep.from,
        to: sweep.to,
        step: sweep.step,
      };
    }
    onRun({
      economics: { base_year: baseYear },
      horizon: { start: baseYear, end: endYear },
      simulate,
    });
  }

  const num = { width: 90 } as const;

  return (
    <div className="body-row">
      <main className="main-area" style={{ overflow: "auto", padding: "16px 22px", maxWidth: 980 }}>
        <div className="eyebrow">simulate · LCA what-if</div>
        <h2 className="view-title">Scenario simulator</h2>
        <p className="view-lead">
          Pin the current configuration (the as-is baseline) and test interventions against it.
          Each variant is the baseline plus a set of edits; run to compare lifecycle emissions,
          cost, and policy sensitivity.
        </p>

        <section style={{ marginBottom: 18 }}>
          <h3 className="section-title">Baseline</h3>
          <p className="muted" style={{ fontSize: ".78rem", margin: 0 }}>
            Current configuration — each machine runs its baseline technology, no auto-adopted
            abatement. (A frozen optimisation result as baseline is coming later.)
          </p>
        </section>

        <section style={{ marginBottom: 18 }}>
          <h3 className="section-title" style={{ marginBottom: 2 }}>Variants</h3>
          <p className="muted" style={{ fontSize: ".74rem", margin: "0 0 8px" }}>
            With no variants, the run just reports the baseline inventory. Add a variant to compare.
          </p>
          <button className="ghost" style={{ marginBottom: 8 }} onClick={addVariant}>＋ add variant</button>

          {variants.map((v, vi) => (
            <div key={vi} className="card" style={{ marginBottom: 10 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                <input
                  value={v.label}
                  onChange={(e) => patchVariant(vi, { label: e.target.value })}
                  style={{ fontWeight: 600, flex: 1 }}
                  aria-label="variant label"
                />
                <button className="ghost" title="remove variant" onClick={() => delVariant(vi)}>✕</button>
              </div>
              {v.overrides.map((o, oi) => (
                <div key={oi} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6, flexWrap: "wrap" }}>
                  <div style={{ minWidth: 220 }}>
                    <SearchSelect
                      value={o.op}
                      onChange={(val) => patchOverride(vi, oi, resetOp(val as OpType, { machines, techs, commodities, impacts, measures }))}
                      options={OP_OPTS}
                    />
                  </div>
                  <OverrideFields
                    o={o}
                    onChange={(p) => patchOverride(vi, oi, p)}
                    opts={{ machines, techs, commodities, impacts, measures }}
                  />
                  <button className="ghost" title="remove edit" onClick={() => delOverride(vi, oi)}>✕</button>
                </div>
              ))}
              <button className="ghost" style={{ fontSize: ".74rem" }} onClick={() => addOverride(vi)}>＋ add edit</button>
            </div>
          ))}
        </section>

        <section style={{ marginBottom: 18 }}>
          <h3 className="section-title" style={{ marginBottom: 2 }}>Policy sweep</h3>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: ".8rem" }}>
            <input type="checkbox" checked={sweepOn} onChange={(e) => setSweepOn(e.target.checked)} />
            Sweep a carbon price and trace each configuration's total cost
          </label>
          {sweepOn && (
            <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
              <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: ".78rem" }}>
                impact
                <div style={{ minWidth: 120 }}>
                  <SearchSelect value={sweep.impact} onChange={(v) => setSweep({ ...sweep, impact: v })} options={impacts.map((i) => ({ value: i }))} />
                </div>
              </label>
              <label style={{ fontSize: ".78rem" }}>
                from <input type="number" style={num} value={sweep.from} onChange={(e) => setSweep({ ...sweep, from: Number(e.target.value) })} />
              </label>
              <label style={{ fontSize: ".78rem" }}>
                to <input type="number" style={num} value={sweep.to} onChange={(e) => setSweep({ ...sweep, to: Number(e.target.value) })} />
              </label>
              <label style={{ fontSize: ".78rem" }}>
                step <input type="number" style={num} value={sweep.step} onChange={(e) => setSweep({ ...sweep, step: Number(e.target.value) })} />
              </label>
            </div>
          )}
        </section>

        <section style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          <button className="run-button" onClick={run} disabled={running != null || !canRun}>
            {running ? `▶ ${running}…` : "▶ Run simulation"}
          </button>
          <span className="muted" style={{ fontSize: ".74rem", marginLeft: 10 }}>
            Evaluates the baseline{variants.length ? ` and ${variants.length} variant(s)` : ""}
            {sweepOn ? `, sweeping ${sweep.impact} ${sweep.from}–${sweep.to}` : ""}, over {baseYear}–{endYear}.
          </span>
        </section>
      </main>
    </div>
  );
}

interface Opts {
  machines: string[];
  techs: string[];
  commodities: string[];
  impacts: string[];
  measures: string[];
}

/** Fields shown for the chosen op (machine+tech, commodity+price, …). */
function OverrideFields({ o, onChange, opts }: { o: Override; onChange: (p: Partial<Override>) => void; opts: Opts }) {
  const sel = (value: string, onPick: (v: string) => void, options: string[], min = 140) => (
    <div style={{ minWidth: min }}>
      <SearchSelect value={value} onChange={onPick} options={options.map((v) => ({ value: v }))} />
    </div>
  );
  const price = (
    <input
      type="number"
      style={{ width: 110 }}
      value={o.price ?? 0}
      onChange={(e) => onChange({ price: Number(e.target.value) })}
      aria-label="price"
    />
  );
  if (o.op === "set_machine_tech")
    return (
      <>
        {sel(o.machine ?? "", (v) => onChange({ machine: v }), opts.machines, 180)}
        <span className="muted">→</span>
        {sel(o.technology ?? "", (v) => onChange({ technology: v }), opts.techs)}
      </>
    );
  if (o.op === "set_price")
    return (
      <>
        {sel(o.commodity ?? "", (v) => onChange({ commodity: v }), opts.commodities)}
        <span className="muted">=</span>
        {price}
      </>
    );
  if (o.op === "set_carbon_price")
    return (
      <>
        {sel(o.impact ?? "", (v) => onChange({ impact: v }), opts.impacts)}
        <span className="muted">=</span>
        {price}
      </>
    );
  // toggle_measure
  return (
    <>
      {sel(o.measure ?? "", (v) => onChange({ measure: v }), opts.measures, 200)}
      <label style={{ display: "flex", gap: 4, alignItems: "center", fontSize: ".78rem" }}>
        <input type="checkbox" checked={o.on ?? true} onChange={(e) => onChange({ on: e.target.checked })} /> on
      </label>
    </>
  );
}

/** Sensible defaults when the op changes (so the new fields aren't empty). */
function resetOp(op: OpType, opts: Opts): Override {
  if (op === "set_machine_tech") return { op, machine: opts.machines[0] ?? "", technology: opts.techs[0] ?? "" };
  if (op === "set_price") return { op, commodity: opts.commodities[0] ?? "", price: 0 };
  if (op === "set_carbon_price") return { op, impact: opts.impacts[0] ?? "CO2", price: 0 };
  return { op, measure: opts.measures[0] ?? "", on: true };
}

/** Drop UI-only undefined fields so the payload is the minimal typed op. */
function serialise(o: Override): Record<string, unknown> {
  const out: Record<string, unknown> = { op: o.op };
  for (const k of ["machine", "technology", "commodity", "impact", "measure", "price", "on"] as const) {
    if (o[k] !== undefined) out[k] = o[k];
  }
  return out;
}
