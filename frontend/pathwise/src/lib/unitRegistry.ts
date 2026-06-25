// The project's conversion-factor registry — the `units` sheet on the model. It
// is the single source of allowed units (the closed vocabulary unit pickers draw
// from) and the per-project conversion factors (base-anchored: 1 unit = factor ×
// dimension-base). Seeded from the units the model already uses; fed to the engine
// as pint unit_overrides at assembly. Pure logic: no React.

import type { Row, Workbook } from "../types";
import type { UnitsBundle } from "./api/units";

const s = (v: unknown): string => (v == null ? "" : String(v));

export interface UnitRow {
  unit: string;
  dimension: string;
  factor_to_base: number;
}

type FactorInfo = { dimension?: string; factor_to_base?: number };

/** The registry rows (the model's `units` sheet). */
export function projectUnitRows(wb: Workbook): UnitRow[] {
  return (wb.units ?? [])
    .map((r) => ({
      unit: s(r.unit),
      dimension: s(r.dimension),
      factor_to_base: Number(r.factor_to_base),
    }))
    .filter((r) => r.unit);
}

/** Unit ids in the registry — the closed vocabulary for every unit picker. */
export function projectUnits(wb: Workbook): string[] {
  return [...new Set(projectUnitRows(wb).map((r) => r.unit))];
}

/** Registry units in a given dimension (e.g. `currency` for the currency picker). */
export function unitsForDimension(wb: Workbook, dimension: string): string[] {
  return projectUnitRows(wb)
    .filter((r) => r.dimension === dimension)
    .map((r) => r.unit);
}

/** Write registry rows back onto the `units` sheet. */
export function setProjectUnitRows(wb: Workbook, rows: UnitRow[]): Workbook {
  const out: Row[] = rows.map((r) => ({
    unit: r.unit,
    dimension: r.dimension,
    factor_to_base: r.factor_to_base,
  }));
  return { ...wb, units: out };
}

/** Units the model references today — flow / impact / io-coefficient units
 *  plus the model currency. The set the registry must cover so nothing breaks. */
export function usedUnits(wb: Workbook): string[] {
  const out = new Set<string>();
  const add = (v: unknown) => {
    const u = s(v);
    if (u) out.add(u);
  };
  for (const r of wb.flows ?? []) add(r.unit);
  for (const r of wb.impacts ?? []) add(r.unit);
  for (const r of wb.io ?? []) if (s(r.role) === "impact" || r.unit != null) add(r.unit);
  const cur = (wb.meta ?? []).find((r) => s(r.key) === "currency");
  if (cur) add(cur.value);
  return [...out].filter(Boolean);
}

/** Seed registry rows from the model's used units, resolving each to its dimension
 *  + factor-to-base via the global unit factors (GET /api/units). Existing rows are
 *  kept (their edited factors win); only missing units are added. */
export function seedUnitRows(wb: Workbook, bundle: UnitsBundle | null): UnitRow[] {
  const byUnit = new Map(projectUnitRows(wb).map((r) => [r.unit, r]));
  const factors = (bundle?.factors ?? {}) as Record<string, FactorInfo>;
  for (const u of usedUnits(wb)) {
    if (byUnit.has(u)) continue;
    const f = factors[u];
    byUnit.set(u, {
      unit: u,
      dimension: s(f?.dimension),
      factor_to_base: typeof f?.factor_to_base === "number" ? f.factor_to_base : 1,
    });
  }
  return [...byUnit.values()];
}
