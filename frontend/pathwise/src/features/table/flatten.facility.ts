// Flatten a facility / value-chain group into editable rows — one per machine leaf
// in its subtree, located by its sub-group path. Columns bind to the SAME caps.ts
// bridges the machine editor uses (so the static-scalar vs wide `*_t__` split never
// corrupts): machine economics, the distance/lifecycle attrs, and the technology
// costs (capex/opex/renewal) which are temporal.

import type { Row, Workbook } from "../../types";
import { parseNodes } from "../../lib/groupGraph";
import { instAttr, modelCurrency, setInstAttr, setTechCost, techCost } from "../../lib/caps";
import type { CellVal, FlatColumn, FlatResult, FlatRow } from "./flatten";

const s = (v: unknown): string => (v == null ? "" : String(v));
const setSheet = (wb: Workbook, sheet: string, rows: Row[]): Workbook => ({ ...wb, [sheet]: rows });
const isTechGroup = (id: string, level: string): boolean => id.endsWith("/_technology") || level.toLowerCase() === "technology";
const techIdOf = (wb: Workbook, machineId: string): string =>
  s((wb.machines ?? []).find((r) => s(r.machine_id) === machineId)?.baseline_technology);

// A plain `machines`-sheet column.
function machineCol(key: string, label: string, kind: FlatColumn["kind"]): FlatColumn {
  return {
    key,
    label,
    kind,
    get: (wb, id) => {
      const v = (wb.machines ?? []).find((r) => s(r.machine_id) === id)?.[key];
      return v == null || v === "" ? null : kind === "number" ? Number(v) : String(v);
    },
    set: (wb, id, v: CellVal) => {
      const scalar = v == null || typeof v === "object" ? "" : v;
      return setSheet(wb, "machines", (wb.machines ?? []).map((r) => (s(r.machine_id) === id ? { ...r, [key]: scalar } : r)));
    },
  };
}

// A temporal machine attribute (static column OR wide `*_t__` sheet) via instAttr.
function machineTemporalCol(key: string, label: string, tSheet: string, unit: string, perYear: boolean): FlatColumn {
  return {
    key,
    label,
    kind: "temporal",
    unit,
    perYear,
    get: (wb, id) => instAttr(wb, "machines", "machine_id", id, key, tSheet),
    set: (wb, id, v: CellVal) =>
      setInstAttr(wb, "machines", "machine_id", id, key, tSheet, v as number | Record<string, number> | null),
  };
}

// A static technology column (resolved from the machine's baseline technology).
function techCol(key: string, label: string, kind: FlatColumn["kind"]): FlatColumn {
  return {
    key,
    label,
    kind,
    get: (wb, id) => {
      const v = (wb.technologies ?? []).find((r) => s(r.technology_id) === techIdOf(wb, id))?.[key];
      return v == null || v === "" ? null : kind === "number" ? Number(v) : String(v);
    },
    set: (wb, id, v: CellVal) => {
      const tid = techIdOf(wb, id);
      const scalar = v == null || typeof v === "object" ? "" : v;
      return setSheet(wb, "technologies", (wb.technologies ?? []).map((r) => (s(r.technology_id) === tid ? { ...r, [key]: scalar } : r)));
    },
  };
}

// A temporal technology cost (capex / opex / renewal) via techCost.
function techCostCol(key: string, label: string, unit: string, perYear: boolean): FlatColumn {
  const tSheet = `technologies_t__${key}`;
  return {
    key,
    label,
    kind: "temporal",
    unit,
    perYear,
    get: (wb, id) => techCost(wb, techIdOf(wb, id), key, tSheet),
    set: (wb, id, v: CellVal) => setTechCost(wb, techIdOf(wb, id), key, tSheet, v as number | Record<string, number> | null),
  };
}

export function flattenFacilityGroup(wb: Workbook, groupId: string): FlatResult {
  const nodes = parseNodes(wb);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const childrenOf = new Map<string | null, typeof nodes>();
  for (const n of nodes) {
    const arr = childrenOf.get(n.parentId) ?? [];
    arr.push(n);
    childrenOf.set(n.parentId, arr);
  }
  // Machine leaves anywhere under groupId.
  const leaves: typeof nodes = [];
  const walk = (id: string) => {
    for (const c of childrenOf.get(id) ?? []) {
      if (c.kind === "machine") leaves.push(c);
      else walk(c.id);
    }
  };
  walk(groupId);

  const pathOf = (leaf: (typeof nodes)[number]): string[] => {
    const out: string[] = [];
    let cur = leaf.parentId;
    while (cur && cur !== groupId) {
      const g = byId.get(cur);
      if (!g) break;
      if (!isTechGroup(g.id, g.level)) out.unshift(g.label);
      cur = g.parentId;
    }
    return out;
  };

  const rows: FlatRow[] = leaves.map((m) => ({ id: m.id, path: pathOf(m), name: m.label, type: "Technology" }));
  const cur = modelCurrency(wb);
  const columns: FlatColumn[] = [
    machineCol("capacity", "Capacity", "number"),
    machineCol("owner", "Owner", "text"),
    machineCol("introduced_year", "Build year", "number"),
    machineCol("decommission_year", "Close year", "number"),
    machineCol("max_renewals", "Max renewals", "number"),
    machineTemporalCol("max_capacity_factor", "Max cap. factor", "processes_t__max_capacity_factor", "×cap", false),
    techCol("lifespan", "Lifespan (yr)", "number"),
    techCostCol("capex", "Capex", cur, false),
    techCostCol("opex", "Opex", cur, true),
    techCostCol("renewal", "Renewal", cur, false),
  ];
  return { rows, columns, title: byId.get(groupId)?.label ?? "Facility" };
}
