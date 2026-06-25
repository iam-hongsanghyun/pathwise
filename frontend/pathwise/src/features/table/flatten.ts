// Group → flat editable rows. A "See in a table" action turns a triggered group
// node into a list of its leaf components (each row located by its sub-group PATH +
// name + type) plus the editable columns for those components. Pure + library-
// agnostic: every column's get/set delegates to the workbook (caps.ts bridges or
// setSheet), so the table never writes raw cells the wrong way.

import type { Workbook } from "../../types";

/** A cell value: a scalar, a {year: value} temporal map, or empty. */
export type CellVal = number | string | Record<string, number> | null;

export interface FlatColumn {
  key: string;
  label: string;
  /** fieldMeta key for the header tooltip/unit (optional). */
  metaKey?: string;
  kind: "text" | "number" | "enum" | "temporal" | "streams";
  /** enum options (kind="enum"). */
  options?: string[];
  unit?: string;
  /** temporal: append "/yr" to the unit (flows) vs leave as-is (rates/prices). */
  perYear?: boolean;
  get: (wb: Workbook, rowId: string) => CellVal;
  set: (wb: Workbook, rowId: string, v: CellVal) => Workbook;
  // ── kind="streams": a recipe side (inputs/outputs). The cell lists each stream
  // name; clicking one edits its coefficient (static or temporal). get() returns the
  // joined names so search/sort still work. ──
  streams?: (wb: Workbook, rowId: string) => string[];
  streamGet?: (wb: Workbook, rowId: string, target: string) => CellVal;
  streamSet?: (wb: Workbook, rowId: string, target: string, v: CellVal) => Workbook;
}

export interface FlatRow {
  /** Stable id of the component (used as the get/set key). */
  id: string;
  /** Sub-group labels from the triggered group down to the component (excl. both). */
  path: string[];
  name: string;
  /** Technology / Stream / Lever — or the fleet's mode. */
  type: string;
}

export interface FlatResult {
  rows: FlatRow[];
  columns: FlatColumn[];
  /** Heading shown on the table panel (the triggered group's label). */
  title: string;
}

export type Flattener = (wb: Workbook, groupId: string) => FlatResult;
