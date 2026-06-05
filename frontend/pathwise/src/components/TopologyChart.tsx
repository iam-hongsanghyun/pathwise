import { useMemo } from "react";
import ReactFlow, { Background, Handle, Position, type Edge, type NodeProps } from "reactflow";
import "reactflow/dist/style.css";
import { nodeId, workbookToGraph, type GraphNode, type NodeData } from "../graph/model";
import type { RunResult, Workbook } from "../types";

type RNData = NodeData & { active?: string; dim?: boolean };

function ReadNode({ data }: NodeProps<RNData>) {
  return (
    <div className={`node ${data.kind}${data.dim ? " dim" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="node-kind">{data.kind}</div>
      <strong>{data.label}</strong>
      {data.kind === "process" && <div className="muted">{data.active ? `▶ ${data.active}` : "idle"}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { process: ReadNode, commodity: ReadNode, market: ReadNode, storage: ReadNode };

const s = (v: unknown): string => (v == null ? "" : String(v));

function ioOf(wb: Workbook, tech: string, role: "input" | "output"): string[] {
  return [
    ...(wb.io ?? [])
      .filter((r) => s(r.technology_id) === tech && s(r.role || "input") === role)
      .map((r) => s(r.target)),
    ...(wb[role === "input" ? "process_inputs" : "process_outputs"] ?? [])
      .filter((r) => s(r.technology_id) === tech)
      .map((r) => s(r.commodity_id)),
  ];
}

interface Props {
  workbook: Workbook;
  result: RunResult;
  year: number;
}

/** Read-only process map for one year. Edges are drawn from each facility's
 *  ACTIVE technology that year (so the diagram restructures across the slider —
 *  coal in a BF year, hydrogen in an H2-DRI year); idle facilities are dimmed
 *  and market supply (e.g. imported iron) is shown. */
export function TopologyChart({ workbook, result, year }: Props) {
  const { nodes, edges } = useMemo(() => {
    const base = workbookToGraph(workbook);
    const pos = new Map(base.nodes.map((n) => [n.id, n.position]));
    const shown = new Set(base.nodes.map((n) => n.id));
    // A facility is "operating" a tech this year only if it has real throughput
    // (a tech can be nominally on with zero output while its product is imported).
    const active = new Map<string, string>();
    for (const t of result.outputs.throughput)
      if (t.period === year && t.value > 1) active.set(t.process, t.technology);

    const nodes: GraphNode[] = base.nodes.map((n) => {
      if (n.data.kind !== "process") return n;
      const tech = active.get(n.data.entityId);
      return { ...n, data: { ...n.data, active: tech, dim: !tech } as RNData };
    });

    const edges: Edge[] = [];
    const add = (from: string, to: string, label?: string) => {
      if (shown.has(from) && shown.has(to))
        edges.push({ id: `${from}->${to}-${edges.length}`, source: from, target: to, label, style: { stroke: "#0f766e" } });
    };
    for (const [proc, tech] of active) {
      for (const c of ioOf(workbook, tech, "input")) add(nodeId("commodity", c), nodeId("process", proc));
      for (const c of ioOf(workbook, tech, "output")) add(nodeId("process", proc), nodeId("commodity", c));
    }
    // Market supply that's actually used this year (e.g. imported HBI/iron).
    for (const m of result.outputs.markets) {
      const buy = m.by_period.find((b) => b.period === year)?.buy ?? 0;
      if (buy > 1) add(nodeId("market", m.market), nodeId("commodity", m.commodity), buy.toFixed(0));
    }
    void pos;
    return { nodes, edges };
  }, [workbook, result, year]);

  return (
    <div className="topology">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView nodesDraggable={false}>
        <Background />
      </ReactFlow>
    </div>
  );
}
