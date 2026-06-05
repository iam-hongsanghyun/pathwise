import { useMemo } from "react";
import ReactFlow, { Background, Handle, Position, type NodeProps } from "reactflow";
import "reactflow/dist/style.css";
import { workbookToGraph, type NodeData } from "../graph/model";
import type { RunResult, Workbook } from "../types";

function ReadNode({ data }: NodeProps<NodeData & { active?: string }>) {
  return (
    <div className={`node ${data.kind}`}>
      <Handle type="target" position={Position.Left} />
      <div className="node-kind">{data.kind}</div>
      <strong>{data.label}</strong>
      {data.active && <div className="muted">▶ {data.active}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { process: ReadNode, commodity: ReadNode, market: ReadNode, storage: ReadNode };

interface Props {
  workbook: Workbook;
  result: RunResult;
  year: number;
}

/** Read-only process map for one year: nodes show the active technology, edges
 *  show that year's flow (so the slider animates the topology over time). */
export function TopologyChart({ workbook, result, year }: Props) {
  const { nodes, edges } = useMemo(() => {
    const g = workbookToGraph(workbook);
    const activeOf = new Map(
      result.outputs.technology
        .filter((t) => t.period === year)
        .map((t) => [`process:${t.process}`, t.technology]),
    );
    const nodes = g.nodes.map((n) => ({
      ...n,
      data: { ...n.data, active: activeOf.get(n.id) },
    }));
    const flowOf = new Map<string, number>();
    for (const f of result.outputs.flows)
      if (f.period === year)
        flowOf.set(`${f.from}->${f.to}:${f.commodity}`, (flowOf.get(`${f.from}->${f.to}:${f.commodity}`) ?? 0) + f.value);
    const edges = g.edges.map((e) => {
      // process→commodity / commodity→process edges aren't inter-facility flows;
      // only label the IRON→STEEL style edges where we have a flow value.
      const label = e.label;
      return { ...e, label, animated: true, style: { stroke: "#0f766e" } };
    });
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
