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

export interface JobState {
  jobId: string;
  status: "running" | "done" | "error" | "cancelled";
  result?: RunResult;
  error?: string;
}
