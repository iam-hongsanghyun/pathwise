// Scope options for targets / constraints. A constraint's `company` column is
// resolved by the backend's Process.in_scope: "all" = the whole system, else a
// node / company / group id that the facilities match against. We derive the
// selectable scopes from the node hierarchy (every group node) or, for a flat
// model with no hierarchy, the distinct process companies.

import type { Workbook } from "../types";
import { parseNodes } from "./groupGraph";

const s = (v: unknown): string => (v == null ? "" : String(v));

export interface ScopeOption {
  value: string;
  label: string;
}

/** "all" (system) plus every scope a target can be attached to. */
export function scopeOptions(wb: Workbook): ScopeOption[] {
  const out: ScopeOption[] = [{ value: "all", label: "System (whole model)" }];
  const groups = parseNodes(wb).filter((n) => n.kind === "group");
  if (groups.length > 0) {
    for (const n of groups) {
      out.push({ value: n.id, label: n.level ? `${n.label} · ${n.level}` : n.label });
    }
  } else {
    const seen = new Set<string>();
    for (const r of wb.processes ?? []) {
      const c = s(r.company);
      if (c && !seen.has(c)) {
        seen.add(c);
        out.push({ value: c, label: c });
      }
    }
  }
  return out;
}

/** The product streams demand / min-production can target. */
export function productIds(wb: Workbook): string[] {
  const out = new Set<string>();
  for (const r of wb.io ?? []) if (s(r.role) === "output" && r.is_product) out.add(s(r.target));
  for (const c of wb.commodities ?? []) if (s(c.kind) === "product") out.add(s(c.commodity_id));
  return [...out].filter(Boolean);
}

/** The impacts that caps / objectives can target — raw elementary flows AND the
 *  characterised LCIA categories (GWP, acidification, …) derived from them. */
export function impactIds(wb: Workbook): string[] {
  const out = new Set<string>();
  for (const r of wb.impacts ?? []) out.add(s(r.impact_id));
  for (const r of wb.io ?? []) if (s(r.role) === "impact") out.add(s(r.target));
  for (const r of wb.characterisation ?? []) out.add(s(r.category_id));
  return [...out].filter(Boolean);
}
