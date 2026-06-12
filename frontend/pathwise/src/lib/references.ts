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

/** Options for a (sheet, column) cell, or ``null`` for a free-text field. */
export function optionsFor(wb: Workbook, sheet: string, col: string, row: Row): string[] | null {
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

  if (col === "company") return companies(wb);
  if (col === "commodity_id") return distinct(wb, "commodities", "commodity_id");
  if (col === "impact_id") return distinct(wb, "impacts", "impact_id");
  if (["technology_id", "baseline_technology", "from_technology", "to_technology"].includes(col))
    return distinct(wb, "technologies", "technology_id");
  if (["from_process", "to_process", "applies_to"].includes(col))
    return distinct(wb, "processes", "process_id");
  return null;
}
