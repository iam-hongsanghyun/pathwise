// Pure, round-trip-safe bridge between the React Flow graph and the workbook.
// The graph and the editable tables are both controlled views over one Workbook.

import type { Edge, Node } from "reactflow";
import type { Row, Workbook } from "../types";

export interface ProcessNodeData {
  label: string;
  company: string;
  baseline_technology: string;
  capacity: number;
}
export interface FlowEdgeData {
  commodity_id: string;
}
export type ProcessNode = Node<ProcessNodeData>;
export type FlowEdge = Edge<FlowEdgeData>;

const str = (v: unknown, d = ""): string => (v == null ? d : String(v));
const num = (v: unknown, d = 0): number => (v == null || v === "" ? d : Number(v));

/** Build React Flow nodes/edges from a workbook. Positions come from the
 *  `node_layout` sheet when present, else a simple grid. */
export function workbookToGraph(wb: Workbook): { nodes: ProcessNode[]; edges: FlowEdge[] } {
  const layout = new Map<string, { x: number; y: number }>();
  for (const r of wb.node_layout ?? []) {
    layout.set(str(r.process_id), { x: num(r.x), y: num(r.y) });
  }
  const nodes: ProcessNode[] = (wb.processes ?? []).map((r, i) => {
    const id = str(r.process_id);
    const pos = layout.get(id) ?? { x: 80 + (i % 4) * 240, y: 80 + Math.floor(i / 4) * 160 };
    return {
      id,
      type: "process",
      position: pos,
      data: {
        label: id,
        company: str(r.company, "all"),
        baseline_technology: str(r.baseline_technology),
        capacity: num(r.capacity),
      },
    };
  });
  const edges: FlowEdge[] = (wb.edges ?? []).map((r, i) => {
    const from = str(r.from_process);
    const to = str(r.to_process);
    const commodity = str(r.commodity_id);
    return {
      id: `e${i}:${from}->${to}:${commodity}`,
      source: from,
      target: to,
      label: commodity,
      data: { commodity_id: commodity },
    };
  });
  return { nodes, edges };
}

/** Fold graph node positions + edges back into the workbook, preserving every
 *  other column on existing process/edge rows. */
export function graphToWorkbook(
  wb: Workbook,
  nodes: ProcessNode[],
  edges: FlowEdge[],
): Workbook {
  const prevProc = new Map<string, Row>((wb.processes ?? []).map((r) => [str(r.process_id), r]));
  const processes: Row[] = nodes.map((n) => ({
    ...(prevProc.get(n.id) ?? {}),
    process_id: n.id,
    company: n.data.company,
    baseline_technology: n.data.baseline_technology,
    capacity: n.data.capacity,
  }));
  const node_layout: Row[] = nodes.map((n) => ({
    process_id: n.id,
    x: Math.round(n.position.x),
    y: Math.round(n.position.y),
  }));
  const newEdges: Row[] = edges.map((e) => ({
    from_process: e.source,
    to_process: e.target,
    commodity_id: e.data?.commodity_id ?? str(e.label),
  }));
  return { ...wb, processes, node_layout, edges: newEdges };
}

/** Default commodity for a new connection: the source's first output that the
 *  target consumes, else the source's first output, else "". */
export function defaultEdgeCommodity(wb: Workbook, source: string, target: string): string {
  const techOf = (pid: string): string =>
    str((wb.processes ?? []).find((p) => str(p.process_id) === pid)?.baseline_technology);
  const outputs = (wb.process_outputs ?? [])
    .filter((r) => str(r.technology_id) === techOf(source))
    .map((r) => str(r.commodity_id));
  const inputs = new Set(
    (wb.process_inputs ?? [])
      .filter((r) => str(r.technology_id) === techOf(target))
      .map((r) => str(r.commodity_id)),
  );
  return outputs.find((c) => inputs.has(c)) ?? outputs[0] ?? "";
}
