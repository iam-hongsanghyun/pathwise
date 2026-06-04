// Client-side workbook I/O — the frontend owns all data ingestion and export.

import * as XLSX from "xlsx";
import type { RunResult, Workbook } from "./types";

/** Parse an .xlsx ArrayBuffer into the {sheet: rows[]} model. */
export function parseWorkbook(buffer: ArrayBuffer): Workbook {
  const wb = XLSX.read(buffer, { type: "array" });
  const model: Workbook = {};
  for (const name of wb.SheetNames) {
    model[name] = XLSX.utils.sheet_to_json(wb.Sheets[name], { defval: null }) as Workbook[string];
  }
  return model;
}

export async function parseWorkbookFile(file: File): Promise<Workbook> {
  return parseWorkbook(await file.arrayBuffer());
}

/** Download the current workbook as .xlsx (one sheet per table). */
export function downloadWorkbook(model: Workbook, filename = "pathwise_model.xlsx"): void {
  const wb = XLSX.utils.book_new();
  for (const [sheet, rows] of Object.entries(model)) {
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), sheet.slice(0, 31));
  }
  XLSX.writeFile(wb, filename);
}

/** Download a run result as .xlsx. */
export function downloadResult(result: RunResult, filename = "pathwise_result.xlsx"): void {
  const wb = XLSX.utils.book_new();
  const add = (name: string, rows: unknown[]) => {
    if (rows.length) XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), name.slice(0, 31));
  };
  add("Technology", result.outputs.technology);
  add("Throughput", result.outputs.throughput);
  add("Transitions", result.outputs.transitions);
  add("Measures", result.outputs.measures);
  add("Flows", result.outputs.flows);
  add("Impacts", result.summary.impacts);
  add("Run", [{ status: result.status, objective: result.objective }]);
  XLSX.writeFile(wb, filename);
}

/** A small starter model (steel: iron-making feeds steel-making). */
export function exampleWorkbook(): Workbook {
  return {
    periods: [
      { year: 2025, duration_years: 1 },
      { year: 2030, duration_years: 1 },
    ],
    commodities: [
      { commodity_id: "coal", kind: "energy", unit: "MWh", price: 30 },
      { commodity_id: "elec", kind: "energy", unit: "MWh", price: 80 },
      { commodity_id: "ore", kind: "material", unit: "t", price: 100 },
      { commodity_id: "iron", kind: "material", unit: "t" },
      { commodity_id: "steel", kind: "product", unit: "t" },
    ],
    impacts: [{ impact_id: "CO2", unit: "tCO2e" }],
    technologies: [
      { technology_id: "BF", lifespan: 25, actions: "replace,renew,continue", capex: 200, opex: 10 },
      { technology_id: "EAF", lifespan: 20, actions: "replace,renew,continue", capex: 150, opex: 12 },
    ],
    processes: [
      { process_id: "F1", company: "Acme", baseline_technology: "BF", capacity: 1000, fixed_opex: 5000, failure_rate: 0.03 },
      { process_id: "F2", company: "Acme", baseline_technology: "EAF", capacity: 1000, fixed_opex: 4000, failure_rate: 0.02 },
    ],
    process_inputs: [
      { technology_id: "BF", commodity_id: "coal", intensity: 4 },
      { technology_id: "BF", commodity_id: "ore", intensity: 1.6 },
      { technology_id: "EAF", commodity_id: "iron", intensity: 1.1 },
      { technology_id: "EAF", commodity_id: "elec", intensity: 0.6 },
    ],
    process_outputs: [
      { technology_id: "BF", commodity_id: "iron", yield: 1, is_product: false },
      { technology_id: "EAF", commodity_id: "steel", yield: 1, is_product: true },
    ],
    commodity_impacts: [
      { commodity_id: "coal", impact_id: "CO2", factor: 0.34 },
      { commodity_id: "elec", impact_id: "CO2", factor: 0.05 },
    ],
    tech_impacts: [{ technology_id: "BF", impact_id: "CO2", factor: 1.2 }],
    edges: [{ from_process: "F1", to_process: "F2", commodity_id: "iron" }],
    measures: [
      { measure_id: "BF_eff", type: "energy_efficiency", applies_to: "F1", target: "coal", lifetime: 15 },
    ],
    measure_blocks: [
      { measure_id: "BF_eff", block: 0, reduction: 0.08, capex: 400 },
      { measure_id: "BF_eff", block: 1, reduction: 0.06, capex: 900 },
    ],
    transitions: [
      { from_technology: "BF", to_technology: "EAF", action: "replace", capex_per_capacity: 180, compatible: true },
    ],
    demand: [
      { company: "Acme", commodity_id: "steel", year: 2025, amount: 800 },
      { company: "Acme", commodity_id: "steel", year: 2030, amount: 900 },
    ],
    impact_prices: [
      { impact_id: "CO2", year: 2025, price: 50 },
      { impact_id: "CO2", year: 2030, price: 120 },
    ],
    impact_caps: [{ company: "all", impact_id: "CO2", year: 2030, limit: 4000 }],
    storage: [
      {
        storage_id: "coal_yard",
        commodity_id: "coal",
        company: "all",
        max_capacity: 5000,
        capex_per_capacity: 2,
        fixed_opex_per_capacity: 0.1,
        charge_efficiency: 1,
        discharge_efficiency: 1,
      },
    ],
    investment_budget: [{ company: "Acme", year: 2030, limit: 500000 }],
    min_production: [{ company: "Acme", commodity_id: "steel", year: 2030, amount: 700 }],
    company_config: [{ company: "Acme", objective: "cost" }],
    markets: [
      { market_id: "KEPCO", target: "elec", target_kind: "commodity", price: 90, tag: "grid" },
      { market_id: "PPA", target: "elec", target_kind: "commodity", price: 70, max_buy: 400, tag: "RE100" },
      { market_id: "ETS", target: "CO2", target_kind: "impact", company: "all", price: 60, allocation: 2000 },
    ],
  };
}
