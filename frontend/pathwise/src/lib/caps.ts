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

/** An impact's declared unit (t, t CO2e, mol H+ eq, …) — what a cap on it is
 *  measured in. Read from the model's `impacts` sheet; "unit" if undeclared. */
export function impactUnit(wb: Workbook, impactId: string): string {
  const row = (wb.impacts ?? []).find((r) => s(r.impact_id) === impactId);
  return s(row?.unit) || "unit";
}

/** The model's accounting / display currency — the `meta` row keyed "currency".
 *  Defaults to "USD" (the currency dimension's base in units.yaml). This is the
 *  symbol every monetary value (costs, prices, budgets) is shown in. */
export function modelCurrency(wb: Workbook): string {
  const row = (wb.meta ?? []).find((r) => s(r.key) === "currency");
  return s(row?.value) || "USD";
}

/** Set the model currency in the `meta` key/value sheet (update in place, else
 *  insert). The numeric values are NOT reconverted — this sets the unit label. */
export function setModelCurrency(wb: Workbook, currency: string): Workbook {
  return setMeta(wb, "currency", currency);
}

/** The model's discount rate (meta key "discount_rate"); 0.08 default. Used for
 *  NPV — sent into the run so the Project-tab value actually drives the solve. */
export function modelDiscount(wb: Workbook): number {
  const row = (wb.meta ?? []).find((r) => s(r.key) === "discount_rate");
  const v = Number(row?.value);
  return Number.isFinite(v) ? v : 0.08;
}

/** Set the model discount rate in the `meta` key/value sheet. */
export function setModelDiscount(wb: Workbook, rate: number): Workbook {
  return setMeta(wb, "discount_rate", rate);
}

/** Upsert a key/value row on the model's `meta` sheet. */
function setMeta(wb: Workbook, key: string, value: Cell): Workbook {
  const meta = [...((wb.meta as Row[]) ?? [])];
  const i = meta.findIndex((r) => s(r.key) === key);
  if (i >= 0) meta[i] = { ...meta[i], value };
  else meta.push({ key, value });
  return { ...wb, meta };
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

// Per-machine intake bounds on a consumed commodity (the consumer-side mirror of
// the output caps): min = required offtake (a floor), max = maximum purchase.
export const minConsumptionCap = (wb: Workbook, scope: string, commodity: string): Bound | null =>
  cap(wb, "min_consumption", scope, commodity);
export const setMinConsumptionCap = (wb: Workbook, scope: string, commodity: string, value: Bound | null): Workbook =>
  setCap(wb, "min_consumption", scope, commodity, value);

export const maxConsumptionCap = (wb: Workbook, scope: string, commodity: string): Bound | null =>
  cap(wb, "max_consumption", scope, commodity);
export const setMaxConsumptionCap = (wb: Workbook, scope: string, commodity: string, value: Bound | null): Workbook =>
  setCap(wb, "max_consumption", scope, commodity, value);

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

// ── Per-connection flow bounds (min / max offtake on one provider→consumer link) ─
// A static bound is the `min_flow` / `max_flow` column on the connection row; a
// temporal bound lives in the long `connections_t` sheet (from_node, to_node,
// commodity_id, year, min_flow, max_flow), which the engine fans onto edges and
// interpolates. The two stores are kept mutually exclusive per bound.

const CONN_T = "connections_t";
type FlowSide = "min_flow" | "max_flow";

const matchesConn = (r: Row, from: string, to: string, commodity: string): boolean =>
  s(r.from_node) === from && s(r.to_node) === to && s(r.commodity_id) === commodity;

/** One side's bound for a connection: a {year: value} map if `connections_t`
 *  carries it, a number if a static column, else null. */
function connBound(wb: Workbook, from: string, to: string, commodity: string, side: FlowSide): Bound | null {
  const by: ByYear = {};
  for (const r of wb[CONN_T] ?? []) {
    if (!matchesConn(r, from, to, commodity)) continue;
    const v = (r as Record<string, Cell>)[side];
    if (!isYearless(r) && v != null && String(v).trim() !== "")
      by[String(Math.round(Number(r.year)))] = Number(v) || 0;
  }
  if (Object.keys(by).length) return by;
  const row = (wb.connections ?? []).find((r) => matchesConn(r, from, to, commodity));
  const v = (row as Record<string, Cell> | undefined)?.[side];
  return v == null || String(v).trim() === "" ? null : Number(v) || 0;
}

/** Both bounds for a connection (for the connection editor's initial state). */
export const connectionFlow = (
  wb: Workbook,
  from: string,
  to: string,
  commodity: string,
): { min: Bound | null; max: Bound | null } => ({
  min: connBound(wb, from, to, commodity, "min_flow"),
  max: connBound(wb, from, to, commodity, "max_flow"),
});

/** The scalar to write on a connection row: the number itself, else blank (a
 *  temporal or absent bound lives in `connections_t`, not the row). */
export const connStatic = (b: Bound | null): Cell => (typeof b === "number" ? b : "");

/** Rewrite the `connections_t` rows for one connection: drop its existing rows,
 *  then add a per-year row for each temporal bound (min/max merged per year). */
export function setConnectionTemporal(
  wb: Workbook,
  from: string,
  to: string,
  commodity: string,
  min: Bound | null,
  max: Bound | null,
): Workbook {
  const rows = (wb[CONN_T] ?? []).filter((r) => !matchesConn(r, from, to, commodity));
  const byYear = new Map<string, Row>();
  const add = (b: Bound | null, side: FlowSide) => {
    if (b == null || typeof b === "number") return;
    for (const [yr, v] of Object.entries(b)) {
      const key = String(Math.round(Number(yr)));
      const ex = byYear.get(key) ?? { from_node: from, to_node: to, commodity_id: commodity, year: Number(key) };
      byYear.set(key, { ...ex, [side]: v });
    }
  };
  add(min, "min_flow");
  add(max, "max_flow");
  const merged = [...rows, ...Array.from(byYear.values())];
  if (merged.length) return { ...wb, [CONN_T]: merged };
  // Drop the sheet entirely when nothing is left, to keep the workbook tidy.
  const { [CONN_T]: _drop, ...rest } = wb;
  return rest;
}

/** Set BOTH stores for an EXISTING connection (no new wiring): the static column
 *  on the connection row + the temporal `connections_t` rows. Used when editing a
 *  per-provider bound from the buyer's popup rather than the connection editor. */
export function setConnectionBounds(
  wb: Workbook,
  from: string,
  to: string,
  commodity: string,
  min: Bound | null,
  max: Bound | null,
): Workbook {
  const withStatic: Workbook = {
    ...wb,
    connections: (wb.connections ?? []).map((r) =>
      matchesConn(r, from, to, commodity) ? { ...r, min_flow: connStatic(min), max_flow: connStatic(max) } : r,
    ),
  };
  return setConnectionTemporal(withStatic, from, to, commodity, min, max);
}

// ── Per-machine→machine edge flow bounds (the machine-only per-provider model) ──
// "How much THIS machine buys from THAT provider machine" is a bound between two
// machines — machine-specific by construction. Stored on the `edges` row (static
// columns) + `edges_t` (per-year). The engine seeds these edges so the hierarchy
// fan-out doesn't duplicate the channel.

const EDGES = "edges";
const EDGES_T = "edges_t";

const matchesEdge = (r: Row, from: string, to: string, commodity: string): boolean =>
  s(r.from_process) === from && s(r.to_process) === to && s(r.commodity_id) === commodity;

function edgeBound(wb: Workbook, from: string, to: string, commodity: string, side: FlowSide): Bound | null {
  const by: ByYear = {};
  for (const r of wb[EDGES_T] ?? []) {
    if (!matchesEdge(r, from, to, commodity)) continue;
    const v = (r as Record<string, Cell>)[side];
    if (!isYearless(r) && v != null && String(v).trim() !== "")
      by[String(Math.round(Number(r.year)))] = Number(v) || 0;
  }
  if (Object.keys(by).length) return by;
  const row = (wb[EDGES] ?? []).find((r) => matchesEdge(r, from, to, commodity));
  const v = (row as Record<string, Cell> | undefined)?.[side];
  return v == null || String(v).trim() === "" ? null : Number(v) || 0;
}

/** Both flow bounds for one provider→consumer machine edge (the popup's initial state). */
export const edgeFlow = (
  wb: Workbook,
  from: string,
  to: string,
  commodity: string,
): { min: Bound | null; max: Bound | null } => ({
  min: edgeBound(wb, from, to, commodity, "min_flow"),
  max: edgeBound(wb, from, to, commodity, "max_flow"),
});

/** Set the per-provider bound on the machine→machine edge. Authors an `edges` row
 *  (static columns; suppresses the fanned duplicate) + `edges_t` rows for any
 *  by-year part. Clearing both removes the authored edge so the fan-out restores it. */
export function setEdgeBounds(
  wb: Workbook,
  from: string,
  to: string,
  commodity: string,
  min: Bound | null,
  max: Bound | null,
): Workbook {
  const existing = (wb[EDGES] ?? []).find((r) => matchesEdge(r, from, to, commodity));
  const byYear = new Map<string, Row>();
  const add = (b: Bound | null, side: FlowSide) => {
    if (b == null || typeof b === "number") return;
    for (const [yr, v] of Object.entries(b)) {
      const k = String(Math.round(Number(yr)));
      const ex = byYear.get(k) ?? { from_process: from, to_process: to, commodity_id: commodity, year: Number(k) };
      byYear.set(k, { ...ex, [side]: v });
    }
  };
  add(min, "min_flow");
  add(max, "max_flow");
  const otherT = (wb[EDGES_T] ?? []).filter((r) => !matchesEdge(r, from, to, commodity));
  return writeEdgeRow(
    wb,
    from,
    to,
    commodity,
    { ...existing, min_flow: connStatic(min), max_flow: connStatic(max) },
    [...otherT, ...Array.from(byYear.values())],
  );
}

/** Both ends of a link's availability window, or null (open-ended). */
export const edgeAvailability = (
  wb: Workbook,
  from: string,
  to: string,
  commodity: string,
): { from: number | null; to: number | null } => {
  const r = (wb[EDGES] ?? []).find((x) => matchesEdge(x, from, to, commodity));
  const av = r?.available_from;
  const at = r?.available_to;
  return {
    from: av == null || String(av).trim() === "" ? null : Number(av),
    to: at == null || String(at).trim() === "" ? null : Number(at),
  };
};

/** Set a link's availability window (years it may carry flow), preserving any bounds. */
export function setEdgeAvailability(
  wb: Workbook,
  from: string,
  to: string,
  commodity: string,
  availFrom: number | null,
  availTo: number | null,
): Workbook {
  const existing = (wb[EDGES] ?? []).find((r) => matchesEdge(r, from, to, commodity)) ?? {};
  return writeEdgeRow(
    wb,
    from,
    to,
    commodity,
    { ...existing, available_from: availFrom ?? "", available_to: availTo ?? "" },
    [...(wb[EDGES_T] ?? [])],
  );
}

/** Upsert (or drop, when empty) the authored edge row + set its `edges_t` rows
 *  (callers pass the complete new edges_t list). An edge row is kept only while it
 *  still carries a meaningful field, so clearing everything restores the fan-out. */
function writeEdgeRow(
  wb: Workbook,
  from: string,
  to: string,
  commodity: string,
  fields: Row,
  edgesT: Row[],
): Workbook {
  const otherE = (wb[EDGES] ?? []).filter((r) => !matchesEdge(r, from, to, commodity));
  const has = (k: string): boolean => fields[k] != null && String(fields[k]).trim() !== "";
  const meaningful = ["min_flow", "max_flow", "available_from", "available_to"].some(has);
  const row: Row = { from_process: from, to_process: to, commodity_id: commodity };
  for (const k of ["min_flow", "max_flow", "available_from", "available_to"]) if (has(k)) row[k] = fields[k];
  const edges = meaningful ? [...otherE, row] : otherE;
  const next = { ...wb } as Workbook;
  if (edges.length) next[EDGES] = edges;
  else delete next[EDGES];
  if (edgesT.length) next[EDGES_T] = edgesT;
  else delete next[EDGES_T];
  return next;
}

// ── Static-or-temporal per-instance attributes (Facility machine editor) ─────
// Each numeric field is STATIC (a column on a base-sheet row) or TEMPORAL (a wide
// `_t__` sheet: one row per year, a column named by the id). Mutually exclusive,
// mirroring setSupplyCap, so the engine reads one source of truth.

/** Read the wide-temporal series for `id` from `tSheet` (column = id), or null. */
function wideSeries(wb: Workbook, tSheet: string, id: string): ByYear | null {
  const by: ByYear = {};
  for (const r of wb[tSheet] ?? []) {
    const v = (r as Record<string, Cell>)[id];
    if (r.year != null && String(r.year).trim() !== "" && v != null && String(v).trim() !== "")
      by[String(Math.round(Number(r.year)))] = Number(v) || 0;
  }
  return Object.keys(by).length ? by : null;
}

/** Drop `id`'s column from every wide row of `tSheet`, then merge `value` (a
 *  {year: v} map) back in. Empty rows are pruned. Returns the new sheet rows. */
function wideWrite(wb: Workbook, tSheet: string, id: string, value: ByYear | null): Row[] {
  const rows = (wb[tSheet] ?? [])
    .map((r) => { const { [id]: _drop, ...rest } = r as Record<string, Cell>; return rest as Row; })
    .filter((r) => Object.keys(r).some((k) => k !== "year" && String(r[k] ?? "").trim() !== ""));
  if (!value) return rows;
  const byYear = new Map<string, Row>();
  for (const r of rows) byYear.set(String(Math.round(Number(r.year))), r);
  for (const [yr, v] of Object.entries(value)) {
    const key = String(Math.round(Number(yr)));
    byYear.set(key, { ...(byYear.get(key) ?? { year: Number(key) }), [id]: v });
  }
  return Array.from(byYear.values());
}

/** Bound on a base-sheet column (`col` of the `idCol`=`id` row) OR its wide `tSheet`. */
export function instAttr(
  wb: Workbook, baseSheet: string, idCol: string, id: string, col: string, tSheet: string,
): Bound | null {
  const series = wideSeries(wb, tSheet, id);
  if (series) return series;
  const row = (wb[baseSheet] ?? []).find((r) => s(r[idCol]) === id);
  const v = row?.[col];
  return v == null || String(v).trim() === "" ? null : Number(v) || 0;
}

/** Upsert the attribute: a number sets the static column (clears the wide sheet),
 *  a {year: v} map writes the wide sheet (clears the column), null clears both. */
export function setInstAttr(
  wb: Workbook, baseSheet: string, idCol: string, id: string, col: string, tSheet: string,
  value: Bound | null,
): Workbook {
  const isTemporal = value != null && typeof value !== "number";
  const base = (wb[baseSheet] ?? []).map((r) =>
    s(r[idCol]) === id ? { ...r, [col]: typeof value === "number" ? value : "" } : r,
  );
  const tRows = wideWrite(wb, tSheet, id, isTemporal ? (value as ByYear) : null);
  const next = { ...wb, [baseSheet]: base } as Workbook;
  if (tRows.length) next[tSheet] = tRows;
  else delete next[tSheet];
  return next;
}

// Technology cost (capex / opex / renewal): static column + wide sheet, plus a
// legacy purge of the long `technologies_prices` sheet (which placement may seed)
// so a single source of truth remains.
const TECH_PRICES = "technologies_prices";

export function techCost(wb: Workbook, techId: string, col: string, tSheet: string): Bound | null {
  const wide = instAttr(wb, "technologies", "technology_id", techId, col, tSheet);
  if (wide != null && typeof wide !== "number") return wide; // wide temporal wins
  // long technologies_prices (a `col` cell per tech-year)
  const by: ByYear = {};
  for (const r of wb[TECH_PRICES] ?? []) {
    if (s(r.technology_id) !== techId) continue;
    const v = (r as Record<string, Cell>)[col];
    if (r.year != null && String(r.year).trim() !== "" && v != null && String(v).trim() !== "")
      by[String(Math.round(Number(r.year)))] = Number(v) || 0;
  }
  if (Object.keys(by).length) return by;
  return wide; // static column (or null)
}

export function setTechCost(wb: Workbook, techId: string, col: string, tSheet: string, value: Bound | null): Workbook {
  // Purge the long technologies_prices `col` for this tech (drop emptied rows).
  const long = (wb[TECH_PRICES] ?? [])
    .map((r) => (s(r.technology_id) === techId ? (() => { const { [col]: _d, ...rest } = r as Record<string, Cell>; return rest as Row; })() : r))
    .filter((r) => s(r.technology_id) !== techId || Object.keys(r).some((k) => k !== "technology_id" && k !== "year" && String(r[k] ?? "").trim() !== ""));
  const withLong = { ...wb } as Workbook;
  if (long.length) withLong[TECH_PRICES] = long;
  else delete withLong[TECH_PRICES];
  return setInstAttr(withLong, "technologies", "technology_id", techId, col, tSheet, value);
}

// Recipe coefficient (an io row): static `coefficient` column OR long `io_t` rows
// keyed by (technology_id, role, target, year).
const IO_T = "io_t";

export function ioCoeff(wb: Workbook, techId: string, role: string, target: string): Bound | null {
  const by: ByYear = {};
  for (const r of wb[IO_T] ?? []) {
    if (s(r.technology_id) === techId && s(r.role) === role && s(r.target) === target
        && r.year != null && String(r.year).trim() !== "" && r.coefficient != null && String(r.coefficient).trim() !== "")
      by[String(Math.round(Number(r.year)))] = Number(r.coefficient) || 0;
  }
  if (Object.keys(by).length) return by;
  const row = (wb.io ?? []).find((r) => s(r.technology_id) === techId && s(r.role) === role && s(r.target) === target);
  const c = row?.coefficient;
  return c == null || String(c).trim() === "" ? null : Number(c) || 0;
}

export function setIoCoeff(wb: Workbook, techId: string, role: string, target: string, value: Bound | null): Workbook {
  const match = (r: Row) => s(r.technology_id) === techId && s(r.role) === role && s(r.target) === target;
  const ioT = (wb[IO_T] ?? []).filter((r) => !match(r));
  // keep the static io row (defines the stream) — set its coefficient when static, else clear it
  const io = (wb.io ?? []).map((r) => (match(r) ? { ...r, coefficient: typeof value === "number" ? value : "" } : r));
  if (value != null && typeof value !== "number")
    for (const [yr, v] of Object.entries(value)) ioT.push({ technology_id: techId, role, target, year: Number(yr), coefficient: v });
  const next = { ...wb, io } as Workbook;
  if (ioT.length) next[IO_T] = ioT;
  else delete next[IO_T];
  return next;
}
