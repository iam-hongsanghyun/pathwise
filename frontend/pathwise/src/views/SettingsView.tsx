import { useState } from "react";
import { SearchSelect } from "../features/controls/SearchSelect";
import { RailList, type RailItem } from "../layout/RailList";
import { Resizer } from "../layout/Resizer";
import type { Density, ThemeName } from "../lib/useTheme";
import type {
  AssetLevel,
  ConfigBundle,
  PortfolioConfig,
  PortfolioMethod,
  RewardMode,
} from "../types";

type Section = "appearance" | "economics" | "method" | "snapshots" | "solver" | "policy";
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
  theme: ThemeName;
  onTheme: (t: ThemeName) => void;
  density: Density;
  onDensity: (d: Density) => void;
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
  theme,
  onTheme,
  density,
  onDensity,
  leftW,
  setLeftW,
}: Props) {
  const [section, setSection] = useState<Section>("appearance");
  const items: RailItem[] = [
    { id: "appearance", label: "Appearance" },
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
          {section === "appearance" && (
            <section className="card">
              <h3>Appearance</h3>
              <label className="inspector-field">
                <span>Theme</span>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div className="pw-swatches">
                    <button
                      className={`pw-swatch sw-refined${theme === "refined" ? " is-active" : ""}`}
                      title="Refined — crisp, flat, light"
                      aria-label="Refined theme"
                      onClick={() => onTheme("refined")}
                    />
                    <button
                      className={`pw-swatch sw-warm${theme === "warm" ? " is-active" : ""}`}
                      title="Warm — softer neutrals, gentle depth"
                      aria-label="Warm theme"
                      onClick={() => onTheme("warm")}
                    />
                    <button
                      className={`pw-swatch sw-bold${theme === "bold" ? " is-active" : ""}`}
                      title="Bold Studio — dark chrome, brighter accent"
                      aria-label="Bold Studio theme"
                      onClick={() => onTheme("bold")}
                    />
                  </div>
                  <span className="muted" style={{ textTransform: "capitalize" }}>
                    {theme === "bold" ? "Bold Studio" : theme}
                  </span>
                </div>
              </label>
              <label className="inspector-field">
                <span>Density</span>
                <SearchSelect value={density} onChange={(v) => onDensity(v as Density)}
                  options={[
                    { value: "compact", label: "Compact" },
                    { value: "comfortable", label: "Comfortable" },
                    { value: "spacious", label: "Spacious" },
                  ]} />
              </label>
              <p className="muted">
                Theme and density are saved to this browser. <strong>Refined</strong> is the default
                light theme; <strong>Bold Studio</strong> is dark.
              </p>
            </section>
          )}
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
                <SearchSelect value={objScope} onChange={(v) => onObjScope(v as Scope)}
                  options={[
                    { value: "company", label: "Each company (independent targets)" },
                    { value: "system", label: "The whole economy (one shared target)" },
                    { value: "facility", label: "Each facility (independent targets)" },
                  ]} />
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
                <SearchSelect value={backend} onChange={onBackend}
                  options={backends.map((b) => ({ value: b.name, label: b.label }))} />
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
                    <SearchSelect value={portfolio.method} onChange={(v) => set({ method: v as PortfolioMethod })}
                      options={(Object.keys(METHOD_LABEL) as PortfolioMethod[]).map((m) => ({ value: m, label: METHOD_LABEL[m] }))} />
                  </label>
                  <label className="inspector-field">
                    <span>Reward basis</span>
                    <SearchSelect value={portfolio.reward_mode} onChange={(v) => set({ reward_mode: v as RewardMode })}
                      options={[
                        { value: "cost_reduction", label: "Cost reduction vs baseline" },
                        { value: "profit", label: "Profit (revenue − cost)" },
                      ]} />
                  </label>
                  <label className="inspector-field">
                    <span>Asset granularity</span>
                    <SearchSelect value={portfolio.asset_level} onChange={(v) => set({ asset_level: v as AssetLevel })}
                      options={[
                        { value: "facility", label: "Per facility × technology" },
                        { value: "technology", label: "Per technology (economy-wide)" },
                        { value: "company", label: "Per company" },
                        { value: "economy", label: "Whole economy (by technology)" },
                      ]} />
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
                        <SearchSelect value={byTarget ? "target" : "aversion"}
                          onChange={(v) => set({ target_return: v === "target" ? 0 : null })}
                          options={[{ value: "aversion", label: "Risk aversion" }, { value: "target", label: "Target return" }]} />
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
                <SearchSelect disabled value="annual" onChange={() => undefined}
                  options={[{ value: "annual", label: "Annual (per period)" }]} />
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
