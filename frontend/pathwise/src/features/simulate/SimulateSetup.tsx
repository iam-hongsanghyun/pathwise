// Simulate run screen — shown when the method is `simulate` (an LCA what-if), in
// place of the optimisation targets/constraints editor. Variants are now authored
// IN the value chain (see VariantsPanel) and live on the model, so this screen is
// a *selector / summary*: it shows the variants the run will evaluate against the
// as-is baseline, plus an optional carbon-price sweep, and fires the run. It does
// NOT pass `simulate.variants`, so the backend reads the model-resident ones.

import { useMemo, useState } from "react";
import { SearchSelect } from "../controls/SearchSelect";
import { impactUnit, modelCurrency, modelDiscount } from "../../lib/caps";
import { impactIds } from "../../lib/scope";
import type { Row, Workbook } from "../../types";

const s = (v: unknown): string => (v == null ? "" : String(v));

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
  const impacts = useMemo(() => impactIds(workbook), [workbook]);
  const years = useMemo(
    () => (workbook.periods ?? []).map((r) => Number(r.year)).filter(Number.isFinite),
    [workbook],
  );
  const baseYear = years.length ? Math.min(...years) : 2025;
  const endYear = years.length ? Math.max(...years) : baseYear;

  // Model-resident variants (authored in the value chain) + their intervention counts.
  const variants = (workbook.variants ?? []) as Row[];
  const interventions = (workbook.variant_interventions ?? []) as Row[];
  const countFor = (vid: string) => interventions.filter((r) => s(r.variant_id) === vid).length;

  const [sweepOn, setSweepOn] = useState(false);
  const [sweep, setSweep] = useState({ impact: impacts[0] ?? "", from: 0, to: 300, step: 25 });
  // A carbon-price sweep: from/to/step are prices, i.e. the model currency per unit of the impact.
  const priceUnit = useMemo(
    () => `${modelCurrency(workbook)}/${impactUnit(workbook, sweep.impact)}`,
    [workbook, sweep.impact],
  );
  const [uncOn, setUncOn] = useState(false);
  const [unc, setUnc] = useState({ sigma: 0.1, n: 1000, seed: 42 });

  function run() {
    const simulate: Record<string, unknown> = { baseline: { plan: "as-is" } };
    if (sweepOn) {
      simulate.policy_sweep = {
        lever: "carbon_price",
        impact: sweep.impact,
        from: sweep.from,
        to: sweep.to,
        step: sweep.step,
      };
    }
    if (uncOn) {
      simulate.uncertainty = { sigma: unc.sigma, n: unc.n, seed: unc.seed };
    }
    // No `variants` key ⇒ the backend evaluates the model-resident variants.
    onRun({
      economics: { base_year: baseYear, discount_rate: modelDiscount(workbook) },
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
          Evaluate the as-is baseline and compare it against the <strong>variants</strong> you
          defined in the Value chain (per-machine forced switches, price or lever changes).
          Optionally sweep a carbon price.
        </p>

        <section style={{ marginBottom: 18 }}>
          <h3 className="section-title">Baseline</h3>
          <p className="muted" style={{ fontSize: ".78rem", margin: 0 }}>
            Current configuration — each machine runs its baseline technology, no auto-adopted
            abatement.
          </p>
        </section>

        <section style={{ marginBottom: 18 }}>
          <h3 className="section-title" style={{ marginBottom: 2 }}>Variants</h3>
          {variants.length === 0 ? (
            <p className="muted" style={{ fontSize: ".78rem", margin: 0 }}>
              No variants yet. Add them in the <strong>Value chain</strong> view — select a machine,
              then “Variants (what-if)” in its panel. The run will still report the baseline LCA.
            </p>
          ) : (
            <ul style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: ".82rem" }}>
              {variants.map((v) => (
                <li key={s(v.variant_id)}>
                  <strong>{s(v.label) || s(v.variant_id)}</strong>{" "}
                  <span className="muted">
                    — {countFor(s(v.variant_id))} intervention(s)
                  </span>
                </li>
              ))}
            </ul>
          )}
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
              <span className="muted" style={{ fontSize: ".78rem" }} title={`carbon price in ${priceUnit}`}>{priceUnit}</span>
            </div>
          )}
        </section>

        <section style={{ marginBottom: 18 }}>
          <h3 className="section-title" style={{ marginBottom: 2 }}>Uncertainty</h3>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: ".8rem" }}>
            <input type="checkbox" checked={uncOn} onChange={(e) => setUncOn(e.target.checked)} />
            Monte-Carlo the emission / characterisation factors (per-impact P5–P95 band)
          </label>
          {uncOn && (
            <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
              <label style={{ fontSize: ".78rem" }} title="log-normal σ on each factor">
                σ <input type="number" step="0.01" style={num} value={unc.sigma} onChange={(e) => setUnc({ ...unc, sigma: Number(e.target.value) })} />
              </label>
              <label style={{ fontSize: ".78rem" }}>
                samples <input type="number" style={num} value={unc.n} onChange={(e) => setUnc({ ...unc, n: Math.max(1, Math.round(Number(e.target.value))) })} />
              </label>
              <label style={{ fontSize: ".78rem" }} title="RNG seed (reproducible)">
                seed <input type="number" style={num} value={unc.seed} onChange={(e) => setUnc({ ...unc, seed: Math.round(Number(e.target.value)) })} />
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
            {sweepOn ? `, sweeping ${sweep.impact} price ${sweep.from}–${sweep.to} ${priceUnit}` : ""}
            {uncOn ? `, ${unc.n} MC samples (σ=${unc.sigma})` : ""}, over {baseYear}–{endYear}.
          </span>
        </section>
      </main>
    </div>
  );
}
