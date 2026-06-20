// Units API client — the canonical unit system (dimensions + allowed units +
// per-unit factors), served by GET /api/units. Pure logic layer: no React imports.
// The unit picker reads its allowed-unit lists from here so it can't drift from
// the model's own validation (the backend is the single source of truth).

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}: ${await resp.text()}`);
  return (await resp.json()) as T;
}

export interface UnitDimension {
  base: string;
  allowed: string[];
}

export interface UnitsConfig {
  dimensions?: Record<string, UnitDimension>;
  custom_units?: string[];
  kind_dimension?: Record<string, string>;
}

export interface UnitsBundle {
  config: UnitsConfig;
  /** Per allowed unit: its dimension + factor to that dimension's base (from pint). */
  factors?: Record<string, unknown>;
}

export async function getUnits(): Promise<UnitsBundle> {
  return json<UnitsBundle>(await fetch("/api/units"));
}

/** Every allowed unit across all dimensions, de-duplicated — for unit pickers. */
export function allowedUnits(config: UnitsConfig | undefined): string[] {
  const out = new Set<string>();
  for (const d of Object.values(config?.dimensions ?? {})) {
    for (const u of d.allowed ?? []) out.add(u);
  }
  return [...out];
}
