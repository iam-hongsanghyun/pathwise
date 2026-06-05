// Pure, round-trip bridge between the React Flow graph and the workbook.
// Node id = `${kind}:${entityId}`; the workbook stays the single source of truth.

import type { Edge, Node } from "reactflow";
import type { Workbook } from "../types";

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

  const nodes: GraphNode[] = [];
  let auto = 0;
  const place = (id: string) => layout.get(id) ?? { x: 60 + (auto % 6) * 210, y: 60 + Math.floor(auto++ / 6) * 150 };
  const add = (kind: NodeKind, entityId: string, label: string, sub?: string, ports?: FacilityPorts) => {
    const id = nodeId(kind, entityId);
    nodes.push({ id, type: kind, position: place(id), data: { kind, entityId, label, sub, ports } });
  };

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
  // commodity → process (input) / process → commodity (output): add an `io` row
  // on the process's baseline technology.
  const ioLink = (tech: string, target: string, role: "input" | "output") => {
    if (!tech) return;
    const exists = (wb.io ?? []).some(
      (r) => s(r.technology_id) === tech && s(r.target) === target && s(r.role, "input") === role,
    );
    if (!exists)
      out.io = [...(wb.io ?? []), { technology_id: tech, target, role, coefficient: 1 }];
  };
  if (a.kind === "commodity" && b.kind === "process") {
    ioLink(baselineOf(wb, b.entityId), a.entityId, "input");
    return out;
  }
  if (a.kind === "process" && b.kind === "commodity") {
    ioLink(baselineOf(wb, a.entityId), b.entityId, "output");
    return out;
  }
  return out;
}
