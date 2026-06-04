import { useCallback, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  Position,
  applyNodeChanges,
  type Connection,
  type NodeChange,
  type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  addEntity,
  connect as connectWb,
  deleteNode,
  persistLayout,
  workbookToGraph,
  type GraphNode,
  type NodeData,
  type NodeKind,
} from "../../graph/model";
import type { Workbook } from "../../types";

function PortList({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="port-row">
      <span className="port-label">{title}</span> {items.join(", ")}
    </div>
  );
}

function NodeView({ data }: NodeProps<NodeData>) {
  const p = data.ports;
  return (
    <div className={`node ${data.kind}`}>
      <Handle type="target" position={Position.Left} />
      <div className="node-kind">{data.kind}</div>
      <strong>{data.label}</strong>
      {data.kind === "process" && p ? (
        <div className="ports">
          <PortList title="⚡ in" items={p.energyIn} />
          <PortList title="📦 in" items={p.materialIn} />
          <PortList title="▸ product" items={p.products} />
          <PortList title="↻ residual" items={p.energyOut} />
          <PortList title="• by-product" items={p.byproducts} />
        </div>
      ) : (
        data.sub && <div className="muted">{data.sub}</div>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { process: NodeView, commodity: NodeView, market: NodeView, storage: NodeView };

interface Menu {
  x: number;
  y: number;
  nodeId?: string;
}

interface Props {
  workbook: Workbook;
  onChange: (wb: Workbook) => void;
}

/** Chemical-process-style canvas: drag to connect, right-click to add/delete.
 *  Streams = rounded nodes; facilities/markets/stores = squares. Two-way synced. */
export function FlowCanvas({ workbook, onChange }: Props) {
  const { nodes, edges } = useMemo(() => workbookToGraph(workbook), [workbook]);
  const [menu, setMenu] = useState<Menu | null>(null);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      if (changes.some((c) => c.type === "position")) {
        onChange(persistLayout(workbook, applyNodeChanges(changes, nodes) as GraphNode[]));
      }
    },
    [workbook, nodes, onChange],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      if (c.source && c.target) onChange(connectWb(workbook, c.source, c.target));
    },
    [workbook, onChange],
  );

  const add = (kind: NodeKind) => {
    onChange(addEntity(workbook, kind));
    setMenu(null);
  };

  return (
    <div className="view-full" onClick={() => menu && setMenu(null)}>
      <div className="toolbar">
        <button onClick={() => add("process")}>+ facility</button>
        <button onClick={() => add("commodity")}>+ stream</button>
        <button onClick={() => add("market")}>+ market</button>
        <button onClick={() => add("storage")}>+ storage</button>
        <span className="muted">
          drag handle→handle to connect (stream→facility = input, market→stream = supply); right-click to add/delete
        </span>
      </div>
      <div className="canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onConnect={onConnect}
          onPaneContextMenu={(e) => {
            e.preventDefault();
            setMenu({ x: e.clientX, y: e.clientY });
          }}
          onNodeContextMenu={(e, node) => {
            e.preventDefault();
            setMenu({ x: e.clientX, y: e.clientY, nodeId: node.id });
          }}
          fitView
        >
          <Background />
          <Controls />
        </ReactFlow>
        {menu && (
          <div className="context-menu" style={{ left: menu.x, top: menu.y }}>
            {menu.nodeId ? (
              <button
                onClick={() => {
                  onChange(deleteNode(workbook, menu.nodeId!));
                  setMenu(null);
                }}
              >
                Delete node
              </button>
            ) : (
              <>
                <button onClick={() => add("process")}>Add facility</button>
                <button onClick={() => add("commodity")}>Add stream</button>
                <button onClick={() => add("market")}>Add market</button>
                <button onClick={() => add("storage")}>Add storage</button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
