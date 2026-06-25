// Flatten a facility / network group into editable rows — one per asset leaf
// in its subtree, located by its sub-group path. Columns bind to the SAME caps.ts
// bridges the asset editor uses (so the static-scalar vs wide `*_t__` split never
// corrupts): asset economics, the distance/lifecycle attrs, and the technology
// costs (capex/opex/renewal) which are temporal.

import type { Row, Workbook } from "../../types";
import { parseNodes } from "../../lib/groupGraph";
import { instAttr, ioCoeff, modelCurrency, setInstAttr, setIoCoeff, setTechCost, techCost } from "../../lib/caps";
import type { CellVal, FlatColumn, FlatResult, FlatRow } from "./flatten";

const s = (v: unknown): string => (v == null ? "" : String(v));
const setSheet = (wb: Workbook, sheet: string, rows: Row[]): Workbook => ({ ...wb, [sheet]: rows });
const isTechGroup = (id: string, level: string): boolean => id.endsWith("/_technology") || level.toLowerCase() === "technology";
const techIdOf = (wb: Workbook, machineId: string): string =>
  s((wb.assets ?? []).find((r) => s(r.asset_id) === machineId)?.baseline_technology);

// A plain `assets`-sheet column.
function machineCol(key: string, label: string, kind: FlatColumn["kind"]): FlatColumn {
  return {
    key,
    label,
    kind,
    get: (wb, id) => {
      const v = (wb.assets ?? []).find((r) => s(r.asset_id) === id)?.[key];
      return v == null || v === "" ? null : kind === "number" ? Number(v) : String(v);
    },
    set: (wb, id, v: CellVal) => {
      const scalar = v == null || typeof v === "object" ? "" : v;
      return setSheet(wb, "assets", (wb.assets ?? []).map((r) => (s(r.asset_id) === id ? { ...r, [key]: scalar } : r)));
    },
  };
}

// A temporal asset attribute (static column OR wide `*_t__` sheet) via instAttr.
function machineTemporalCol(key: string, label: string, tSheet: string, unit: string, perYear: boolean): FlatColumn {
  return {
    key,
    label,
    kind: "temporal",
    unit,
    perYear,
    get: (wb, id) => instAttr(wb, "assets", "asset_id", id, key, tSheet),
    set: (wb, id, v: CellVal) =>
      setInstAttr(wb, "assets", "asset_id", id, key, tSheet, v as number | Record<string, number> | null),
  };
}

// A static technology column (resolved from the asset's baseline technology).
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

// A temporal technology attribute (e.g. min capacity factor) via instAttr.
function techTemporalCol(key: string, label: string, tSheet: string, unit: string, perYear: boolean): FlatColumn {
  return {
    key,
    label,
    kind: "temporal",
    unit,
    perYear,
    get: (wb, id) => instAttr(wb, "technologies", "technology_id", techIdOf(wb, id), key, tSheet),
    set: (wb, id, v: CellVal) =>
      setInstAttr(wb, "technologies", "technology_id", techIdOf(wb, id), key, tSheet, v as number | Record<string, number> | null),
  };
}

// The distinct stream targets of a technology's recipe on one side (input/output).
function ioTargets(wb: Workbook, techId: string, role: string): string[] {
  const seen = new Set<string>();
  for (const sheet of ["io", "io_t"]) {
    for (const r of wb[sheet] ?? []) {
      if (s(r.technology_id) === techId && s(r.role) === role && s(r.target)) seen.add(s(r.target));
    }
  }
  return [...seen];
}

// A recipe side: lists each stream; clicking one edits its coefficient (temporal-aware).
function streamCol(role: "input" | "output", label: string): FlatColumn {
  return {
    key: role,
    label,
    kind: "streams",
    streams: (wb, id) => ioTargets(wb, techIdOf(wb, id), role),
    streamGet: (wb, id, target) => ioCoeff(wb, techIdOf(wb, id), role, target),
    streamSet: (wb, id, target, v) =>
      setIoCoeff(wb, techIdOf(wb, id), role, target, v as number | Record<string, number> | null),
    get: (wb, id) => ioTargets(wb, techIdOf(wb, id), role).join(", "),
    set: (wb) => wb,
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
  // Asset leaves anywhere under groupId.
  const leaves: typeof nodes = [];
  const walk = (id: string) => {
    for (const c of childrenOf.get(id) ?? []) {
      if (c.kind === "asset") leaves.push(c);
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
    streamCol("input", "Inputs"),
    streamCol("output", "Outputs"),
    techCol("lifespan", "Lifespan (yr)", "number"),
    techCol("introduction_year", "Tech intro yr", "number"),
    techCol("phase_out_year", "Tech phase-out", "number"),
    techTemporalCol("min_capacity_factor", "Min cap. factor", "technologies_t__min_capacity_factor", "×cap", false),
    techCostCol("capex", "Capex", cur, false),
    techCostCol("opex", "Opex", cur, true),
    techCostCol("renewal", "Renewal", cur, false),
  ];
  return { rows, columns, title: byId.get(groupId)?.label ?? "Facility" };
}
