import { useCallback, useEffect, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  Position,
  useEdgesState,
  useNodesState,
  type Connection,
  type NodeProps,
  type ReactFlowInstance,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  DRAG_MIME,
  addFacilityWithTech,
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

/** Human-readable explanation shown on hover (native tooltip). */
function describe(data: NodeData): string {
  const p = data.ports;
  if (data.kind === "process" && p) {
    const ins = [...p.energyIn, ...p.materialIn];
    return [
      `Facility: ${data.label}`,
      data.sub ? `Technology: ${data.sub}` : "",
      ins.length ? `Inputs: ${ins.join(", ")}` : "",
      p.products.length ? `Products: ${p.products.join(", ")}` : "",
      p.energyOut.length ? `Residual energy: ${p.energyOut.join(", ")}` : "",
      p.byproducts.length ? `By-products: ${p.byproducts.join(", ")}` : "",
    ]
      .filter(Boolean)
      .join("\n");
  }
  const role = data.kind === "commodity" ? "Stream" : data.kind === "market" ? "Market" : "Storage";
  return `${role}: ${data.label}${data.sub ? ` (${data.sub})` : ""}`;
}

function NodeView({ data }: NodeProps<NodeData>) {
  const p: FacilityPorts | undefined = data.ports;
  // Keep the box minimal — name + main product only; full I/O is on hover.
  const mainProduct = p?.products[0] ?? p?.energyOut[0] ?? p?.byproducts[0];
  return (
    <div className={`node ${data.kind}`} title={describe(data)}>
      <Handle type="target" position={Position.Left} className="h-in" title="input (left)" />
      <div className="node-kind">{data.kind}</div>
      <strong>{data.label}</strong>
      {data.kind === "process"
        ? mainProduct && <div className="node-main">▸ {mainProduct}</div>
        : data.sub && <div className="muted">{data.sub}</div>}
      <Handle type="source" position={Position.Right} className="h-out" title="output (right)" />
    </div>
  );
}
const nodeTypes = { process: NodeView, commodity: NodeView, market: NodeView, storage: NodeView };

interface Props {
  workbook: Workbook;
  onChange: (wb: Workbook) => void;
  onSelect?: (sel: { sheet: string; idCol: string; id: string }) => void;
  /** A library facility template dropped on the canvas (`<sector>/<facility_id>`). */
  onDropLibrary?: (key: string, x: number, y: number) => void;
}

/** Process-map canvas. Entities are predefined in the Data tables; drag them
 *  from the left-rail tree onto the canvas to place them, then drag handle→
 *  handle to connect. Right-click a node to remove it from the map. */
export function FlowCanvas({ workbook, onChange, onSelect, onDropLibrary }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState<NodeData>([]);
  const [edges, setEdges] = useEdgesState([]);
  const [menu, setMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null);
  const rf = useRef<ReactFlowInstance | null>(null);
  const wrap = useRef<HTMLDivElement | null>(null);

  // The workbook is the source of truth: re-derive the graph when it changes.
  // Dragging mutates only the local node state (smooth); positions are written
  // back to the workbook on drag-stop, so a mid-drag round-trip can't blank the map.
  useEffect(() => {
    const g = workbookToGraph(workbook);
    setNodes(g.nodes);
    setEdges(g.edges);
  }, [workbook, setNodes, setEdges]);

  const onNodeDragStop = useCallback(() => {
    onChange(persistLayout(workbook, nodes as GraphNode[]));
  }, [workbook, nodes, onChange]);

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
      // A technology payload spawns a new facility running it; a library payload
      // instantiates a prebuilt template; otherwise the payload is an existing
      // entity being placed on the map.
      if (dragId.startsWith("libfac:")) {
        onDropLibrary?.(dragId.slice(7), pos.x, pos.y);
      } else if (dragId.startsWith("tech:")) {
        onChange(addFacilityWithTech(workbook, dragId.slice(5), pos.x, pos.y));
      } else {
        onChange(placeEntity(workbook, dragId, pos.x, pos.y));
      }
    },
    [workbook, onChange, onDropLibrary],
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
          onNodeDragStop={onNodeDragStop}
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
