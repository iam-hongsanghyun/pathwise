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

/** An empty model — the app starts here (no preset). Core sheets exist so the
 *  tree renders editable groups; real models are loaded from the example library
 *  (sector workbooks under /examples) or by uploading an .xlsx. */
export function emptyWorkbook(): Workbook {
  return {
    periods: [],
    commodities: [],
    technologies: [],
    processes: [],
    io: [],
    impacts: [],
    markets: [],
    storage: [],
    demand: [],
  };
}

export interface ExampleModel {
  id: string;
  label: string;
  file: string;
  description?: string;
}

/** List the bundled example workbooks (sector models) from the library index. */
export async function listExamples(): Promise<ExampleModel[]> {
  const res = await fetch("/examples/index.json");
  if (!res.ok) return [];
  return (await res.json()) as ExampleModel[];
}

/** Fetch + parse a bundled example workbook (client-side, like an upload). */
export async function loadExample(file: string): Promise<Workbook> {
  const res = await fetch(`/examples/${file}`);
  if (!res.ok) throw new Error(`could not load example ${file}`);
  return parseWorkbook(await res.arrayBuffer());
}
