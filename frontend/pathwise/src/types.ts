// Shared types mirroring the pathwise API contract.

export type Cell = string | number | boolean | null;
export type Row = Record<string, Cell>;
export type Workbook = Record<string, Row[]>;

/** A selected model entity (drives the right-rail inspector). */
export interface Selection {
  sheet: string;
  idCol: string;
  id: string;
}

export interface DomainCapability {
  name: string;
  label: string;
  terminology: Record<string, string>;
  requiredSheets: string[];
  schema: Record<string, { label?: string; columns?: Record<string, { label?: string }> }>;
}

export interface ConfigBundle {
  schemaVersion: string;
  version: string;
  domains: DomainCapability[];
  backends: { name: string; label: string; features?: Record<string, unknown> }[];
  server: { solver: string; maxSolverTimeLimitS: number; defaultMipGap: number };
  buildId: string;
}

export interface RunResult {
  status: string;
  termination: string;
  objective: number | null;
  terminology: Record<string, string>;
  validation: { errors: string[]; warnings: string[] };
  outputs: {
    technology: { process: string; technology: string; period: number }[];
    throughput: { process: string; technology: string; period: number; value: number }[];
    transitions: { process: string; to_technology: string; period: number }[];
    renewals: { process: string; technology: string; period: number }[];
    measures: {
      process: string | null;
      measure: string;
      type: string | null;
      period: number;
      adoption: number;
    }[];
    flows: { from: string; to: string; commodity: string; period: number; value: number }[];
    trade: { process: string; commodity: string; period: number; kind: string; value: number }[];
    storage: {
      storage: string;
      commodity: string | null;
      capacity: number;
      by_period: { period: number; level: number; charge: number; discharge: number }[];
    }[];
    markets: {
      market: string;
      commodity: string;
      tag: string | null;
      by_period: { period: number; buy: number; sell: number }[];
    }[];
    ets: {
      market: string;
      impact: string;
      by_period: { period: number; bought: number; sold: number }[];
    }[];
    demand_slack: { key: string; value: number }[];
    portfolio?: PortfolioResultBlock;
    macc?: MaccResultBlock;
    lca?: LcaBlock;
    variants?: VariantBlock[];
    comparison?: ComparisonRow[];
    policy_sweep?: PolicySweepRow[];
    cap_compliance?: CapComplianceRow[];
  };
  summary: {
    periods: { period: number; cost?: number }[];
    impacts: { period: number; impact: string; total: number }[];
    commodity: { commodity: string; period: number; consumed: number; produced: number }[];
  };
}

// ── Portfolio backend ────────────────────────────────────────────────────────

export type PortfolioMethod = "mvo" | "cvar" | "hrp" | "black_litterman";
export type RewardMode = "profit" | "cost_reduction";
export type AssetLevel = "facility" | "technology" | "company" | "economy";

export interface BlackLittermanView {
  asset: string;
  view: number;
}

/** The run-time config for the portfolio backend (sent inside `scenario`). */
export interface PortfolioConfig {
  method: PortfolioMethod;
  reward_mode: RewardMode;
  asset_level: AssetLevel;
  n_scenarios: number;
  volatility: number; // 0 ⇒ use the engine's per-category defaults
  risk_aversion: number;
  target_return: number | null; // null ⇒ optimise by risk aversion
  cvar_alpha: number;
  views: BlackLittermanView[];
}

export interface PortfolioAsset {
  asset_id: string;
  label: string;
  company: string;
  from_technology: string;
  to_technology: string;
  transition_capex: number;
  weight: number;
  expected_return: number;
  std: number;
}

export interface PortfolioResultBlock {
  method: string;
  reward_mode: RewardMode;
  asset_level: string;
  normalize_by_capex: boolean;
  n_scenarios: number;
  expected_return: number;
  variance: number;
  risk: number;
  cvar: number | null;
  objective: number;
  chosen: { return: number; risk: number };
  frontier: { return: number; risk: number }[];
  distribution: number[];
  assets: PortfolioAsset[];
}

// ── MACC backend (greedy abatement) ───────────────────────────────────────────

export interface MaccYear {
  year: number;
  bau: number;
  target: number;
  required: number;
  abated: number;
  actual_emissions: number;
  shortfall: number;
  annual_capex: number;
  cumulative_capex: number;
  deployed: Record<string, number>;
}

export interface MaccResultBlock {
  impact_id: string;
  by_year: MaccYear[];
  options: { option_id: string; label: string; deployed: number }[];
  cumulative_capex: number;
}

// ── Simulate backend (LCA what-if) ────────────────────────────────────────────

/** A lifecycle inventory: emissions by stage / by impact, normalised per
 *  functional unit, plus the configuration's cost (incl. its carbon cost). */
export interface LcaBlock {
  functional_unit: { commodity: string | null; amount: number };
  by_impact: { impact: string; total: number; per_unit: number }[];
  by_stage: { stage: string; impact: string; total: number; per_unit: number }[];
  cost: { total: number; carbon: number; per_unit: number };
}

/** One evaluated variant (baseline + overrides). `lca` is null if it failed. */
export interface VariantBlock {
  label: string;
  status: string;
  lca: LcaBlock | null;
}

/** Baseline-vs-variant diff: abatement, ex-carbon cost delta, $/impact-unit, and
 *  the carbon price at which the variant overtakes the baseline. */
export interface ComparisonRow {
  label: string;
  status: string;
  impact?: string;
  abatement?: number;
  cost_delta?: number;
  abatement_cost_per_unit?: number | null;
  breakeven_carbon_price?: number | null;
}

/** One carbon-price point of the policy sweep: every config's cost & emissions. */
export interface PolicySweepRow {
  carbon_price: number;
  impact: string;
  variants: { label: string; cost: number | null; emissions: number | null }[];
}

/** A configuration's per-year emissions vs the impact caps. */
export interface CapComplianceRow {
  label: string;
  status: string;
  compliant?: boolean;
  by_year?: { impact: string; year: number; emissions: number; cap: number; over: number }[];
}

export interface JobState {
  jobId: string;
  status: "running" | "done" | "error" | "cancelled";
  result?: RunResult;
  error?: string;
}
