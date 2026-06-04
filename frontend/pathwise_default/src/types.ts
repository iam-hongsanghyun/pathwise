// Shared types mirroring the pathwise API contract.

export type Row = Record<string, unknown>;
export type Workbook = Record<string, Row[]>;

export interface DomainCapability {
  name: string;
  label: string;
  terminology: Record<string, string>;
  requiredSheets: string[];
  schema: Record<string, { label?: string; columns?: Record<string, unknown> }>;
}

export interface BackendCapability {
  name: string;
  label: string;
  solver?: string;
  features?: Record<string, boolean>;
}

/** The backend handshake — server-side truths only (no model defaults). */
export interface ConfigBundle {
  schemaVersion: string;
  version: string;
  domains: DomainCapability[];
  backends: BackendCapability[];
  server: { solver: string; maxSolverTimeLimitS: number; defaultMipGap: number };
  buildId: string;
}

export interface PeriodSummary {
  period: number;
  energy_mj: number;
  emissions_tco2e: number;
  intensity_gco2e_per_mj: number;
}

export interface RunResult {
  status: string;
  termination: string;
  objective: number | null;
  terminology: Record<string, string>;
  validation: { errors: string[]; warnings: string[] };
  outputs: {
    chosen_technology: { asset: string; technology: string; period: number }[];
    transitions: { asset: string; to_technology: string; period: number }[];
    new_builds: { asset: string; period: number }[];
    measures: { asset: string; measure: string; block: number; period: number; adoption: number }[];
    slack: { kind: string; group: string; period: number; value: number }[];
    carrier_energy: { asset: string; carrier: string; period: number; energy_mj: number }[];
  };
  summary: { periods: PeriodSummary[] };
}

export interface JobState {
  jobId: string;
  status: "running" | "done" | "error" | "cancelled";
  result?: RunResult;
  error?: string;
}

/** User-definable model config (owned by the frontend, sent with each run). */
export interface Scenario {
  name: string;
  domain: string;
  selection: { target_set?: string };
  economics: {
    discount_rate: number;
    base_period?: number;
    capex_convention: "annuity" | "npv";
    default_measure_lifetime?: number;
    default_newbuild_lifetime?: number;
    currency?: string;
  };
  features: Record<string, boolean>;
  solver: { name: string; threads: number; time_limit_s: number; mip_gap: number };
}
