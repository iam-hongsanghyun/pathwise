import { useCallback, useMemo } from "react";
import ReactFlow, {
  addEdge,
  Background,
  Controls,
  Handle,
  Position,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  defaultEdgeCommodity,
  graphToWorkbook,
  workbookToGraph,
  type FlowEdge,
  type ProcessNode,
  type ProcessNodeData,
} from "../graph/model";
import type { Workbook } from "../types";

function ProcessNodeView({ data }: NodeProps<ProcessNodeData>) {
  return (
    <div className="pnode">
      <Handle type="target" position={Position.Left} />
      <strong>{data.label}</strong>
      <div className="muted">{data.baseline_technology || "—"}</div>
      <div className="muted">cap {data.capacity}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { process: ProcessNodeView };

interface Props {
  workbook: Workbook;
  onChange: (wb: Workbook) => void;
}

/** Drag-and-drop facility network: nodes = facilities, edges = stream flows.
 *  Edits fold straight back into the workbook (two-way sync). */
export function FacilityDesigner({ workbook, onChange }: Props) {
  const { nodes, edges } = useMemo(() => workbookToGraph(workbook), [workbook]);

  const commit = useCallback(
    (ns: ProcessNode[], es: FlowEdge[]) => onChange(graphToWorkbook(workbook, ns, es)),
    [workbook, onChange],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => commit(applyNodeChanges(changes, nodes) as ProcessNode[], edges),
    [nodes, edges, commit],
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => commit(nodes, applyEdgeChanges(changes, edges) as FlowEdge[]),
    [nodes, edges, commit],
  );
  const onConnect = useCallback(
    (c: Connection) => {
      if (!c.source || !c.target) return;
      const commodity = defaultEdgeCommodity(workbook, c.source, c.target);
      const edge: FlowEdge = {
        id: `e:${c.source}->${c.target}:${commodity}`,
        source: c.source,
        target: c.target,
        label: commodity,
        data: { commodity_id: commodity },
      };
      commit(nodes, addEdge(edge, edges) as FlowEdge[]);
    },
    [workbook, nodes, edges, commit],
  );

  const addFacility = () => {
    const id = uniqueId(workbook, "F");
    const next: Workbook = {
      ...workbook,
      processes: [
        ...(workbook.processes ?? []),
        { process_id: id, company: "all", baseline_technology: "", capacity: 1000 },
      ],
    };
    onChange(next);
  };

  return (
    <div className="designer">
      <div className="toolbar">
        <button onClick={addFacility}>+ facility</button>
        <span className="muted">drag to connect outputs → inputs; double-click a stream label in Tables to set its commodity</span>
      </div>
      <div className="canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}

function uniqueId(wb: Workbook, prefix: string): string {
  const existing = new Set((wb.processes ?? []).map((p) => String(p.process_id)));
  let i = 1;
  while (existing.has(`${prefix}${i}`)) i += 1;
  return `${prefix}${i}`;
}
