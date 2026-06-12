// Resolve which workbook columns are references / enums / booleans, and the
// option values for each — so the inspector can render dropdowns that link
// entities together instead of free-text ids.

import type { Row, Workbook } from "../types";

const ENUMS: Record<string, string[]> = {
  "commodities.kind": ["energy", "material", "indirect", "product", "byproduct"],
  "markets.target_kind": ["commodity", "impact"],
  "measures.type": ["energy_efficiency", "emission_reduction", "environmental"],
  "transitions.action": ["replace", "renew", "continue"],
  "company_config.objective": ["cost", "profit"],
};

const BOOLEAN_COLS = new Set(["sellable", "purchasable", "replaceable", "is_product", "compatible"]);

function distinct(wb: Workbook, sheet: string, col: string): string[] {
  const seen = new Set<string>();
  for (const r of wb[sheet] ?? []) {
    const v = r[col];
    if (v != null && v !== "") seen.add(String(v));
  }
  return [...seen].sort();
}

function companies(wb: Workbook): string[] {
  return ["all", ...distinct(wb, "processes", "company").filter((c) => c !== "all")];
}

/** Each entity sheet's own id column — NOT a reference when edited on that
 *  sheet itself (it's the unique id being defined there). */
const ID_COL: Record<string, string> = {
  processes: "process_id",
  commodities: "commodity_id",
  markets: "market_id",
  storage: "storage_id",
  technologies: "technology_id",
  measures: "measure_id",
  impacts: "impact_id",
};

/** Columns holding a user-invented NAME (not a component id): existing names
 *  are offered for reuse, but typing a new one is always valid. */
export function isFreeName(sheet: string, col: string): boolean {
  return (sheet === "maccs" || sheet === "macc_links") && col === "macc";
}

/** Options for a (sheet, column) cell, or ``null`` for a free-text field. */
export function optionsFor(wb: Workbook, sheet: string, col: string, row: Row): string[] | null {
  if (ID_COL[sheet] === col) return null; // defining the id, not referencing one
  const key = `${sheet}.${col}`;
  if (key in ENUMS) return ENUMS[key];
  if (BOOLEAN_COLS.has(col)) return ["true", "false"];

  // markets.target points at a commodity or an impact depending on target_kind.
  if (sheet === "markets" && col === "target") {
    return String(row.target_kind ?? "commodity") === "impact"
      ? distinct(wb, "impacts", "impact_id")
      : distinct(wb, "commodities", "commodity_id");
  }
  // measures.target points at a commodity (efficiency) or impact (others).
  if (sheet === "measures" && col === "target") {
    return String(row.type ?? "") === "energy_efficiency"
      ? distinct(wb, "commodities", "commodity_id")
      : distinct(wb, "impacts", "impact_id");
  }

  // MACC names: offer existing ones, but new names are fine (free-name col).
  if (isFreeName(sheet, col)) return distinct(wb, "maccs", "macc");
  if ((sheet === "measure_blocks" || sheet === "maccs") && col === "measure_id")
    return distinct(wb, "measures", "measure_id");

  if (col === "company") return companies(wb);
  if (col === "commodity_id") return distinct(wb, "commodities", "commodity_id");
  if (col === "impact_id") return distinct(wb, "impacts", "impact_id");
  if (
    ["technology_id", "baseline_technology", "from_technology", "to_technology", "technology"].includes(col)
  )
    return distinct(wb, "technologies", "technology_id");
  if (["from_process", "to_process", "applies_to", "facility"].includes(col))
    return distinct(wb, "processes", "process_id");
  return null;
}

/** Where a reference column points — the sheet(s) a missing component could
 *  be created on. Empty array = not a creatable component (enums, booleans,
 *  free names like MACC labels). */
export interface RefTarget {
  sheet: string;
  idCol: string;
  label: string;
}

const COMMODITY: RefTarget = { sheet: "commodities", idCol: "commodity_id", label: "stream" };
const IMPACT: RefTarget = { sheet: "impacts", idCol: "impact_id", label: "impact" };
const TECH: RefTarget = { sheet: "technologies", idCol: "technology_id", label: "technology" };
const FACILITY: RefTarget = { sheet: "processes", idCol: "process_id", label: "facility" };
const MEASURE: RefTarget = { sheet: "measures", idCol: "measure_id", label: "measure" };

export function refTargets(sheet: string, col: string, row: Row): RefTarget[] {
  if (ID_COL[sheet] === col) return [];
  if (`${sheet}.${col}` in ENUMS || BOOLEAN_COLS.has(col)) return [];
  if (isFreeName(sheet, col)) return []; // a name, not a component
  if ((sheet === "measure_blocks" || sheet === "maccs") && col === "measure_id") return [MEASURE];
  if (sheet === "markets" && col === "target")
    return String(row.target_kind ?? "commodity") === "impact" ? [IMPACT] : [COMMODITY];
  if (sheet === "measures" && col === "target")
    return String(row.type ?? "") === "energy_efficiency" ? [COMMODITY] : [IMPACT];
  if (col === "commodity_id") return [COMMODITY];
  if (col === "impact_id") return [IMPACT];
  if (
    ["technology_id", "baseline_technology", "from_technology", "to_technology", "technology"].includes(col)
  )
    return [TECH];
  if (["from_process", "to_process", "applies_to", "facility"].includes(col)) return [FACILITY];
  return [];
}

/** BROKEN references: a filled value that does not resolve to an existing
 *  component — shown red in editors and as a red DOT in the model tree. */
export function rowProblems(wb: Workbook, sheet: string, row: Row): string[] {
  const bad: string[] = [];
  for (const [col, v] of Object.entries(row)) {
    if (v == null || v === "" || typeof v === "boolean") continue;
    if (isFreeName(sheet, col)) continue; // new names are always valid
    const opts = optionsFor(wb, sheet, col, row);
    if (opts && !opts.includes(String(v))) bad.push(col);
  }
  return bad;
}

/** MISSING requirements: required columns left empty (any type, schema-driven)
 *  plus one-of rules — shown as a red BACKGROUND in the model tree.
 *  Distinct from rowProblems (broken links → red dot). */
export function rowMissing(sheet: string, row: Row, requiredCols?: string[]): string[] {
  const out: string[] = [];
  for (const col of requiredCols ?? []) {
    const v = row[col];
    if (v == null || v === "") out.push(col);
  }
  // A MACC deployment must name a facility OR a technology.
  if (
    sheet === "macc_links" &&
    (row.facility == null || row.facility === "") &&
    (row.technology == null || row.technology === "")
  )
    out.push("facility or technology");
  return out;
}

/** True when a measure reaches at least one facility: a direct facility /
 *  technology column, membership in a MACC that is deployed somewhere, or the
 *  legacy applies_to / set columns. Catalogue-only measures are fine — they
 *  are simply inert until deployed. */
export function measureDeployed(wb: Workbook, row: Row): boolean {
  if (row.facility || row.technology || row.applies_to) return true;
  const mid = String(row.measure_id ?? "");
  const myMaccs = new Set(
    (wb.maccs ?? [])
      .filter((r) => String(r.measure_id ?? "") === mid && r.macc)
      .map((r) => String(r.macc)),
  );
  if (
    (wb.macc_links ?? []).some(
      (l) => myMaccs.has(String(l.macc ?? "")) && (l.facility || l.technology),
    )
  )
    return true;
  // legacy named set
  const set = String(row.set ?? "");
  return (
    set !== "" && (wb.measure_links ?? []).some((l) => String(l.set ?? "") === set && l.applies_to)
  );
}

/** What to add first when a reference dropdown has no options yet. */
export function emptyHint(sheet: string, col: string): string {
  if (isFreeName(sheet, col)) return "type a name for a new MACC";
  if ((sheet === "measure_blocks" || sheet === "maccs") && col === "measure_id")
    return "add a measure first";
  if (col === "commodity_id") return "add a stream first";
  if (col === "impact_id") return "add an impact first";
  if (
    ["technology_id", "baseline_technology", "from_technology", "to_technology", "technology"].includes(col)
  )
    return "add a technology first";
  if (["from_process", "to_process", "applies_to", "facility"].includes(col))
    return "add a facility first";
  if (col === "company") return "set a company on a facility first";
  return "add the referenced component first";
}
