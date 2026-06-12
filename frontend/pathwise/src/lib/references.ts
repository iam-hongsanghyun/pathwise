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

  // measures / measure_links may target a FACILITY or a TECHNOLOGY (= every
  // facility running it as baseline).
  if ((sheet === "measures" || sheet === "measure_links") && col === "applies_to")
    return [
      ...distinct(wb, "processes", "process_id"),
      ...distinct(wb, "technologies", "technology_id"),
    ];
  // Linking picks an EXISTING named MACC set (define sets on measure rows).
  if (sheet === "measure_links" && col === "set") return distinct(wb, "measures", "set");
  if (sheet === "measure_blocks" && col === "measure_id")
    return distinct(wb, "measures", "measure_id");

  if (col === "company") return companies(wb);
  if (col === "commodity_id") return distinct(wb, "commodities", "commodity_id");
  if (col === "impact_id") return distinct(wb, "impacts", "impact_id");
  if (["technology_id", "baseline_technology", "from_technology", "to_technology"].includes(col))
    return distinct(wb, "technologies", "technology_id");
  if (["from_process", "to_process", "applies_to"].includes(col))
    return distinct(wb, "processes", "process_id");
  return null;
}

/** Where a reference column points — the sheet(s) a missing component could
 *  be created on. Empty array = not a creatable component (enums, booleans,
 *  free names like MACC set labels). */
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
  if ((sheet === "measures" || sheet === "measure_links") && col === "applies_to")
    return [FACILITY, TECH];
  if (sheet === "measure_links" && col === "set") return []; // named on measure rows
  if (sheet === "measure_blocks" && col === "measure_id") return [MEASURE];
  if (sheet === "markets" && col === "target")
    return String(row.target_kind ?? "commodity") === "impact" ? [IMPACT] : [COMMODITY];
  if (sheet === "measures" && col === "target")
    return String(row.type ?? "") === "energy_efficiency" ? [COMMODITY] : [IMPACT];
  if (col === "commodity_id") return [COMMODITY];
  if (col === "impact_id") return [IMPACT];
  if (["technology_id", "baseline_technology", "from_technology", "to_technology"].includes(col))
    return [TECH];
  if (["from_process", "to_process", "applies_to"].includes(col)) return [FACILITY];
  return [];
}

/** Reference columns of one row whose value does not resolve to an existing
 *  component — shown red in editors and as a red dot in the model tree. */
export function rowProblems(wb: Workbook, sheet: string, row: Row): string[] {
  const bad: string[] = [];
  for (const [col, v] of Object.entries(row)) {
    if (v == null || v === "" || typeof v === "boolean") continue;
    const opts = optionsFor(wb, sheet, col, row);
    if (opts && !opts.includes(String(v))) bad.push(col);
  }
  return bad;
}

/** What to add first when a reference dropdown has no options yet. */
export function emptyHint(sheet: string, col: string): string {
  if ((sheet === "measures" || sheet === "measure_links") && col === "applies_to")
    return "add a facility or technology first";
  if (sheet === "measure_links" && col === "set")
    return "name a MACC set on a measure row first";
  if (sheet === "measure_blocks" && col === "measure_id") return "add a measure first";
  if (col === "commodity_id") return "add a stream first";
  if (col === "impact_id") return "add an impact first";
  if (["technology_id", "baseline_technology", "from_technology", "to_technology"].includes(col))
    return "add a technology first";
  if (["from_process", "to_process", "applies_to"].includes(col)) return "add a facility first";
  if (col === "company") return "set a company on a facility first";
  return "add the referenced component first";
}
