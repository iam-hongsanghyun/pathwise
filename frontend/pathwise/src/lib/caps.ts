// Per-machine annual production bounds. A bound is a YEAR-LESS row on the
// `max_production` / `min_production` sheet: the engine (assemble._temporal_dict
// base_years) applies it to every run year, so one value = an annual ceiling /
// floor across the whole horizon. Scope is a node id (a machine, a group) or
// "all" (system / national).

import type { ByYear } from "./api/components";
import type { Cell, Row, Workbook } from "../types";

/** A bound: a scalar (every year) or a {year: value} map. Mirrors TemporalVal. */
export type Bound = number | ByYear;

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

/** The bound on `commodity` at `scope` in `sheet`: a {year: value} map if there are
 *  per-year rows, a number if a single year-less (static) row, else null. */
function cap(wb: Workbook, sheet: string, scope: string, commodity: string): Bound | null {
  const rows = (wb[sheet] ?? []).filter(
    (r) => s(r.company) === scope && s(r.commodity_id) === commodity,
  );
  if (!rows.length) return null;
  const yearRows = rows.filter((r) => !isYearless(r));
  if (yearRows.length) {
    const by: ByYear = {};
    for (const r of yearRows) by[String(Math.round(Number(r.year)))] = Number(r.amount) || 0;
    return by;
  }
  return Number(rows[0].amount) || 0;
}

/** Upsert (or clear, when `value` is null) the bound: a static value writes ONE
 *  year-less row; a temporal value writes one row per year. New workbook. */
function setCap(wb: Workbook, sheet: string, scope: string, commodity: string, value: Bound | null): Workbook {
  const rows = (wb[sheet] ?? []).filter(
    (r) => !(s(r.company) === scope && s(r.commodity_id) === commodity),
  );
  if (value != null) {
    if (typeof value === "number") {
      if (value > 0) rows.push({ company: scope, commodity_id: commodity, amount: value });
    } else {
      for (const [yr, v] of Object.entries(value)) rows.push({ company: scope, commodity_id: commodity, year: Number(yr), amount: v });
    }
  }
  return { ...wb, [sheet]: rows };
}

export const maxOutputCap = (wb: Workbook, scope: string, commodity: string): Bound | null =>
  cap(wb, "max_production", scope, commodity);
export const setMaxOutputCap = (wb: Workbook, scope: string, commodity: string, value: Bound | null): Workbook =>
  setCap(wb, "max_production", scope, commodity, value);

export const minOutputCap = (wb: Workbook, scope: string, commodity: string): Bound | null =>
  cap(wb, "min_production", scope, commodity);
export const setMinOutputCap = (wb: Workbook, scope: string, commodity: string, value: Bound | null): Workbook =>
  setCap(wb, "min_production", scope, commodity, value);

// ── Source-stream supply cap (max_purchase) ──────────────────────────────────
// A static cap is the `max_purchase` column on the commodities row; a temporal
// cap lives in the WIDE `commodities_t__max_purchase` sheet (one row per year, a
// column named by each commodity). The engine interpolates the temporal series,
// else falls back to the static value.

const SUPPLY_T = "commodities_t__max_purchase";

/** The supply cap for `commodity`: a {year: value} map if the wide temporal sheet
 *  carries it, a number if a static `max_purchase`, else null. */
export function supplyCap(wb: Workbook, commodity: string): Bound | null {
  const by: ByYear = {};
  for (const r of wb[SUPPLY_T] ?? []) {
    const yr = r.year;
    const v = (r as Record<string, Cell>)[commodity];
    if (yr != null && String(yr).trim() !== "" && v != null && String(v).trim() !== "")
      by[String(Math.round(Number(yr)))] = Number(v) || 0;
  }
  if (Object.keys(by).length) return by;
  const row = (wb.commodities ?? []).find((r) => s(r.commodity_id) === commodity);
  const mp = row?.max_purchase;
  return mp == null || String(mp).trim() === "" ? null : Number(mp) || 0;
}

/** Upsert (or clear, when `value` is null) the supply cap. A static value sets the
 *  `max_purchase` column; a temporal value writes the wide sheet. The two stores
 *  are kept mutually exclusive so the engine reads one source of truth. */
export function setSupplyCap(wb: Workbook, commodity: string, value: Bound | null): Workbook {
  // Drop this commodity's column from every wide row, then drop emptied rows.
  const tRows = (wb[SUPPLY_T] ?? [])
    .map((r) => {
      const { [commodity]: _drop, ...rest } = r as Record<string, Cell>;
      return rest as Row;
    })
    .filter((r) => Object.keys(r).some((k) => k !== "year" && String(r[k] ?? "").trim() !== ""));
  const commodities = (wb.commodities ?? []).map((r) =>
    s(r.commodity_id) === commodity ? { ...r, max_purchase: "" } : r,
  );

  if (value == null) return { ...wb, commodities, [SUPPLY_T]: tRows };

  if (typeof value === "number") {
    return {
      ...wb,
      [SUPPLY_T]: tRows,
      commodities: commodities.map((r) => (s(r.commodity_id) === commodity ? { ...r, max_purchase: value } : r)),
    };
  }

  // Temporal: merge the commodity's column into the per-year wide rows.
  const byYearRow = new Map<string, Row>();
  for (const r of tRows) byYearRow.set(String(Math.round(Number(r.year))), r);
  for (const [yr, v] of Object.entries(value)) {
    const key = String(Math.round(Number(yr)));
    const existing = byYearRow.get(key) ?? { year: Number(key) };
    byYearRow.set(key, { ...existing, [commodity]: v });
  }
  return { ...wb, commodities, [SUPPLY_T]: Array.from(byYearRow.values()) };
}
