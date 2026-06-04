import { useCallback, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  Position,
  applyNodeChanges,
  type Connection,
  type NodeChange,
  type NodeProps,
  type ReactFlowInstance,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  DRAG_MIME,
  connect as connectWb,
  persistLayout,
  placeEntity,
  unplace,
  workbookToGraph,
  type FacilityPorts,
  type GraphNode,
  type NodeData,
  type NodeKind,
} from "../../graph/model";
import type { Workbook } from "../../types";

const SHEET_OF: Record<NodeKind, { sheet: string; idCol: string }> = {
  process: { sheet: "processes", idCol: "process_id" },
  commodity: { sheet: "commodities", idCol: "commodity_id" },
  market: { sheet: "markets", idCol: "market_id" },
  storage: { sheet: "storage", idCol: "storage_id" },
};

function PortList({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="port-row">
      <span className="port-label">{title}</span> {items.join(", ")}
    </div>
  );
}

function NodeView({ data }: NodeProps<NodeData>) {
  const p: FacilityPorts | undefined = data.ports;
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

interface Props {
  workbook: Workbook;
  onChange: (wb: Workbook) => void;
  onSelect?: (sel: { sheet: string; idCol: string; id: string }) => void;
}

/** Process-map canvas. Entities are predefined in the Data tables; drag them
 *  from the left-rail tree onto the canvas to place them, then drag handle→
 *  handle to connect. Right-click a node to remove it from the map. */
export function FlowCanvas({ workbook, onChange, onSelect }: Props) {
  const { nodes, edges } = useMemo(() => workbookToGraph(workbook), [workbook]);
  const [menu, setMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null);
  const rf = useRef<ReactFlowInstance | null>(null);
  const wrap = useRef<HTMLDivElement | null>(null);

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

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const dragId = e.dataTransfer.getData(DRAG_MIME);
      if (!dragId) return;
      const pos = rf.current?.screenToFlowPosition
        ? rf.current.screenToFlowPosition({ x: e.clientX, y: e.clientY })
        : { x: e.clientX - 260, y: e.clientY - 120 };
      onChange(placeEntity(workbook, dragId, pos.x, pos.y));
    },
    [workbook, onChange],
  );

  return (
    <div className="view-full" onClick={() => menu && setMenu(null)}>
      <div className="toolbar">
        <span className="muted">
          drag a component from the tree onto the canvas to place it; drag handle→handle to connect
          (stream→facility = input, facility→stream = output, market→stream = supply)
        </span>
      </div>
      <div
        className="canvas"
        ref={wrap}
        onDragOver={(e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
        }}
        onDrop={onDrop}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onInit={(inst) => (rf.current = inst)}
          onNodesChange={onNodesChange}
          onConnect={onConnect}
          onNodeContextMenu={(e, node) => {
            e.preventDefault();
            setMenu({ x: e.clientX, y: e.clientY, nodeId: node.id });
          }}
          onNodeClick={(_e, node) => {
            const kind = (node.data as { kind?: NodeKind }).kind;
            const entityId = (node.data as { entityId?: string }).entityId;
            const map = kind ? SHEET_OF[kind] : undefined;
            if (map && entityId) onSelect?.({ ...map, id: entityId });
          }}
          fitView
        >
          <Background />
          <Controls />
        </ReactFlow>
        {menu && (
          <div className="context-menu" style={{ left: menu.x, top: menu.y }}>
            <button
              onClick={() => {
                onChange(unplace(workbook, menu.nodeId));
                setMenu(null);
              }}
            >
              Remove from map
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
