// Per-machine annual production bounds. A bound is a YEAR-LESS row on the
// `max_production` / `min_production` sheet: the engine (assemble._temporal_dict
// base_years) applies it to every run year, so one value = an annual ceiling /
// floor across the whole horizon. Scope is a node id (a machine, a group) or
// "all" (system / national).

import type { Cell, Row, Workbook } from "../types";

const s = (v: Cell | undefined): string => (v == null ? "" : String(v));
const isYearless = (r: Row): boolean => r.year == null || String(r.year).trim() === "";

/** The product commodity a per-machine output bound limits: the `is_product`
 *  output of the machine's baseline technology (else its first output), or null. */
export function machineProduct(wb: Workbook, machineId: string): string | null {
  const m = (wb.machines ?? []).find((r) => s(r.machine_id) === machineId);
  const tech = s(m?.baseline_technology);
  if (!tech) return null;
  const outs = (wb.io ?? []).filter((r) => s(r.technology_id) === tech && s(r.role) === "output");
  const prod =
    outs.find((r) => r.is_product === true || s(r.is_product) === "true" || Number(r.is_product) === 1) ??
    outs[0];
  return prod ? s(prod.target) || null : null;
}

/** A commodity's declared unit (t, MWh, …) — what a bound on it is measured in. */
export function commodityUnit(wb: Workbook, commodity: string): string {
  const row = (wb.commodities ?? []).find((r) => s(r.commodity_id) === commodity);
  return s(row?.unit) || "unit";
}

/** The year-less bound on `commodity` at `scope` in `sheet`, or null if unset. */
function cap(wb: Workbook, sheet: string, scope: string, commodity: string): number | null {
  const row = (wb[sheet] ?? []).find(
    (r) => s(r.company) === scope && s(r.commodity_id) === commodity && isYearless(r),
  );
  return row ? Number(row.amount) || 0 : null;
}

/** Upsert (or clear, when `amount` is null/≤0) the year-less bound. New workbook. */
function setCap(
  wb: Workbook,
  sheet: string,
  scope: string,
  commodity: string,
  amount: number | null,
): Workbook {
  const rows = (wb[sheet] ?? []).filter(
    (r) => !(s(r.company) === scope && s(r.commodity_id) === commodity && isYearless(r)),
  );
  if (amount != null && amount > 0) rows.push({ company: scope, commodity_id: commodity, amount });
  return { ...wb, [sheet]: rows };
}

export const maxOutputCap = (wb: Workbook, scope: string, commodity: string): number | null =>
  cap(wb, "max_production", scope, commodity);
export const setMaxOutputCap = (
  wb: Workbook,
  scope: string,
  commodity: string,
  amount: number | null,
): Workbook => setCap(wb, "max_production", scope, commodity, amount);

export const minOutputCap = (wb: Workbook, scope: string, commodity: string): number | null =>
  cap(wb, "min_production", scope, commodity);
export const setMinOutputCap = (
  wb: Workbook,
  scope: string,
  commodity: string,
  amount: number | null,
): Workbook => setCap(wb, "min_production", scope, commodity, amount);
