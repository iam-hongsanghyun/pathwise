import { useState } from "react";
import { RailList, type RailItem } from "../layout/RailList";
import { Resizer } from "../layout/Resizer";
import type {
  AssetLevel,
  ConfigBundle,
  PortfolioConfig,
  PortfolioMethod,
  RewardMode,
} from "../types";

type Section = "economics" | "method" | "snapshots" | "solver" | "policy";
type Scope = "system" | "company" | "facility";

interface Props {
  discount: number;
  onDiscount: (v: number) => void;
  objScope: Scope;
  onObjScope: (s: Scope) => void;
  config: ConfigBundle | null;
  backend: string;
  onBackend: (b: string) => void;
  portfolio: PortfolioConfig;
  onPortfolio: (p: PortfolioConfig) => void;
  leftW: number;
  setLeftW: (w: number) => void;
}

const METHOD_LABEL: Record<PortfolioMethod, string> = {
  mvo: "Mean-variance (MVO)",
  cvar: "Conditional VaR (CVaR)",
  hrp: "Hierarchical risk parity (HRP)",
  black_litterman: "Black-Litterman",
};

/** Settings — its own section rail; scenario/run parameters only (model data is
 *  edited in Data). */
export function SettingsView({
  discount,
  onDiscount,
  objScope,
  onObjScope,
  config,
  backend,
  onBackend,
  portfolio,
  onPortfolio,
  leftW,
  setLeftW,
}: Props) {
  const [section, setSection] = useState<Section>("economics");
  const items: RailItem[] = [
    { id: "economics", label: "Economics" },
    { id: "method", label: "Optimisation method" },
    { id: "snapshots", label: "Snapshots" },
    { id: "solver", label: "Solver" },
    { id: "policy", label: "Policy" },
  ];
  const backends = config?.backends ?? [{ name: "linopy", label: "linopy + HiGHS" }];
  const isPortfolio = backend === "portfolio";
  const set = (patch: Partial<PortfolioConfig>) => onPortfolio({ ...portfolio, ...patch });
  const byTarget = portfolio.target_return != null;

  return (
    <div className="body-row">
      <RailList
        title="Settings"
        items={items}
        activeId={section}
        onSelect={(id) => setSection(id as Section)}
        width={leftW}
      />
      <Resizer width={leftW} setWidth={setLeftW} side="left" />
      <main className="main-area">
        <div className="view">
          {section === "economics" && (
            <section className="card">
              <h3>Economics</h3>
              <label className="inspector-field">
                <span>Discount rate</span>
                <input
                  type="number"
                  step="0.01"
                  value={discount}
                  onChange={(e) => onDiscount(Number(e.target.value))}
                />
              </label>
              <label className="inspector-field">
                <span>Optimise cost for</span>
                <select value={objScope} onChange={(e) => onObjScope(e.target.value as Scope)}>
                  <option value="company">Each company (independent targets)</option>
                  <option value="system">The whole economy (one shared target)</option>
                  <option value="facility">Each facility (independent targets)</option>
                </select>
              </label>
              <p className="muted">
                The objective is always to minimise total discounted cost. This sets the level the
                emission targets bind at: <strong>whole economy</strong> pools every target into one
                shared cap (companies trade off to the cheapest system-wide outcome);{" "}
                <strong>each company / facility</strong> keeps targets separate, so the solve
                decomposes into independent per-company (or per-facility) cost minimisations.
                Per-company objective (cost / profit), budgets and minimum production are edited per
                company in the model.
              </p>
            </section>
          )}
          {section === "method" && (
            <section className="card">
              <h3>Optimisation method</h3>
              <label className="inspector-field">
                <span>Backend</span>
                <select value={backend} onChange={(e) => onBackend(e.target.value)}>
                  {backends.map((b) => (
                    <option key={b.name} value={b.name}>
                      {b.label}
                    </option>
                  ))}
                </select>
              </label>
              {!isPortfolio ? (
                <p className="muted">
                  <strong>linopy + HiGHS</strong> solves the deterministic least-cost transition
                  plan (one technology per facility per period). Pick <strong>Portfolio</strong> to
                  instead allocate transition capital across candidate switches by risk vs reward.
                </p>
              ) : (
                <>
                  <label className="inspector-field">
                    <span>Method</span>
                    <select
                      value={portfolio.method}
                      onChange={(e) => set({ method: e.target.value as PortfolioMethod })}
                    >
                      {(Object.keys(METHOD_LABEL) as PortfolioMethod[]).map((m) => (
                        <option key={m} value={m}>
                          {METHOD_LABEL[m]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="inspector-field">
                    <span>Reward basis</span>
                    <select
                      value={portfolio.reward_mode}
                      onChange={(e) => set({ reward_mode: e.target.value as RewardMode })}
                    >
                      <option value="cost_reduction">Cost reduction vs baseline</option>
                      <option value="profit">Profit (revenue − cost)</option>
                    </select>
                  </label>
                  <label className="inspector-field">
                    <span>Asset granularity</span>
                    <select
                      value={portfolio.asset_level}
                      onChange={(e) => set({ asset_level: e.target.value as AssetLevel })}
                    >
                      <option value="facility">Per facility × technology</option>
                      <option value="technology">Per technology (economy-wide)</option>
                      <option value="company">Per company</option>
                      <option value="economy">Whole economy (by technology)</option>
                    </select>
                  </label>
                  <label className="inspector-field">
                    <span>Monte Carlo scenarios</span>
                    <input
                      type="number"
                      min={2}
                      step={100}
                      value={portfolio.n_scenarios}
                      onChange={(e) => set({ n_scenarios: Math.max(2, Number(e.target.value)) })}
                    />
                  </label>
                  <label className="inspector-field">
                    <span>Volatility (0 = sector defaults)</span>
                    <input
                      type="number"
                      min={0}
                      step={0.05}
                      value={portfolio.volatility}
                      onChange={(e) => set({ volatility: Math.max(0, Number(e.target.value)) })}
                    />
                  </label>
                  {(portfolio.method === "mvo" || portfolio.method === "black_litterman") && (
                    <>
                      <label className="inspector-field">
                        <span>Optimise by</span>
                        <select
                          value={byTarget ? "target" : "aversion"}
                          onChange={(e) =>
                            set({ target_return: e.target.value === "target" ? 0 : null })
                          }
                        >
                          <option value="aversion">Risk aversion</option>
                          <option value="target">Target return</option>
                        </select>
                      </label>
                      {byTarget ? (
                        <label className="inspector-field">
                          <span>Target return</span>
                          <input
                            type="number"
                            step={0.01}
                            value={portfolio.target_return ?? 0}
                            onChange={(e) => set({ target_return: Number(e.target.value) })}
                          />
                        </label>
                      ) : (
                        <label className="inspector-field">
                          <span>Risk aversion</span>
                          <input
                            type="number"
                            min={0}
                            step={0.5}
                            value={portfolio.risk_aversion}
                            onChange={(e) =>
                              set({ risk_aversion: Math.max(0, Number(e.target.value)) })
                            }
                          />
                        </label>
                      )}
                    </>
                  )}
                  {portfolio.method === "cvar" && (
                    <label className="inspector-field">
                      <span>CVaR confidence (α)</span>
                      <input
                        type="number"
                        min={0.5}
                        max={0.999}
                        step={0.01}
                        value={portfolio.cvar_alpha}
                        onChange={(e) => set({ cvar_alpha: Number(e.target.value) })}
                      />
                    </label>
                  )}
                  {portfolio.method === "hrp" && (
                    <p className="muted">
                      HRP is parameter-light: it clusters assets by correlation and allocates by
                      recursive inverse-variance bisection — no return target needed.
                    </p>
                  )}
                  {portfolio.method === "black_litterman" && (
                    <BlViews portfolio={portfolio} onChange={onPortfolio} />
                  )}
                  <p className="muted">
                    Candidate technology transitions are treated as portfolio assets. Each asset's
                    reward is sampled across {portfolio.n_scenarios} Monte-Carlo price/cost
                    scenarios; the optimiser returns the allocation (weights) trading risk against
                    reward.
                  </p>
                </>
              )}
            </section>
          )}
          {section === "snapshots" && (
            <section className="card">
              <h3>Snapshots (time resolution)</h3>
              <p className="muted">
                Runs are <strong>annual</strong> — one snapshot per period. Temporal data already
                uses the static + wide-temporal split (rows = years, columns = item names), so
                sub-annual weighted snapshots slot onto the same axis when enabled.
              </p>
              <label className="inspector-field">
                <span>Resolution</span>
                <select disabled value="annual">
                  <option value="annual">Annual (per period)</option>
                </select>
              </label>
            </section>
          )}
          {section === "solver" && (
            <section className="card">
              <h3>Solver</h3>
              <p className="muted">
                HiGHS via linopy (our engine — not PyPSA). Global scaling on for numerical
                stability; MIP gap / time limit are server-controlled.
              </p>
            </section>
          )}
          {section === "policy" && (
            <section className="card">
              <h3>Policy</h3>
              <p className="muted">
                Carbon price / tradable ETS and energy markets (KEPCO / PPA / JKM) are modelled as
                Markets — add them in Data or the Model canvas.
              </p>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}

/** Minimal Black-Litterman absolute-views editor (asset id + expected reward). */
function BlViews({
  portfolio,
  onChange,
}: {
  portfolio: PortfolioConfig;
  onChange: (p: PortfolioConfig) => void;
}) {
  const views = portfolio.views;
  const update = (i: number, patch: Partial<{ asset: string; view: number }>) =>
    onChange({ ...portfolio, views: views.map((v, j) => (j === i ? { ...v, ...patch } : v)) });
  const add = () => onChange({ ...portfolio, views: [...views, { asset: "", view: 0 }] });
  const remove = (i: number) =>
    onChange({ ...portfolio, views: views.filter((_, j) => j !== i) });

  return (
    <div className="bl-views">
      <div className="inspector-field">
        <span>Views (asset → expected reward)</span>
      </div>
      {views.map((v, i) => (
        <div key={i} className="bl-view-row">
          <input
            placeholder="asset id"
            value={v.asset}
            onChange={(e) => update(i, { asset: e.target.value })}
          />
          <input
            type="number"
            step={0.01}
            value={v.view}
            onChange={(e) => update(i, { view: Number(e.target.value) })}
          />
          <button className="ghost" onClick={() => remove(i)} title="remove view">
            ✕
          </button>
        </div>
      ))}
      <button className="ghost" onClick={add}>
        + add view
      </button>
      <p className="muted">
        Asset ids appear in the result allocation table after a run. No views ⇒ the posterior equals
        the sample prior (same as MVO).
      </p>
    </div>
  );
}
