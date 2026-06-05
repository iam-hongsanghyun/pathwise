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

/** Steel decarbonisation example: iron-making (BF coal route) feeds steel-making
 *  (EAF). Over 2025→2050 a rising ETS price + falling H2 cost let the optimiser
 *  replace BF with H2-DRI or buy HBI/iron from a market and idle the iron plant. */
export function exampleWorkbook(): Workbook {
  const years = [2025, 2030, 2035, 2040, 2045, 2050];
  return {
    periods: years.map((year) => ({ year, duration_years: 5 })),
    commodities: [
      { commodity_id: "coal", kind: "energy", unit: "t", price: 40 },
      { commodity_id: "ore", kind: "material", unit: "t", price: 100 },
      { commodity_id: "elec", kind: "energy", unit: "MWh", price: 70 },
      { commodity_id: "h2", kind: "energy", unit: "t", price: 200 },
      { commodity_id: "iron", kind: "material", unit: "t" },
      { commodity_id: "steel", kind: "product", unit: "t" },
    ],
    impacts: [{ impact_id: "CO2", unit: "tCO2e" }],
    technologies: [
      { technology_id: "BF", lifespan: 40, actions: "continue,replace", opex: 20 },
      { technology_id: "H2DRI", lifespan: 30, actions: "continue,replace", opex: 25 },
      { technology_id: "EAF", lifespan: 30, actions: "continue", opex: 30 },
    ],
    processes: [
      { process_id: "IRON", company: "Steelco", baseline_technology: "BF", capacity: 1200, fixed_opex: 1000 },
      { process_id: "STEEL", company: "Steelco", baseline_technology: "EAF", capacity: 1200, fixed_opex: 1000 },
    ],
    io: [
      { technology_id: "BF", target: "coal", role: "input", coefficient: 5 },
      { technology_id: "BF", target: "ore", role: "input", coefficient: 1.5 },
      { technology_id: "BF", target: "iron", role: "output", coefficient: 1 },
      { technology_id: "BF", target: "CO2", role: "impact", coefficient: 1.8 },
      { technology_id: "H2DRI", target: "h2", role: "input", coefficient: 3 },
      { technology_id: "H2DRI", target: "ore", role: "input", coefficient: 1.4 },
      { technology_id: "H2DRI", target: "iron", role: "output", coefficient: 1 },
      { technology_id: "H2DRI", target: "CO2", role: "impact", coefficient: 0.1 },
      { technology_id: "EAF", target: "iron", role: "input", coefficient: 1.05 },
      { technology_id: "EAF", target: "elec", role: "input", coefficient: 0.6 },
      { technology_id: "EAF", target: "steel", role: "output", coefficient: 1, is_product: true },
    ],
    commodity_impacts: [
      { commodity_id: "coal", impact_id: "CO2", factor: 0.3 },
      { commodity_id: "elec", impact_id: "CO2", factor: 0.2 },
    ],
    edges: [{ from_process: "IRON", to_process: "STEEL", commodity_id: "iron" }],
    transitions: [
      { from_technology: "BF", to_technology: "H2DRI", action: "replace", capex_per_capacity: 300, compatible: true },
    ],
    markets: [
      { market_id: "HBI", target: "iron", target_kind: "commodity", price: 520, tag: "imported" },
      { market_id: "ETS", target: "CO2", target_kind: "impact", company: "all", price: 30 },
    ],
    commodities_t__price: [
      { year: 2025, h2: 200 },
      { year: 2050, h2: 60 },
    ],
    markets_t__price: [
      { year: 2025, ETS: 30 },
      { year: 2050, ETS: 260 },
    ],
    demand: years.map((year) => ({ company: "Steelco", commodity_id: "steel", year, amount: 1000 })),
    company_config: [{ company: "Steelco", objective: "cost" }],
    node_layout: [
      { id: "commodity:coal", x: 40, y: 40 },
      { id: "commodity:ore", x: 40, y: 150 },
      { id: "commodity:h2", x: 40, y: 260 },
      { id: "commodity:elec", x: 40, y: 470 },
      { id: "process:IRON", x: 280, y: 150 },
      { id: "commodity:iron", x: 520, y: 150 },
      { id: "process:STEEL", x: 760, y: 250 },
      { id: "commodity:steel", x: 1000, y: 250 },
      { id: "market:HBI", x: 520, y: 320 },
      { id: "market:ETS", x: 280, y: 380 },
    ],
  };
}
