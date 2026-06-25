// Pure, round-trip bridge between the topology graph and the workbook.
// Node id = `${kind}:${entityId}`; the workbook stays the single source of
// truth. Pure-logic layer: no React / no chart library types.

import type { Row, Workbook } from "../types";

export type NodeKind = "process" | "commodity" | "market" | "storage";
export interface FacilityPorts {
  energyIn: string[];
  materialIn: string[];
  products: string[];
  byproducts: string[];
  energyOut: string[]; // residual energy (heat/steam) out
}
export interface NodeData {
  kind: NodeKind;
  entityId: string;
  label: string;
  sub?: string;
  ports?: FacilityPorts;
}
export interface GraphNode {
  id: string;
  position: { x: number; y: number };
  data: NodeData;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
}

const s = (v: unknown, d = ""): string => (v == null ? d : String(v));
const n = (v: unknown, d = 0): number => (v == null || v === "" ? d : Number(v));
export const nodeId = (kind: NodeKind, id: string): string => `${kind}:${id}`;
/** dataTransfer MIME type for dragging a tree item onto the canvas. */
export const DRAG_MIME = "application/pathwise-node";

/** Derive React Flow nodes + edges from the workbook. Every component is shown
 *  on the editing canvas (and is draggable); `node_layout` only stores positions
 *  — a node without a saved position is auto-laid-out until it is moved. */
export function workbookToGraph(wb: Workbook): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const layout = new Map<string, { x: number; y: number }>();
  for (const r of wb.node_layout ?? []) layout.set(s(r.id), { x: n(r.x), y: n(r.y) });

  const kindOf = new Map<string, string>(
    (wb.commodities ?? []).map((r) => [s(r.commodity_id), s(r.kind, "material")]),
  );

  // Inputs/outputs come from the unified `io` table (legacy sheets as fallback).
  const inputsOf = (tech: string): string[] => [
    ...(wb.io ?? [])
      .filter((r) => s(r.technology_id) === tech && s(r.role, "input") === "input")
      .map((r) => s(r.target)),
    ...(wb.process_inputs ?? [])
      .filter((r) => s(r.technology_id) === tech)
      .map((r) => s(r.commodity_id)),
  ];
  const outputsOf = (tech: string): string[] => [
    ...(wb.io ?? [])
      .filter((r) => s(r.technology_id) === tech && s(r.role) === "output")
      .map((r) => s(r.target)),
    ...(wb.process_outputs ?? [])
      .filter((r) => s(r.technology_id) === tech)
      .map((r) => s(r.commodity_id)),
  ];
  const facilityPorts = (process: string): FacilityPorts => {
    const tech = s((wb.processes ?? []).find((p) => s(p.process_id) === process)?.baseline_technology);
    const p: FacilityPorts = { energyIn: [], materialIn: [], products: [], byproducts: [], energyOut: [] };
    for (const c of inputsOf(tech)) (kindOf.get(c) === "energy" ? p.energyIn : p.materialIn).push(c);
    for (const c of outputsOf(tech)) {
      const k = kindOf.get(c);
      if (k === "product") p.products.push(c);
      else if (k === "energy") p.energyOut.push(c);
      else p.byproducts.push(c);
    }
    return p;
  };

  const layered = layeredLayout(wb, inputsOf, outputsOf);
  const nodes: GraphNode[] = [];
  let auto = 0;
  // Saved position wins; else the layered left→right placement; else a grid.
  const place = (id: string) =>
    layout.get(id) ??
    layered.get(id) ?? { x: 60 + (auto % 6) * 210, y: 60 + Math.floor(auto++ / 6) * 150 };
  const add = (kind: NodeKind, entityId: string, label: string, sub?: string, ports?: FacilityPorts) => {
    const id = nodeId(kind, entityId);
    nodes.push({ id, position: place(id), data: { kind, entityId, label, sub, ports } });
  };

  for (const r of wb.commodities ?? []) add("commodity", s(r.commodity_id), s(r.commodity_id), s(r.kind));
  for (const r of wb.processes ?? [])
    add("process", s(r.process_id), s(r.process_id), s(r.baseline_technology), facilityPorts(s(r.process_id)));
  for (const r of wb.markets ?? []) add("market", s(r.market_id), s(r.market_id), s(r.target_kind, "commodity"));
  for (const r of wb.storage ?? []) add("storage", s(r.storage_id), s(r.storage_id), s(r.commodity_id));

  const has = new Set(nodes.map((nd) => nd.id));
  const edges: GraphEdge[] = [];
  const edge = (from: string, to: string, label?: string) => {
    if (has.has(from) && has.has(to)) edges.push({ id: `${from}->${to}`, source: from, target: to, label });
  };
  // Technology inputs/outputs → commodity↔process edges (via each process's baseline tech).
  for (const p of wb.processes ?? []) {
    const pid = s(p.process_id);
    const tech = s(p.baseline_technology);
    for (const c of inputsOf(tech)) edge(nodeId("commodity", c), nodeId("process", pid));
    for (const c of outputsOf(tech)) edge(nodeId("process", pid), nodeId("commodity", c));
  }
  for (const r of wb.markets ?? [])
    if (s(r.target_kind, "commodity") === "commodity")
      edge(nodeId("market", s(r.market_id)), nodeId("commodity", s(r.target)), s(r.tag));
  for (const r of wb.storage ?? [])
    edge(nodeId("storage", s(r.storage_id)), nodeId("commodity", s(r.commodity_id)));
  return { nodes, edges };
}

/** Layered left→right placement for nodes with no saved position.
 *
 *  Columns alternate commodity / process by flow depth, so the map reads as
 *  inputs → stage 1 → intermediate → stage 2 → … → product (left to right),
 *  matching the input-left / output-right handles. Raw inputs sit in column 0;
 *  a process at flow depth `d` sits in column `2d+1`; a commodity produced by
 *  that process in column `2d+2`. Markets sit just left of the commodity they
 *  supply; storage shares its commodity's column. Within a column, nodes stack
 *  top-to-bottom. Returns `nodeId → {x, y}`. */
function layeredLayout(
  wb: Workbook,
  inputsOf: (tech: string) => string[],
  outputsOf: (tech: string) => string[],
): Map<string, { x: number; y: number }> {
  const producers = new Map<string, string[]>(); // commodity → producing process ids
  const procInputs = new Map<string, string[]>();
  for (const p of wb.processes ?? []) {
    const pid = s(p.process_id);
    const tech = s(p.baseline_technology);
    procInputs.set(pid, inputsOf(tech));
    for (const c of outputsOf(tech)) producers.set(c, [...(producers.get(c) ?? []), pid]);
  }

  const depthCache = new Map<string, number>();
  const depth = (pid: string, seen: Set<string>): number => {
    const cached = depthCache.get(pid);
    if (cached !== undefined) return cached;
    if (seen.has(pid)) return 0; // cycle guard
    seen.add(pid);
    let d = 0;
    for (const c of procInputs.get(pid) ?? [])
      for (const up of producers.get(c) ?? []) if (up !== pid) d = Math.max(d, depth(up, seen) + 1);
    depthCache.set(pid, d);
    return d;
  };
  const commodityCol = (c: string): number => {
    const prod = producers.get(c) ?? [];
    return prod.length ? Math.max(...prod.map((p) => 2 * depth(p, new Set()) + 2)) : 0;
  };

  const colOf = new Map<string, number>();
  for (const p of wb.processes ?? [])
    colOf.set(nodeId("process", s(p.process_id)), 2 * depth(s(p.process_id), new Set()) + 1);
  for (const r of wb.commodities ?? [])
    colOf.set(nodeId("commodity", s(r.commodity_id)), commodityCol(s(r.commodity_id)));
  for (const r of wb.markets ?? [])
    colOf.set(nodeId("market", s(r.market_id)), Math.max(0, commodityCol(s(r.target)) - 1));
  for (const r of wb.storage ?? [])
    colOf.set(nodeId("storage", s(r.storage_id)), commodityCol(s(r.commodity_id)));

  const byCol = new Map<number, string[]>();
  for (const [id, col] of colOf) byCol.set(col, [...(byCol.get(col) ?? []), id]);
  const pos = new Map<string, { x: number; y: number }>();
  const COL_W = 220;
  const ROW_H = 108;
  for (const [col, ids] of byCol) {
    ids.sort();
    ids.forEach((id, i) => pos.set(id, { x: 40 + col * COL_W, y: 40 + i * ROW_H }));
  }
  return pos;
}

/** Persist node positions into the workbook's `node_layout` sheet — upserts a
 *  row for every current node (so dragging an auto-laid-out node sticks). */
export function persistLayout(wb: Workbook, nodes: GraphNode[]): Workbook {
  const rows = new Map((wb.node_layout ?? []).map((r) => [s(r.id), { ...r }]));
  for (const nd of nodes) {
    rows.set(nd.id, { id: nd.id, x: Math.round(nd.position.x), y: Math.round(nd.position.y) });
  }
  return { ...wb, node_layout: [...rows.values()] };
}

/** Place an existing entity on the map at (x, y) — adds a `node_layout` row. */
export function placeEntity(wb: Workbook, dragId: string, x: number, y: number): Workbook {
  const existing = (wb.node_layout ?? []).filter((r) => s(r.id) !== dragId);
  return {
    ...wb,
    node_layout: [...existing, { id: dragId, x: Math.round(x), y: Math.round(y) }],
  };
}

/** Remove an entity from the map (un-place) — keeps its data row. */
export function unplace(wb: Workbook, id: string): Workbook {
  return { ...wb, node_layout: (wb.node_layout ?? []).filter((r) => s(r.id) !== id) };
}

/** Create a new facility running ``tech`` and place it at (x, y). Used when a
 *  technology is dragged from the palette onto the canvas. */
export function addFacilityWithTech(wb: Workbook, tech: string, x: number, y: number): Workbook {
  const seen = new Set((wb.processes ?? []).map((r) => s(r.process_id)));
  let i = 1;
  while (seen.has(`F${i}`)) i += 1;
  const id = `F${i}`;
  return placeEntity(
    {
      ...wb,
      processes: [
        ...(wb.processes ?? []),
        { process_id: id, company: "all", baseline_technology: tech, capacity: 1000 },
      ],
    },
    nodeId("process", id),
    x,
    y,
  );
}

/** Delete an entity row and everything that directly references it: its
 *  node_layout placement, edges touching it, and (for a commodity) the io rows
 *  that consume/produce it. Technology rows are untouched (shared recipes). */
export function deleteEntity(wb: Workbook, id: string): Workbook {
  const i = id.indexOf(":");
  const kind = id.slice(0, i) as NodeKind;
  const entityId = id.slice(i + 1);
  const sheetOf: Record<NodeKind, { sheet: string; idCol: string }> = {
    process: { sheet: "processes", idCol: "process_id" },
    commodity: { sheet: "commodities", idCol: "commodity_id" },
    market: { sheet: "markets", idCol: "market_id" },
    storage: { sheet: "storage", idCol: "storage_id" },
  };
  const { sheet, idCol } = sheetOf[kind];
  const out: Workbook = {
    ...wb,
    [sheet]: (wb[sheet] ?? []).filter((r) => s(r[idCol]) !== entityId),
    node_layout: (wb.node_layout ?? []).filter((r) => s(r.id) !== id),
  };
  if (kind === "process") {
    out.edges = (wb.edges ?? []).filter(
      (r) => s(r.from_process) !== entityId && s(r.to_process) !== entityId,
    );
    out.levers = (wb.levers ?? []).filter(
      (r) => s(r.facility) !== entityId && s(r.applies_to) !== entityId,
    );
    out.macc_links = (wb.macc_links ?? []).filter((r) => s(r.facility) !== entityId);
  }
  if (kind === "commodity") {
    out.io = (wb.io ?? []).filter((r) => s(r.target) !== entityId);
    out.edges = (wb.edges ?? []).filter((r) => s(r.commodity_id) !== entityId);
    out.demand = (wb.demand ?? []).filter((r) => s(r.commodity_id) !== entityId);
  }
  return out;
}

/** Delete a facility and every facility connected to it through `edges`
 *  (the whole chain), including the edges and placements between them. */
export function deleteChain(wb: Workbook, processId: string): Workbook {
  const adj = new Map<string, Set<string>>();
  for (const e of wb.edges ?? []) {
    const a = s(e.from_process);
    const b = s(e.to_process);
    (adj.get(a) ?? adj.set(a, new Set()).get(a)!).add(b);
    (adj.get(b) ?? adj.set(b, new Set()).get(b)!).add(a);
  }
  const doomed = new Set<string>([processId]);
  const queue = [processId];
  while (queue.length) {
    for (const next of adj.get(queue.pop()!) ?? [])
      if (!doomed.has(next)) {
        doomed.add(next);
        queue.push(next);
      }
  }
  let out = wb;
  for (const pid of doomed) out = deleteEntity(out, nodeId("process", pid));
  return out;
}

/** Clear every saved node position — the map falls back to the auto-layout. */
export function clearLayout(wb: Workbook): Workbook {
  return { ...wb, node_layout: [] };
}

/** Register `toTech` as a transition option of `fromTech` (deduped). */
export function addTransitionOption(
  wb: Workbook,
  fromTech: string,
  toTech: string,
  capexPerCapacity = 0,
): Workbook {
  if (!fromTech || !toTech || fromTech === toTech) return wb;
  const exists = (wb.transitions ?? []).some(
    (r) => s(r.from_technology) === fromTech && s(r.to_technology) === toTech,
  );
  if (exists) return wb;
  return {
    ...wb,
    transitions: [
      ...(wb.transitions ?? []),
      {
        from_technology: fromTech,
        to_technology: toTech,
        action: "replace",
        capex_per_capacity: capexPerCapacity,
      },
    ],
  };
}

/** Create a technology row if it does not exist yet (a blank recipe to edit). */
export function ensureTechnology(wb: Workbook, techId: string): Workbook {
  if (!techId || (wb.technologies ?? []).some((r) => s(r.technology_id) === techId)) return wb;
  return {
    ...wb,
    technologies: [
      ...(wb.technologies ?? []),
      { technology_id: techId, lifespan: 20, actions: "continue,replace,renew" },
    ],
  };
}

/** Add a lever (one starter block). Install it directly on a `facility`
 *  (that plant only) or a `technology` (every facility running it — each
 *  still adopts independently) — or NEITHER: a catalogue lever, deployed
 *  later by bundling it into a MACC. `macc` adds it to that bundle. */
export function addLever(
  wb: Workbook,
  opts: {
    facility?: string;
    technology?: string;
    type: "energy_efficiency" | "emission_reduction" | "environmental";
    target: string;
    lifetime?: number;
    reduction: number;
    capex: number;
    macc?: string;
  },
): Workbook {
  const where = opts.facility || opts.technology || "catalogue";
  const taken = new Set((wb.levers ?? []).map((r) => s(r.lever_id)));
  let mid = `${where} · ${opts.target} lever`;
  for (let i = 2; taken.has(mid); i += 1) mid = `${where} · ${opts.target} lever ${i}`;
  const row: Row = {
    lever_id: mid,
    type: opts.type,
    target: opts.target,
    lifetime: opts.lifetime ?? 15,
  };
  if (opts.facility) row.facility = opts.facility;
  if (opts.technology) row.technology = opts.technology;
  const out: Workbook = {
    ...wb,
    levers: [...(wb.levers ?? []), row],
    lever_blocks: [
      ...(wb.lever_blocks ?? []),
      { lever_id: mid, block: 0, reduction: opts.reduction, capex: opts.capex },
    ],
  };
  if (opts.macc) out.maccs = [...(wb.maccs ?? []), { macc: opts.macc, lever_id: mid }];
  return out;
}

/** The four ways a MACC deployment can name its target. */
export const MACC_LINK_KINDS = ["facility", "technology", "commodity", "storage"] as const;
export type MaccLinkKind = (typeof MACC_LINK_KINDS)[number];

/** Expand lever definitions into per-facility instances — the TS mirror of
 *  the assembler: direct `facility` / `technology` columns, plus every MACC
 *  the lever belongs to (`maccs`) that is deployed (`macc_links` — on a
 *  facility, a technology, a stream, or a store), plus the legacy
 *  `applies_to` / `set` columns. One row per (lever, facility). */
export function resolveLevers(
  wb: Workbook,
): { lever_id: string; base_id: string; applies_to: string; type: string; target: string }[] {
  const procIds = new Set((wb.processes ?? []).map((r) => s(r.process_id)));
  const byBaseline = new Map<string, string[]>();
  for (const p of wb.processes ?? []) {
    const tech = s(p.baseline_technology);
    byBaseline.set(tech, [...(byBaseline.get(tech) ?? []), s(p.process_id)]);
  }
  const resolve = (target: string): string[] =>
    procIds.has(target) ? [target] : (byBaseline.get(target) ?? []);
  // Streams/stores resolve to consumers: every facility whose baseline
  // technology takes the stream as an input (mirrors the assembler).
  const techInputs = new Map<string, Set<string>>();
  const addInput = (tech: string, commodity: string) => {
    if (tech && commodity) (techInputs.get(tech) ?? techInputs.set(tech, new Set()).get(tech)!).add(commodity);
  };
  for (const r of wb.process_inputs ?? []) addInput(s(r.technology_id), s(r.commodity_id));
  for (const r of wb.io ?? [])
    if (s(r.role, "input") === "input") addInput(s(r.technology_id), s(r.target));
  const consumers = (commodity: string): string[] =>
    (wb.processes ?? [])
      .filter((p) => techInputs.get(s(p.baseline_technology))?.has(commodity))
      .map((p) => s(p.process_id));
  const storageCommodity = new Map(
    (wb.storage ?? []).map((r) => [s(r.storage_id), s(r.commodity_id)]),
  );
  const resolveLink = (kind: MaccLinkKind, target: string): string[] => {
    if (kind === "commodity") return consumers(target);
    if (kind === "storage") {
      const stored = storageCommodity.get(target);
      return stored ? consumers(stored) : [];
    }
    return resolve(target);
  };
  const linksBySet = new Map<string, string[]>();
  for (const r of wb.lever_links ?? []) {
    const set = s(r.set);
    if (set && s(r.applies_to))
      linksBySet.set(set, [...(linksBySet.get(set) ?? []), s(r.applies_to)]);
  }
  const maccsByLever = new Map<string, string[]>();
  for (const r of wb.maccs ?? []) {
    const mid = s(r.lever_id);
    if (mid && s(r.macc)) maccsByLever.set(mid, [...(maccsByLever.get(mid) ?? []), s(r.macc)]);
  }
  const maccTargets = new Map<string, { kind: MaccLinkKind; name: string }[]>();
  for (const r of wb.macc_links ?? []) {
    const macc = s(r.macc);
    if (!macc) continue;
    for (const kind of MACC_LINK_KINDS) {
      const name = s(r[kind]);
      if (name) maccTargets.set(macc, [...(maccTargets.get(macc) ?? []), { kind, name }]);
    }
  }
  const out: { lever_id: string; base_id: string; applies_to: string; type: string; target: string }[] = [];
  for (const m of wb.levers ?? []) {
    const mid = s(m.lever_id);
    const targets: string[] = [];
    if (s(m.facility)) targets.push(...resolve(s(m.facility)));
    if (s(m.technology)) targets.push(...resolve(s(m.technology)));
    for (const macc of maccsByLever.get(mid) ?? [])
      for (const link of maccTargets.get(macc) ?? [])
        targets.push(...resolveLink(link.kind, link.name));
    if (s(m.applies_to)) targets.push(...resolve(s(m.applies_to))); // legacy
    for (const link of linksBySet.get(s(m.set)) ?? []) targets.push(...resolve(link)); // legacy
    const unique = [...new Set(targets)];
    for (const pid of unique)
      out.push({
        lever_id: unique.length === 1 ? mid : `${mid} @ ${pid}`,
        base_id: mid,
        applies_to: pid,
        type: s(m.type, "energy_efficiency"),
        target: s(m.target),
      });
  }
  return out;
}

/** Deploy a named MACC on a facility, technology, stream or store (deduped). */
export function applyMacc(
  wb: Workbook,
  macc: string,
  target: Partial<Record<MaccLinkKind, string>>,
): Workbook {
  if (!macc || !MACC_LINK_KINDS.some((k) => target[k])) return wb;
  const exists = (wb.macc_links ?? []).some(
    (r) => s(r.macc) === macc && MACC_LINK_KINDS.every((k) => s(r[k]) === (target[k] ?? "")),
  );
  if (exists) return wb;
  const row: Row = { macc };
  for (const k of MACC_LINK_KINDS) row[k] = target[k] ?? null;
  return { ...wb, macc_links: [...(wb.macc_links ?? []), row] };
}

/** Distinct MACC names with members (built in the maccs sheet). */
export function maccNames(wb: Workbook): string[] {
  return [...new Set((wb.maccs ?? []).map((r) => s(r.macc)).filter(Boolean))];
}
