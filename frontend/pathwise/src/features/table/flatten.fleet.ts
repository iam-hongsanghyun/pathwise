// Flatten a fleet-registry group into editable rows — one per fleet in its subtree,
// located by its sub-group path. All fleet fields are plain `fleet`-sheet columns.

import type { Row, Workbook } from "../../types";
import { fleetId, parseFleetGroups } from "../fleet/fleetGraph";
import type { CellVal, FlatColumn, FlatResult, FlatRow } from "./flatten";

const s = (v: unknown): string => (v == null ? "" : String(v));
const setSheet = (wb: Workbook, sheet: string, rows: Row[]): Workbook => ({ ...wb, [sheet]: rows });

// A plain `fleet`-sheet column (read/write the matching fleet row by id).
function fleetCol(key: string, label: string, kind: FlatColumn["kind"], options?: string[]): FlatColumn {
  return {
    key,
    label,
    kind,
    options,
    get: (wb, id) => {
      const r = (wb.fleet ?? []).find((f) => fleetId(f) === id);
      const v = r?.[key];
      if (v == null || v === "") return null;
      return kind === "number" ? Number(v) : String(v);
    },
    set: (wb, id, v: CellVal) => {
      const scalar = v == null || typeof v === "object" ? "" : v; // fleet fields are static
      return setSheet(wb, "fleet", (wb.fleet ?? []).map((f) => (fleetId(f) === id ? { ...f, [key]: scalar } : f)));
    },
  };
}

const FLEET_COLUMNS: FlatColumn[] = [
  fleetCol("fuel", "Fuel", "text"),
  fleetCol("cargo", "Cargo", "text"),
  fleetCol("count", "Units", "number"),
  fleetCol("ship_size", "Cargo / voyage", "number"),
  fleetCol("speed", "Speed", "number"),
  fleetCol("turnaround_days", "Turnaround (d)", "number"),
  fleetCol("operating_days", "Op. days/yr", "number"),
  fleetCol("efficiency", "Efficiency", "number"),
  fleetCol("capacity", "Flat capacity", "number"),
  fleetCol("opex", "O&M / unit / yr", "number"),
  fleetCol("capex", "Capex / unit", "number"),
  fleetCol("max_build", "Max build", "number"),
  fleetCol("build_year", "Build year", "number"),
  fleetCol("close_year", "Close year", "number"),
  fleetCol("lifespan", "Lifespan (yr)", "number"),
];

/** Labels of the sub-groups between `leaf` and `root` (top→down, both excluded). */
function pathUnder(groups: ReturnType<typeof parseFleetGroups>, leaf: string | null, root: string): string[] {
  const byId = new Map(groups.map((g) => [g.id, g]));
  const out: string[] = [];
  let cur = leaf;
  while (cur && cur !== root) {
    const g = byId.get(cur);
    if (!g) break;
    out.unshift(g.label);
    cur = g.parentId;
  }
  return out;
}

export function flattenFleetGroup(wb: Workbook, groupId: string): FlatResult {
  const groups = parseFleetGroups(wb);
  const byId = new Map(groups.map((g) => [g.id, g]));
  // Every group in the triggered group's subtree (incl. itself).
  const inSubtree = (gid: string): boolean => {
    let cur: string | null = gid;
    const seen = new Set<string>();
    while (cur && !seen.has(cur)) {
      if (cur === groupId) return true;
      seen.add(cur);
      cur = byId.get(cur)?.parentId ?? null;
    }
    return false;
  };
  const rows: FlatRow[] = (wb.fleet ?? [])
    .filter((f) => inSubtree(s(f.group)))
    .map((f) => ({
      id: fleetId(f),
      path: pathUnder(groups, s(f.group) || null, groupId),
      name: s(f.label) || fleetId(f),
      type: s(f.mode) || "—",
    }));
  return { rows, columns: FLEET_COLUMNS, title: byId.get(groupId)?.label ?? "Fleets" };
}
