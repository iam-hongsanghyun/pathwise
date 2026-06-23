// Run cockpit for the `frontier` backend — trace the cost–impact Pareto curve by
// sweeping a cap on a (characterised) impact category and re-running least-cost
// optimisation at each point. Shown for the targets view when the method is
// `frontier`, in place of the optimisation constraints editor.

import { useMemo, useState } from "react";
import { SearchSelect } from "../controls/SearchSelect";
import { impactUnit } from "../../lib/caps";
import { impactIds } from "../../lib/scope";
import type { Workbook } from "../../types";

export function FrontierSetup({
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

  const [fr, setFr] = useState({ impact: impacts[0] ?? "", from: 0, to: 1000, step: 100 });
  // The cap range is measured in the swept impact's own unit (t CO2e, mol H+ eq, …).
  const unit = useMemo(() => impactUnit(workbook, fr.impact), [workbook, fr.impact]);
  const num = { width: 100 } as const;

  function run() {
    onRun({
      economics: { base_year: baseYear },
      horizon: { start: baseYear, end: endYear },
      optimisation_scope: "system",
      optimisation_mode: "joint",
      frontier: { impact: fr.impact, from: fr.from, to: fr.to, step: fr.step },
    });
  }

  return (
    <div className="body-row">
      <main className="main-area" style={{ overflow: "auto", padding: "16px 22px", maxWidth: 980 }}>
        <div className="eyebrow">frontier · cost vs impact</div>
        <h2 className="view-title">Cost–impact frontier</h2>
        <p className="view-lead">
          Sweep a cap on an impact category and re-run least-cost optimisation at each point.
          The resulting curve is the cost↔impact trade-off — how much each extra tonne avoided
          costs.
        </p>

        <section style={{ marginBottom: 18 }}>
          <h3 className="section-title">Trade-off impact + cap range</h3>
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
            <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: ".8rem" }}>
              impact
              <div style={{ minWidth: 130 }}>
                <SearchSelect value={fr.impact} onChange={(v) => setFr({ ...fr, impact: v })} options={impacts.map((i) => ({ value: i }))} />
              </div>
            </label>
            <label style={{ fontSize: ".8rem" }}>
              from <input type="number" style={num} value={fr.from} onChange={(e) => setFr({ ...fr, from: Number(e.target.value) })} />
            </label>
            <label style={{ fontSize: ".8rem" }}>
              to <input type="number" style={num} value={fr.to} onChange={(e) => setFr({ ...fr, to: Number(e.target.value) })} />
            </label>
            <label style={{ fontSize: ".8rem" }}>
              step <input type="number" style={num} value={fr.step} onChange={(e) => setFr({ ...fr, step: Number(e.target.value) })} />
            </label>
            <span className="muted" style={{ fontSize: ".8rem" }} title={`cap range in the units of ${fr.impact || "the impact"}`}>{unit}</span>
          </div>
          <p className="muted" style={{ fontSize: ".74rem", marginTop: 8 }}>
            Caps below the achievable minimum come back infeasible (the frontier's endpoint).
          </p>
        </section>

        <section style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          <button className="run-button" onClick={run} disabled={running != null || !canRun}>
            {running ? `▶ ${running}…` : "▶ Run frontier"}
          </button>
          <span className="muted" style={{ fontSize: ".74rem", marginLeft: 10 }}>
            Sweeps {fr.impact} {fr.from}–{fr.to} {unit} (step {fr.step} {unit}), system-wide, over {baseYear}–{endYear}.
          </span>
        </section>
      </main>
    </div>
  );
}
