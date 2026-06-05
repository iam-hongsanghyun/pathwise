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
  backends: { name: string; label: string; features?: Record<string, boolean> }[];
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
  };
  summary: {
    periods: { period: number; cost?: number }[];
    impacts: { period: number; impact: string; total: number }[];
    commodity: { commodity: string; period: number; consumed: number; produced: number }[];
  };
}

export interface JobState {
  jobId: string;
  status: "running" | "done" | "error" | "cancelled";
  result?: RunResult;
  error?: string;
}
