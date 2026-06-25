// Client-side model validation — a FAST, PURE mirror of the most common, easy to
// get wrong model problems, surfaced live as the user builds (tree badges, the
// Model-health panel, a Run pre-flight gate) instead of only as a generic banner
// after a failed solve.
//
// It is deliberately a STRICT SUBSET of the authoritative server validation: it
// only flags things that are structurally certain from the workbook alone, so it
// can never contradict a model the server solves successfully. The following are
// NOT mirrored here (they need the full solve / scenario and stay server-side):
//   • LP/MILP infeasibility (capacity vs demand, blend share conflicts, lag/horizon)
//   • unbounded / numeric-scaling objectives, MIP-gap / time-limit terminations
//   • cross-period availability windows making demand unmeetable in a given year
//   • anything dependent on the run-time scenario (scope / mode / coupling)

import type { Row, Workbook } from "../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const num = (v: unknown): number => (v == null || v === "" ? NaN : Number(v));

export type Severity = "error" | "warning";

/** A workbook mutation expressed declaratively so the host applies it with the
 *  SAME setSheet helper the builders already use (zero validator → React coupling). */
export type FixDescriptor =
  | { kind: "patchRow"; sheet: string; rowIndex: number; patch: Row }
  | { kind: "removeRow"; sheet: string; rowIndex: number }
  | { kind: "appendRow"; sheet: string; row: Row }
  | { kind: "setFlowField"; flowId: string; patch: Row };

export interface IssueFix {
  label: string;
  descriptor: FixDescriptor;
  /** If set, the host prompts for a number and writes it into the descriptor's
   *  patch/row at `field` before applying (e.g. "set this market's price"). */
  promptFor?: { field: string; label: string; defaultValue?: number };
}

export interface Issue {
  /** Deterministic `${rule}:${scopeKey}` — stable React key + dedupe handle. */
  id: string;
  rule: string;
  severity: Severity;
  title: string;
  message: string;
  scope?: { nodeId?: string; flowId?: string; techId?: string };
  sheet?: string;
  rowIndex?: number;
  fix?: IssueFix;
}

export interface IssueIndex {
  byNode: Map<string, Issue[]>;
  errorCount: number;
  warnCount: number;
}

/** Group issues by their node scope and tally severities (cheap, for badges). */
export function indexIssues(issues: Issue[]): IssueIndex {
  const byNode = new Map<string, Issue[]>();
  let errorCount = 0;
  let warnCount = 0;
  for (const i of issues) {
    if (i.severity === "error") errorCount++;
    else warnCount++;
    const nid = i.scope?.nodeId;
    if (nid) (byNode.get(nid) ?? byNode.set(nid, []).get(nid)!).push(i);
  }
  return { byNode, errorCount, warnCount };
}

/** Roll a node's own issues up to all its ancestors, so a collapsed parent in the
 *  tree still shows the worst severity among its descendants. */
export function rollUpBadges(
  wb: Workbook,
  byNode: Map<string, Issue[]>,
): Map<string, { severity: Severity; count: number }> {
  const parent = new Map((wb.nodes ?? []).map((r) => [s(r.node_id), s(r.parent_id)]));
  const agg = new Map<string, { error: number; warning: number }>();
  const bump = (id: string, sev: Severity) => {
    const a = agg.get(id) ?? { error: 0, warning: 0 };
    a[sev] += 1;
    agg.set(id, a);
  };
  for (const [nid, issues] of byNode) {
    for (const issue of issues) {
      // walk self → ancestors (cycle-guarded)
      let cur: string | undefined = nid;
      const seen = new Set<string>();
      while (cur && !seen.has(cur)) {
        bump(cur, issue.severity);
        seen.add(cur);
        cur = parent.get(cur) || undefined;
      }
    }
  }
  const out = new Map<string, { severity: Severity; count: number }>();
  for (const [id, a] of agg) {
    out.set(id, a.error > 0 ? { severity: "error", count: a.error } : { severity: "warning", count: a.warning });
  }
  return out;
}

/** Validate a workbook into a flat, id-sorted list of issues. Pure + O(rows). */
export function validateModel(wb: Workbook): Issue[] {
  const issues: Issue[] = [];
  const add = (i: Issue) => issues.push(i);

  const nodes = wb.nodes ?? [];
  const assets = wb.assets ?? [];
  const io = wb.io ?? [];
  const flows = wb.flows ?? [];
  const links = wb.links ?? [];
  const markets = wb.markets ?? [];
  const demand = wb.demand ?? [];
  const technologies = wb.technologies ?? [];
  const transitions = wb.transitions ?? [];

  const nodeIds = new Set(nodes.map((r) => s(r.node_id)));
  const techIds = new Set(technologies.map((r) => s(r.technology_id)));
  const flowSet = new Set(flows.map((r) => s(r.flow_id)));

  // products = io outputs flagged is_product ∪ flows of kind "product"
  const products = new Set<string>();
  for (const r of io) if (s(r.role) === "output" && r.is_product) products.add(s(r.target));
  for (const c of flows) if (s(c.kind) === "product") products.add(s(c.flow_id));

  // io grouped by technology (inputs + has-any-output check)
  const inputsOfTech = new Map<string, string[]>();
  const techHasOutput = new Set<string>();
  for (const r of io) {
    const t = s(r.technology_id);
    const role = s(r.role);
    if (role === "input") (inputsOfTech.get(t) ?? inputsOfTech.set(t, []).get(t)!).push(s(r.target));
    if (role === "output") techHasOutput.add(t);
    // unknown-flow (input/output only; "impact" targets an impact, not a stream)
    if ((role === "input" || role === "output") && s(r.target) && !flowSet.has(s(r.target))) {
      add({
        id: `io-unknown-flow:${t}:${s(r.target)}`,
        rule: "io-unknown-flow",
        severity: "warning",
        title: "Unknown flow",
        message: `Technology "${t}" references flow "${s(r.target)}", which isn't defined in the library.`,
        scope: { techId: t },
      });
    }
  }

  // Ancestor-chain scope per node (self → root), cycle-guarded.
  const parentOf = new Map(nodes.map((r) => [s(r.node_id), s(r.parent_id)]));
  const scopeOf = (nodeId: string): Set<string> => {
    const out = new Set<string>();
    let cur: string | undefined = nodeId;
    while (cur && !out.has(cur)) {
      out.add(cur);
      cur = parentOf.get(cur) || undefined;
    }
    return out;
  };

  // ── Markets: free-buy + duplicates ──────────────────────────────────────────
  const marketSeen = new Set<string>();
  markets.forEach((r, rowIndex) => {
    const isBuy = "price" in r; // buy rows carry `price`; sell rows carry `sell_price`
    const target = s(r.target);
    const company = s(r.company);
    const side = isBuy ? "buy" : "sell";
    const dupKey = `${company}|${target}|${side}`;
    if (marketSeen.has(dupKey)) {
      add({
        id: `duplicate-market:${dupKey}:${rowIndex}`,
        rule: "duplicate-market",
        severity: "warning",
        title: "Duplicate market",
        message: `More than one ${side} market for "${target}" at this node.`,
        scope: { nodeId: company, flowId: target },
        sheet: "markets",
        rowIndex,
        fix: { label: "Remove duplicate", descriptor: { kind: "removeRow", sheet: "markets", rowIndex } },
      });
    }
    marketSeen.add(dupKey);
    if (isBuy && !(num(r.price) > 0)) {
      add({
        id: `free-buy-market:${company}:${target}:${rowIndex}`,
        rule: "free-buy-market",
        severity: "warning",
        title: "Free purchase",
        message: `Buy market for "${target}" has price 0 — the optimiser will buy it for free. Set a real price or remove it.`,
        scope: { nodeId: company, flowId: target },
        sheet: "markets",
        rowIndex,
        fix: {
          label: "Set price",
          descriptor: { kind: "patchRow", sheet: "markets", rowIndex, patch: {} },
          promptFor: { field: "price", label: `buy price for ${target}` },
        },
      });
    }
  });

  // ── Assets: capacity, baseline tech, unsatisfied inputs ────────────────────
  for (const m of assets) {
    const mid = s(m.asset_id);
    const tech = s(m.baseline_technology);
    if (!tech || !techIds.has(tech)) {
      add({
        id: `orphan-asset-no-tech:${mid}`,
        rule: "orphan-asset-no-tech",
        severity: "error",
        title: "Missing technology",
        message: tech
          ? `Asset "${mid}" runs technology "${tech}", which isn't in any library.`
          : `Asset "${mid}" has no baseline technology set.`,
        scope: { nodeId: mid },
      });
    }
    if (!(num(m.capacity) > 0)) {
      add({
        id: `nonpositive-capacity:${mid}`,
        rule: "nonpositive-capacity",
        severity: "error",
        title: "No capacity",
        message: `Asset "${mid}" has capacity ${s(m.capacity) || 0} — it can't produce anything.`,
        scope: { nodeId: mid },
        sheet: "assets",
        rowIndex: assets.indexOf(m),
        fix: {
          label: "Set capacity",
          descriptor: { kind: "patchRow", sheet: "assets", rowIndex: assets.indexOf(m), patch: {} },
          promptFor: { field: "capacity", label: "capacity", defaultValue: 1000 },
        },
      });
    }
    // unsatisfied-input — mirrors AssetInspector.inFrom verbatim.
    const scope = scopeOf(mid);
    for (const c of inputsOfTech.get(tech) ?? []) {
      const fedByLink = links.some(
        (x) => s(x.flow_id) === c && scope.has(s(x.to_node)) && !scope.has(s(x.from_node)),
      );
      const boughtAtNode = markets.some((x) => s(x.target) === c && s(x.price) !== "" && scope.has(s(x.company)));
      const comm = flows.find((x) => s(x.flow_id) === c);
      const purchasable = !!comm && (comm.purchasable === true || s(comm.price) !== "");
      if (!fedByLink && !boughtAtNode && !purchasable) {
        add({
          id: `unsatisfied-input:${mid}:${c}`,
          rule: "unsatisfied-input",
          severity: "error",
          title: "Unsatisfied input",
          message: `"${mid}" needs "${c}" but nothing supplies it — no upstream link, no market, and it isn't purchasable.`,
          scope: { nodeId: mid, flowId: c },
          fix: {
            label: `Make ${c} purchasable`,
            descriptor: { kind: "setFlowField", flowId: c, patch: { purchasable: true } },
          },
        });
      }
    }
  }

  // ── Demand: on a non-product, or non-positive ────────────────────────────────
  demand.forEach((r, rowIndex) => {
    const c = s(r.flow_id);
    if (c && products.size > 0 && !products.has(c)) {
      add({
        id: `demand-on-non-product:${s(r.company)}:${c}:${rowIndex}`,
        rule: "demand-on-non-product",
        severity: "error",
        title: "Demand on a non-product",
        message: `Target asks for "${c}", which isn't a product output of any technology. Only products can be delivered to demand.`,
        scope: { nodeId: s(r.company), flowId: c },
        sheet: "demand",
        rowIndex,
      });
    }
    if (!(num(r.amount) > 0)) {
      add({
        id: `demand-nonpositive:${s(r.company)}:${c}:${rowIndex}`,
        rule: "demand-nonpositive",
        severity: "warning",
        title: "Empty target",
        message: `Target for "${c}" has amount ${s(r.amount) || 0} — it asks for nothing.`,
        scope: { nodeId: s(r.company), flowId: c },
        sheet: "demand",
        rowIndex,
        fix: {
          label: "Set amount",
          descriptor: { kind: "patchRow", sheet: "demand", rowIndex, patch: {} },
          promptFor: { field: "amount", label: "amount", defaultValue: 100 },
        },
      });
    }
  });

  // ── Technologies in use that produce NOTHING (no output rows at all) ──────────
  // (An intermediate tech that outputs a non-product stream is fine in a value
  // chain — it feeds downstream — so we only flag a tech with zero outputs.)
  const usedTechs = new Set(assets.map((m) => s(m.baseline_technology)));
  for (const t of usedTechs) {
    if (t && techIds.has(t) && !techHasOutput.has(t)) {
      add({
        id: `tech-no-outputs:${t}`,
        rule: "tech-no-outputs",
        severity: "warning",
        title: "No outputs",
        message: `Technology "${t}" produces no output flow — it consumes inputs but makes nothing.`,
        scope: { techId: t },
      });
    }
  }

  // ── Links to/from a node that doesn't exist ────────────────────────────
  links.forEach((r, rowIndex) => {
    const from = s(r.from_node);
    const to = s(r.to_node);
    const bad = (from && !nodeIds.has(from)) || (to && !nodeIds.has(to));
    if (bad) {
      add({
        id: `link-dangling-node:${rowIndex}`,
        rule: "link-dangling-node",
        severity: "warning",
        title: "Dangling link",
        message: `A "${s(r.flow_id)}" link references a node that no longer exists.`,
        sheet: "links",
        rowIndex,
        fix: { label: "Remove", descriptor: { kind: "removeRow", sheet: "links", rowIndex } },
      });
    }
  });

  // ── Alternatives that equal the baseline (no-op transition) ───────────────────
  transitions.forEach((r, rowIndex) => {
    if (s(r.from_technology) && s(r.from_technology) === s(r.to_technology)) {
      add({
        id: `alt-equals-baseline:${rowIndex}`,
        rule: "alt-equals-baseline",
        severity: "warning",
        title: "No-op alternative",
        message: `An alternative switches "${s(r.from_technology)}" to itself.`,
        sheet: "transitions",
        rowIndex,
        fix: { label: "Remove", descriptor: { kind: "removeRow", sheet: "transitions", rowIndex } },
      });
    }
  });

  return issues.sort((a, b) => a.id.localeCompare(b.id));
}
