// Client-side workbook I/O — the frontend owns all data ingestion and export.
// The backend never touches files; it only exchanges the JSON model and result.

import * as XLSX from "xlsx";
import type { RunResult, Workbook } from "./types";

/** Parse an .xlsx ArrayBuffer into the {sheet: rows[]} model. */
export function parseWorkbook(buffer: ArrayBuffer): Workbook {
  const wb = XLSX.read(buffer, { type: "array" });
  const model: Workbook = {};
  for (const name of wb.SheetNames) {
    const rows = XLSX.utils.sheet_to_json(wb.Sheets[name], { defval: null });
    model[name] = rows as Record<string, unknown>[];
  }
  return model;
}

/** Read a File (from an <input type=file>) into the model. */
export async function parseWorkbookFile(file: File): Promise<Workbook> {
  return parseWorkbook(await file.arrayBuffer());
}

/** Fetch a bundled sample workbook from the frontend's own assets. */
export async function loadSample(url: string): Promise<Workbook> {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`could not load sample: ${resp.status}`);
  return parseWorkbook(await resp.arrayBuffer());
}

/** Build and download an .xlsx from the entire run result (client-side). */
export function downloadResultXlsx(result: RunResult, filename = "pathwise_result.xlsx"): void {
  const wb = XLSX.utils.book_new();
  const add = (sheet: string, rows: unknown[]) => {
    if (rows.length > 0) {
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), sheet.slice(0, 31));
    }
  };
  add("Assignments", result.outputs.chosen_technology);
  add("Carrier_Energy", result.outputs.carrier_energy);
  add("Transitions", result.outputs.transitions);
  add("New_Builds", result.outputs.new_builds);
  add("Measures", result.outputs.measures);
  add("Slack", result.outputs.slack);
  add("Period_Summary", result.summary.periods);
  add("Run_Info", [
    { status: result.status, objective: result.objective, termination: result.termination },
  ]);
  XLSX.writeFile(wb, filename);
}
