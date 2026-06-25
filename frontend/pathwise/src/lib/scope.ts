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

//: Every sheet whose rows carry a plain ``impact_id`` column. Scanning them all
//: means a user-defined impact surfaces no matter where it was first introduced
//: — a declaration, a price, a cap, a cradle factor, a per-process factor, or
//: freight emissions. "Impact" is a general, user-extensible term: the model,
//: not a prefilled list, is the single source of truth.
const IMPACT_ID_SHEETS = [
  "impacts", // canonical declaration (impact_id, unit)
  "impact_prices",
  "impacts_t__price",
  "tech_impacts",
  "process_impacts",
  "process_impacts_t",
  "commodity_impacts",
  "commodity_impacts_t",
  "link_impacts",
  "edge_impacts",
  "impact_caps",
  "impact_caps_t__limit",
] as const;

/** The unique impacts present anywhere in the model — raw elementary flows AND
 *  characterised LCIA categories (GWP, acidification, …). Driven entirely by the
 *  model's own sheets so any user-created impact appears; never a prefilled set.
 *  The canonical ``impacts`` declaration leads (preserving its authored order);
 *  impacts seen only in other sheets are appended. */
export function impactIds(wb: Workbook): string[] {
  const out = new Set<string>();
  for (const sheet of IMPACT_ID_SHEETS) {
    for (const r of wb[sheet] ?? []) {
      const id = s(r.impact_id);
      if (id) out.add(id);
    }
  }
  // An impact also attaches to a technology's recipe as a ``role=impact`` row…
  for (const r of wb.io ?? []) if (s(r.role) === "impact") out.add(s(r.target));
  for (const r of wb.io_t ?? []) if (s(r.role) === "impact") out.add(s(r.target));
  // …and characterisation references both a raw flow and its derived category.
  for (const r of wb.characterisation ?? []) {
    out.add(s(r.flow_impact_id));
    out.add(s(r.category_id));
  }
  return [...out].filter(Boolean);
}
