import { LineChart } from "./LineChart";
import type { LcaBlock, RunResult } from "../../types";

/** Result view for a `simulate` (LCA what-if) run. Shows the baseline lifecycle
 *  inventory (emissions by value-chain stage and by impact, per functional unit),
 *  and — when the scenario defined variants — a baseline-vs-variant comparison, a
 *  carbon-price sensitivity curve, and cap compliance. Mirrors MaccResult /
 *  PortfolioResult: the MILP timelines are empty for a simulate run, so this
 *  stands in for the standard analytics. */
export function LcaResult({ result }: { result: RunResult }) {
  const lca = result.outputs.lca;
  if (!lca) return null;
  const impact = primaryImpact(lca);
  const comparison = result.outputs.comparison ?? [];
  const variants = result.outputs.variants ?? [];
  const sweep = result.outputs.policy_sweep ?? [];
  const compliance = result.outputs.cap_compliance ?? [];

  const headPerUnit = lca.by_impact.find((d) => d.impact === impact)?.per_unit ?? 0;
  const fuAmount = lca.functional_unit.amount;
  const fuName = lca.functional_unit.commodity ?? "unit";

  // Stage rows for the headline impact (largest first).
  const stageRows = lca.by_stage
    .filter((d) => d.impact === impact)
    .sort((a, b) => b.total - a.total);
  const stageMax = Math.max(...stageRows.map((d) => d.total), 1);

  // Lifecycle-phase rollup (materials · manufacturing · use · EoL) for the headline
  // impact, present only when nodes carry a `phase` tag.
  const phaseRows = (lca.by_phase ?? [])
    .filter((d) => d.impact === impact)
    .sort((a, b) => b.total - a.total);
  const phaseMax = Math.max(...phaseRows.map((d) => d.total), 1);

  // Monte-Carlo factor-uncertainty band, present only when the scenario ran it.
  const uncertainty = lca.uncertainty ?? [];

  return (
    <div className="view">
      <div className="card">
        <h3>Lifecycle assessment · {result.status}</h3>
        <p className="muted">
          Cradle-to-gate emissions of the pinned configuration, by value-chain stage, normalised
          per functional unit. Use-phase emissions appear here too when the model carries a use
          process.
        </p>
        <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap", marginTop: ".5rem" }}>
          <Stat label="Functional unit" value={`${fmt(fuAmount, 0)} ${fuName}`} />
          <Stat label={`${impact} / ${fuName}`} value={fmt(headPerUnit, 3)} />
          <Stat label={`Total ${impact}`} value={fmt(impactTotal(lca, impact))} />
          <Stat label="Cost / unit" value={fmt(lca.cost.per_unit, 2)} />
        </div>
      </div>

      <div className="card">
        <h3>Emissions by stage ({impact})</h3>
        {stageRows.length ? (
          <Bars rows={stageRows.map((d) => ({ label: shortStage(d.stage), value: d.total }))} max={stageMax} />
        ) : (
          <p className="muted">No staged emissions.</p>
        )}
      </div>

      <div className="card">
        <h3>By impact (total · per unit)</h3>
        <table className="grid-table">
          <thead>
            <tr>
              <th>Impact</th>
              <th>Total</th>
              <th>Per {fuName}</th>
            </tr>
          </thead>
          <tbody>
            {lca.by_impact.map((d) => (
              <tr key={d.impact}>
                <td>{d.impact}</td>
                <td>{fmt(d.total)}</td>
                <td>{fmt(d.per_unit, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {phaseRows.length > 0 && (
        <div className="card">
          <h3>Emissions by lifecycle phase ({impact})</h3>
          <Bars rows={phaseRows.map((d) => ({ label: d.phase, value: d.total }))} max={phaseMax} />
          <p className="muted" style={{ fontSize: ".74rem", marginTop: ".5rem" }}>
            Stages rolled up by their <code>phase</code> tag (materials · manufacturing · use ·
            end-of-life), the standard cradle-to-grave breakdown.
          </p>
        </div>
      )}

      {uncertainty.length > 0 && (
        <div className="card">
          <h3>Factor uncertainty (Monte-Carlo)</h3>
          <table className="grid-table">
            <thead>
              <tr>
                <th>Impact</th>
                <th>Mean</th>
                <th>P5</th>
                <th>Median</th>
                <th>P95</th>
                <th>Std</th>
              </tr>
            </thead>
            <tbody>
              {uncertainty.map((u) => (
                <tr key={u.impact}>
                  <td>{u.impact}</td>
                  <td>{fmt(u.mean)}</td>
                  <td>{fmt(u.p5)}</td>
                  <td>{fmt(u.p50)}</td>
                  <td>{fmt(u.p95)}</td>
                  <td>{fmt(u.std)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: ".74rem", marginTop: ".5rem" }}>
            The inventory recomputed over sampled emission/characterisation factors at fixed
            throughput. P5–P95 is the 90% band on total impact.
          </p>
        </div>
      )}

      {comparison.length > 0 && (
        <ComparisonCard impact={impact} baseline={impactTotal(lca, impact)} variants={variants} comparison={comparison} />
      )}

      {sweep.length > 0 && <SweepCard sweep={sweep} comparison={comparison} />}

      {compliance.length > 0 && <ComplianceCard compliance={compliance} />}
    </div>
  );
}

function ComparisonCard({
  impact,
  baseline,
  variants,
  comparison,
}: {
  impact: string;
  baseline: number;
  variants: RunResult["outputs"]["variants"];
  comparison: NonNullable<RunResult["outputs"]["comparison"]>;
}) {
  // Total emissions per configuration (baseline first), for the bar comparison.
  const bars = [{ label: "baseline", value: baseline }];
  for (const v of variants ?? []) bars.push({ label: v.label, value: v.lca ? impactTotal(v.lca, impact) : 0 });
  const max = Math.max(...bars.map((b) => b.value), 1);

  // Sunk (stranded-asset) cost per variant, keyed by label, from its own LCA.
  const sunkOf = new Map((variants ?? []).map((v) => [v.label, v.lca?.cost.sunk ?? 0]));
  const anySunk = [...sunkOf.values()].some((x) => x > 0);

  return (
    <div className="card">
      <h3>Baseline vs variants — {impact}</h3>
      <Bars rows={bars} max={max} />
      <div style={{ overflowX: "auto", marginTop: ".75rem" }}>
        <table className="grid-table">
          <thead>
            <tr>
              <th>Variant</th>
              <th>Abatement</th>
              <th>Cost Δ (ex-carbon)</th>
              {anySunk && <th>of which sunk</th>}
              <th>$ / {impact}</th>
              <th>Break-even carbon price</th>
            </tr>
          </thead>
          <tbody>
            {comparison.map((c) => (
              <tr key={c.label}>
                <td>{c.label}</td>
                {c.status === "optimal" ? (
                  <>
                    <td>{fmt(c.abatement ?? 0)}</td>
                    <td>{fmt(c.cost_delta ?? 0, 1)}</td>
                    {anySunk && <td>{(sunkOf.get(c.label) ?? 0) > 0 ? fmt(sunkOf.get(c.label) ?? 0, 1) : "—"}</td>}
                    <td>{c.abatement_cost_per_unit == null ? "—" : fmt(c.abatement_cost_per_unit, 2)}</td>
                    <td>{c.breakeven_carbon_price == null ? "never" : fmt(c.breakeven_carbon_price, 2)}</td>
                  </>
                ) : (
                  <td colSpan={anySunk ? 5 : 4} className="muted">{c.status}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ fontSize: ".74rem", marginTop: ".5rem" }}>
        Abatement &gt; 0 means the variant emits less. Break-even is the carbon price at which the
        variant's total cost drops below the baseline's; “never” means it emits more, so no price
        flips the choice.{anySunk ? " Cost Δ includes the sunk cost of retiring an asset before end-of-life." : ""}
      </p>
    </div>
  );
}

function SweepCard({
  sweep,
  comparison,
}: {
  sweep: NonNullable<RunResult["outputs"]["policy_sweep"]>;
  comparison: NonNullable<RunResult["outputs"]["comparison"]>;
}) {
  const prices = sweep.map((r) => r.carbon_price);
  const labels = sweep[0]?.variants.map((v) => v.label) ?? [];
  const series = labels.map((label) => ({
    label,
    values: sweep.map((row) => row.variants.find((v) => v.label === label)?.cost ?? 0),
  }));
  const breakeven = comparison
    .filter((c) => c.breakeven_carbon_price != null)
    .map((c) => `${c.label} at ${fmt(c.breakeven_carbon_price as number, 1)}`);

  return (
    <div className="card">
      <h3>Policy sweep — total cost vs carbon price</h3>
      <LineChart years={prices} series={series} unit="$" />
      <p className="muted" style={{ fontSize: ".74rem", marginTop: ".5rem" }}>
        Each line is a configuration's total cost as the carbon price rises (x-axis = price on{" "}
        {sweep[0]?.impact ?? "CO2"}). Where a variant's line crosses the baseline's is its break-even
        price{breakeven.length ? `: ${breakeven.join(", ")}` : ""}.
      </p>
    </div>
  );
}

function ComplianceCard({ compliance }: { compliance: NonNullable<RunResult["outputs"]["cap_compliance"]> }) {
  return (
    <div className="card">
      <h3>Cap compliance</h3>
      <div style={{ overflowX: "auto" }}>
        <table className="grid-table">
          <thead>
            <tr>
              <th>Config</th>
              <th>Status</th>
              <th>Impact</th>
              <th>Year</th>
              <th>Emissions</th>
              <th>Cap</th>
              <th>Over</th>
            </tr>
          </thead>
          <tbody>
            {compliance.flatMap((c) =>
              (c.by_year ?? []).map((y, i) => (
                <tr key={`${c.label}:${y.impact}:${y.year}`}>
                  {i === 0 && <td rowSpan={c.by_year?.length || 1}>{c.label}</td>}
                  {i === 0 && (
                    <td rowSpan={c.by_year?.length || 1}>
                      <span style={{ color: c.compliant ? "#0f766e" : "#dc2626", fontWeight: 600 }}>
                        {c.compliant ? "compliant" : "over"}
                      </span>
                    </td>
                  )}
                  <td>{y.impact}</td>
                  <td>{y.year}</td>
                  <td>{fmt(y.emissions)}</td>
                  <td>{fmt(y.cap)}</td>
                  <td>{y.over > 1e-6 ? fmt(y.over) : "—"}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Horizontal labelled bars (one per row), scaled to `max`. */
function Bars({ rows, max }: { rows: { label: string; value: number }[]; max: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {rows.map((r) => (
        <div key={r.label} style={{ display: "grid", gridTemplateColumns: "160px 1fr 90px", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: ".78rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.label}>
            {r.label}
          </span>
          <div style={{ background: "var(--border)", borderRadius: 3, height: 14 }}>
            <div style={{ width: `${Math.max(0, (r.value / max) * 100)}%`, background: "#0f766e", height: 14, borderRadius: 3 }} />
          </div>
          <span style={{ fontSize: ".78rem", textAlign: "right" }}>{fmt(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="muted" style={{ fontSize: ".8rem" }}>{label}</div>
      <div style={{ fontSize: "1.3rem", fontWeight: 600 }}>{value}</div>
    </div>
  );
}

const fmt = (v: number, d = 2) => v.toLocaleString(undefined, { maximumFractionDigits: d });

/** The headline impact a view keys on: CO2 if present, else the first. */
function primaryImpact(lca: LcaBlock): string {
  const impacts = lca.by_impact.map((d) => d.impact);
  return impacts.includes("CO2") ? "CO2" : (impacts[0] ?? "CO2");
}

function impactTotal(lca: LcaBlock, impact: string): number {
  return lca.by_impact.find((d) => d.impact === impact)?.total ?? 0;
}

/** A node id like `vc/korea/kr_steel` → `kr_steel` for compact labels. */
function shortStage(stage: string): string {
  const seg = stage.split("/").filter(Boolean);
  return seg[seg.length - 1] ?? stage;
}
