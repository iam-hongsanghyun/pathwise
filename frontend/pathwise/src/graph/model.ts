// Pure, round-trip bridge between the React Flow graph and the workbook.
// Node id = `${kind}:${entityId}`; the workbook stays the single source of truth.

import type { Edge, Node } from "reactflow";
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
export type GraphNode = Node<NodeData>;
export type GraphEdge = Edge;

const s = (v: unknown, d = ""): string => (v == null ? d : String(v));
const n = (v: unknown, d = 0): number => (v == null || v === "" ? d : Number(v));
export const nodeId = (kind: NodeKind, id: string): string => `${kind}:${id}`;
const parse = (id: string): { kind: NodeKind; entityId: string } => {
  const i = id.indexOf(":");
  return { kind: id.slice(0, i) as NodeKind, entityId: id.slice(i + 1) };
};

function baselineOf(wb: Workbook, process: string): string {
  return s(
    (wb.processes ?? []).find((p) => s(p.process_id) === process)?.baseline_technology,
  );
}

/** Derive React Flow nodes + edges from the workbook. */
export function workbookToGraph(wb: Workbook): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const layout = new Map<string, { x: number; y: number }>();
  for (const r of wb.node_layout ?? []) layout.set(s(r.id), { x: n(r.x), y: n(r.y) });

  const kindOf = new Map<string, string>(
    (wb.commodities ?? []).map((r) => [s(r.commodity_id), s(r.kind, "material")]),
  );

  const nodes: GraphNode[] = [];
  let auto = 0;
  const place = (id: string) => layout.get(id) ?? { x: 60 + (auto % 5) * 200, y: 60 + Math.floor(auto++ / 5) * 130 };
  const add = (kind: NodeKind, entityId: string, label: string, sub?: string, ports?: FacilityPorts) => {
    const id = nodeId(kind, entityId);
    nodes.push({ id, type: kind, position: place(id), data: { kind, entityId, label, sub, ports } });
  };

  const facilityPorts = (process: string): FacilityPorts => {
    const tech = s((wb.processes ?? []).find((p) => s(p.process_id) === process)?.baseline_technology);
    const p: FacilityPorts = { energyIn: [], materialIn: [], products: [], byproducts: [], energyOut: [] };
    for (const r of wb.process_inputs ?? []) {
      if (s(r.technology_id) !== tech) continue;
      const c = s(r.commodity_id);
      (kindOf.get(c) === "energy" ? p.energyIn : p.materialIn).push(c);
    }
    for (const r of wb.process_outputs ?? []) {
      if (s(r.technology_id) !== tech) continue;
      const c = s(r.commodity_id);
      const k = kindOf.get(c);
      if (k === "product") p.products.push(c);
      else if (k === "energy") p.energyOut.push(c);
      else p.byproducts.push(c);
    }
    return p;
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
    for (const r of wb.process_inputs ?? [])
      if (s(r.technology_id) === tech) edge(nodeId("commodity", s(r.commodity_id)), nodeId("process", pid));
    for (const r of wb.process_outputs ?? [])
      if (s(r.technology_id) === tech) edge(nodeId("process", pid), nodeId("commodity", s(r.commodity_id)));
  }
  for (const r of wb.markets ?? [])
    if (s(r.target_kind, "commodity") === "commodity")
      edge(nodeId("market", s(r.market_id)), nodeId("commodity", s(r.target)), s(r.tag));
  for (const r of wb.storage ?? [])
    edge(nodeId("storage", s(r.storage_id)), nodeId("commodity", s(r.commodity_id)));
  return { nodes, edges };
}

/** Persist node positions into the workbook's `node_layout` sheet. */
export function persistLayout(wb: Workbook, nodes: GraphNode[]): Workbook {
  const node_layout: Row[] = nodes.map((nd) => ({
    id: nd.id,
    x: Math.round(nd.position.x),
    y: Math.round(nd.position.y),
  }));
  return { ...wb, node_layout };
}

function uniqueId(wb: Workbook, sheet: string, col: string, prefix: string): string {
  const seen = new Set((wb[sheet] ?? []).map((r) => s(r[col])));
  let i = 1;
  while (seen.has(`${prefix}${i}`)) i += 1;
  return `${prefix}${i}`;
}

/** Add a new entity of the given kind; returns the new workbook. */
export function addEntity(wb: Workbook, kind: NodeKind): Workbook {
  const next: Workbook = { ...wb };
  if (kind === "commodity") {
    const id = uniqueId(wb, "commodities", "commodity_id", "stream");
    next.commodities = [...(wb.commodities ?? []), { commodity_id: id, kind: "material", unit: "unit" }];
  } else if (kind === "process") {
    const id = uniqueId(wb, "processes", "process_id", "F");
    next.processes = [...(wb.processes ?? []), { process_id: id, company: "all", baseline_technology: "", capacity: 1000 }];
  } else if (kind === "market") {
    const id = uniqueId(wb, "markets", "market_id", "MKT");
    next.markets = [...(wb.markets ?? []), { market_id: id, target: "", target_kind: "commodity", price: 0 }];
  } else {
    const id = uniqueId(wb, "storage", "storage_id", "STO");
    next.storage = [...(wb.storage ?? []), { storage_id: id, commodity_id: "", max_capacity: 0 }];
  }
  return next;
}

/** Delete a node's underlying entity (and dependent rows). */
export function deleteNode(wb: Workbook, id: string): Workbook {
  const { kind, entityId } = parse(id);
  const out: Workbook = { ...wb };
  const drop = (sheet: string, col: string) =>
    (out[sheet] = (wb[sheet] ?? []).filter((r) => s(r[col]) !== entityId));
  if (kind === "commodity") drop("commodities", "commodity_id");
  else if (kind === "process") drop("processes", "process_id");
  else if (kind === "market") drop("markets", "market_id");
  else if (kind === "storage") drop("storage", "storage_id");
  out.node_layout = (wb.node_layout ?? []).filter((r) => s(r.id) !== id);
  return out;
}

/** Wire a connection: writes the appropriate sheet based on endpoint kinds. */
export function connect(wb: Workbook, sourceId: string, targetId: string): Workbook {
  const a = parse(sourceId);
  const b = parse(targetId);
  const out: Workbook = { ...wb };
  // market → commodity : set the market's traded commodity.
  if (a.kind === "market" && b.kind === "commodity") {
    out.markets = (wb.markets ?? []).map((r) =>
      s(r.market_id) === a.entityId ? { ...r, target: b.entityId, target_kind: "commodity" } : r,
    );
    return out;
  }
  // storage → commodity : set the stored commodity.
  if (a.kind === "storage" && b.kind === "commodity") {
    out.storage = (wb.storage ?? []).map((r) =>
      s(r.storage_id) === a.entityId ? { ...r, commodity_id: b.entityId } : r,
    );
    return out;
  }
  // commodity → process : add an input on the process's baseline tech.
  if (a.kind === "commodity" && b.kind === "process") {
    const tech = baselineOf(wb, b.entityId);
    const exists = (wb.process_inputs ?? []).some(
      (r) => s(r.technology_id) === tech && s(r.commodity_id) === a.entityId,
    );
    if (tech && !exists)
      out.process_inputs = [
        ...(wb.process_inputs ?? []),
        { technology_id: tech, commodity_id: a.entityId, intensity: 1 },
      ];
    return out;
  }
  // process → commodity : add an output on the process's baseline tech.
  if (a.kind === "process" && b.kind === "commodity") {
    const tech = baselineOf(wb, a.entityId);
    const exists = (wb.process_outputs ?? []).some(
      (r) => s(r.technology_id) === tech && s(r.commodity_id) === b.entityId,
    );
    if (tech && !exists)
      out.process_outputs = [
        ...(wb.process_outputs ?? []),
        { technology_id: tech, commodity_id: b.entityId, yield: 1 },
      ];
    return out;
  }
  return out;
}
