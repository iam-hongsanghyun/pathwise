// Shared recipe summariser — turns a technology's IO rows into a readable
// "deploy N units → consumes / produces / emits" read-out. Pure; used by both the
// Component builder (TechnologyEditor) and the Value-chain builder (AssetInspector)
// so the preview reads identically in both.

const s = (v: unknown): string => (v == null ? "" : String(v));
const num = (v: unknown): number => (v == null || v === "" ? 0 : Number(v) || 0);

export interface RecipeLine {
  stream: string;
  perUnit: number;
  total: number;
  isProduct?: boolean;
  /** Authored unit of the coefficient, if the row declares one. */
  unit?: string;
}
export interface RecipeSummary {
  inputs: RecipeLine[];
  outputs: RecipeLine[];
  impacts: RecipeLine[];
}

/** Minimal structural shape of an IO row — matches both the library's `IoRow`
 *  and a raw workbook `Row`, so both builders can pass their rows directly. */
export interface IoLike {
  role?: unknown;
  target?: unknown;
  coefficient?: unknown;
  is_product?: unknown;
  unit?: unknown;
}

/** Summarise a technology's IO (already filtered to one technology's rows),
 *  scaling per-unit coefficients by `n` units of throughput. */
export function summarizeRecipe(ioRows: ReadonlyArray<IoLike>, n = 1): RecipeSummary {
  const line = (r: IoLike): RecipeLine => {
    const perUnit = num(r.coefficient);
    return { stream: s(r.target), perUnit, total: perUnit * n, isProduct: !!r.is_product, unit: s(r.unit) || undefined };
  };
  return {
    inputs: ioRows.filter((r) => s(r.role) === "input").map(line),
    outputs: ioRows.filter((r) => s(r.role) === "output").map(line),
    impacts: ioRows.filter((r) => s(r.role) === "impact").map(line),
  };
}
