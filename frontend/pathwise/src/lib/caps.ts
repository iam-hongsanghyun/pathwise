// Per-machine / per-stream annual output caps. A cap is a YEAR-LESS row on the
// `max_production` sheet: the engine (assemble._temporal_dict base_years) applies
// it to every run year, so one value = an annual ceiling across the whole horizon.
// Scope is a node id (a machine, a group) or "all" (system / national).

import type { Cell, Row, Workbook } from "../types";

const s = (v: Cell | undefined): string => (v == null ? "" : String(v));
const isYearless = (r: Row): boolean => r.year == null || String(r.year).trim() === "";

/** The product commodity a per-machine output cap limits: the `is_product` output
 *  of the machine's baseline technology (else its first output), or null. */
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

/** The current annual cap on `commodity` at `scope` (the year-less row), or null. */
export function maxOutputCap(wb: Workbook, scope: string, commodity: string): number | null {
  const row = (wb.max_production ?? []).find(
    (r) => s(r.company) === scope && s(r.commodity_id) === commodity && isYearless(r),
  );
  return row ? Number(row.amount) || 0 : null;
}

/** Upsert (or clear, when `amount` is null/≤0) the year-less cap on `commodity`
 *  at `scope`. Returns a new workbook. */
export function setMaxOutputCap(
  wb: Workbook,
  scope: string,
  commodity: string,
  amount: number | null,
): Workbook {
  const rows = (wb.max_production ?? []).filter(
    (r) => !(s(r.company) === scope && s(r.commodity_id) === commodity && isYearless(r)),
  );
  if (amount != null && amount > 0) rows.push({ company: scope, commodity_id: commodity, amount });
  return { ...wb, max_production: rows };
}
