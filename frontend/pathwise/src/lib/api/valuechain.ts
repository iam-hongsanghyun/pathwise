// Value-chain API client: list / load / run coupled multi-stage models.
// Types mirror src/pathwise/data/valuechain.py and core.valuechain output.

export interface VcStage {
  id: string;
  label?: string;
  model?: string;
  region?: string;
  sector?: string;
}

export interface VcLink {
  from_stage: string;
  to_stage: string;
  commodity: string;
  signals?: string[];
  impact?: string;
  lag_years?: number;
  feedback?: boolean;
  alternative_of?: string | null;
}

export interface ValueChainSpec {
  id: string;
  label?: string;
  stages: VcStage[];
  links: VcLink[];
}

export interface VcIndexEntry {
  id: string;
  label: string;
  file?: string;
  description?: string;
}

export interface VcCouplingPoint {
  year: number;
  value: number;
}

export interface VcCoupling {
  from_stage: string;
  to_stage: string;
  commodity: string;
  signal: string;
  lag_years: number;
  impact?: string;
  by_year: VcCouplingPoint[];
}

export interface VcStageResult {
  status: string;
  objective: number | null;
  outputs?: Record<string, unknown[]>;
  summary?: Record<string, unknown[]>;
}

export interface VcRunResult {
  status: string;
  stages: Record<string, VcStageResult>;
  couplings: VcCoupling[];
  iterations?: number;
}

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}: ${await resp.text()}`);
  return (await resp.json()) as T;
}

/** List the value chains the backend serves. */
export async function listValueChains(): Promise<VcIndexEntry[]> {
  const res = await fetch("/api/value-chains");
  if (!res.ok) return [];
  return (await res.json()) as VcIndexEntry[];
}

/** Fetch one value-chain spec (stages + coupling links). */
export async function loadValueChain(id: string): Promise<ValueChainSpec> {
  return json<ValueChainSpec>(await fetch(`/api/value-chain/${encodeURIComponent(id)}`));
}

/** Solve a value chain as a forward cascade; returns per-stage results + couplings. */
export async function runValueChain(
  id: string,
  scenario: Record<string, unknown> = {},
): Promise<VcRunResult> {
  return json<VcRunResult>(
    await fetch(`/api/value-chain/${encodeURIComponent(id)}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario }),
    }),
  );
}
