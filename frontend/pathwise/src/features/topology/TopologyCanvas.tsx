import { useEffect, useMemo, useRef, useState } from "react";
import {
  DRAG_MIME,
  addFacilityWithTech,
  clearLayout,
  deleteChain,
  deleteEntity,
  persistLayout,
  placeEntity,
  unplace,
  workbookToGraph,
  type GraphNode,
  type NodeKind,
} from "../../lib/graph";
import type { RunResult, Selection, Workbook } from "../../types";

const NODE_W = 172;
const NODE_H = 56;

const SHEET_OF: Record<NodeKind, { sheet: string; idCol: string }> = {
  process: { sheet: "processes", idCol: "process_id" },
  commodity: { sheet: "commodities", idCol: "commodity_id" },
  market: { sheet: "markets", idCol: "market_id" },
  storage: { sheet: "storage", idCol: "storage_id" },
};

interface Props {
  workbook: Workbook;
  /** Editable canvas: nodes drag (positions persist), tree items drop, nodes
   *  can be removed from the map. Read-only when false (analytics map). */
  editable?: boolean;
  /** Read-only mode: the solved run + year to display active technologies. */
  result?: RunResult | null;
  year?: number;
  onSelect?: (sel: Selection) => void;
  onChange?: (wb: Workbook) => void;
  onDropLibrary?: (key: string, x: number, y: number) => void;
  /** A technology dragged onto the canvas — the host decides Initial vs Transition. */
  onDropTech?: (techId: string, x: number, y: number) => void;
  /** Right-click shortcuts: add a transition option / a measure. */
  onAddTransition?: (processId: string) => void;
  onAddMeasure?: (kind: NodeKind, entityId: string) => void;
  /** Link an existing named MACC set to this facility (undefined → hidden). */
  onApplySet?: (processId: string) => void;
}

interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** The process-map canvas — hand-rolled SVG (no graph library): layered
 *  auto-layout from lib/graph, wheel zoom, background pan, node drag, click to
 *  select, drop-to-place. Left dot = input, right dot = output; in read-only
 *  mode each facility shows the technology it runs in the selected year. */
export function TopologyCanvas({
  workbook,
  editable = false,
  result,
  year,
  onSelect,
  onChange,
  onDropLibrary,
  onDropTech,
  onAddTransition,
  onAddMeasure,
  onApplySet,
}: Props) {
  const { nodes: baseNodes, edges } = useMemo(() => workbookToGraph(workbook), [workbook]);

  // Positions overlay (live during a drag; committed to node_layout on drop).
  const [override, setOverride] = useState<Map<string, { x: number; y: number }>>(new Map());
  useEffect(() => setOverride(new Map()), [workbook]);
  const nodes: GraphNode[] = baseNodes.map((nd) =>
    override.has(nd.id) ? { ...nd, position: override.get(nd.id)! } : nd,
  );
  const posOf = new Map(nodes.map((nd) => [nd.id, nd.position]));

  // Active technology per facility in the selected year (read-only mode); a
  // tech counts as operating only with real throughput.
  const active = useMemo(() => {
    const map = new Map<string, string>();
    if (result && year != null)
      for (const t of result.outputs.throughput)
        if (t.period === year && t.value > 1) map.set(t.process, t.technology);
    return map;
  }, [result, year]);
  const marketBuys = useMemo(() => {
    const map = new Map<string, number>();
    if (result && year != null)
      for (const m of result.outputs.markets) {
        const buy = m.by_period.find((b) => b.period === year)?.buy ?? 0;
        if (buy > 1) map.set(m.market, buy);
      }
    return map;
  }, [result, year]);

  // Viewport: fit the node bbox on model change; wheel zoom; background pan.
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [vb, setVb] = useState<ViewBox>({ x: 0, y: 0, w: 1200, h: 700 });
  const fitKey = baseNodes.map((nd) => nd.id).join("|");
  useEffect(() => {
    if (!baseNodes.length) return;
    const xs = baseNodes.map((nd) => nd.position.x);
    const ys = baseNodes.map((nd) => nd.position.y);
    const pad = 60;
    const x = Math.min(...xs) - pad;
    const y = Math.min(...ys) - pad;
    const w = Math.max(...xs) + NODE_W - x + pad;
    const h = Math.max(...ys) + NODE_H - y + pad;
    setVb({ x, y, w: Math.max(w, 600), h: Math.max(h, 400) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey]);

  const toWorld = (clientX: number, clientY: number) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || rect.width < 1 || rect.height < 1) return { x: vb.x, y: vb.y };
    return {
      x: vb.x + ((clientX - rect.left) / rect.width) * vb.w,
      y: vb.y + ((clientY - rect.top) / rect.height) * vb.h,
    };
  };

  const onWheel = (e: React.WheelEvent) => {
    const at = toWorld(e.clientX, e.clientY);
    const k = e.deltaY > 0 ? 1.12 : 1 / 1.12;
    setVb((v) => ({
      x: at.x - (at.x - v.x) * k,
      y: at.y - (at.y - v.y) * k,
      w: v.w * k,
      h: v.h * k,
    }));
  };

  // One pointer interaction at a time: either panning or dragging a node.
  const gesture = useRef<
    | { kind: "pan"; startX: number; startY: number; vb: ViewBox }
    | { kind: "node"; id: string; dx: number; dy: number; moved: boolean; startX: number; startY: number }
    | null
  >(null);
  // Below this screen-pixel displacement a node press is treated as a click
  // (select), not a drag — so tiny jitter doesn't swallow the selection.
  const DRAG_THRESHOLD_PX = 3;
  const [menu, setMenu] = useState<{ x: number; y: number; nodeId?: string } | null>(null);

  const capture = (el: Element | null, pointerId: number) => {
    try {
      el?.setPointerCapture(pointerId);
    } catch {
      /* synthetic events carry no active pointer — capture is best-effort */
    }
  };
  const onPointerDown = (e: React.PointerEvent) => {
    capture(e.currentTarget as Element, e.pointerId);
    gesture.current = { kind: "pan", startX: e.clientX, startY: e.clientY, vb };
    setMenu(null);
  };
  const startNodeDrag = (e: React.PointerEvent, id: string) => {
    e.stopPropagation();
    // Always record the press so a no-move release selects the node (handled in
    // onPointerUp — the DOM `click` is unreliable once the pointer is captured).
    // Capture + actual dragging only happen in editable mode.
    const at = toWorld(e.clientX, e.clientY);
    const pos = posOf.get(id);
    gesture.current = {
      kind: "node",
      id,
      dx: pos ? at.x - pos.x : 0,
      dy: pos ? at.y - pos.y : 0,
      moved: false,
      startX: e.clientX,
      startY: e.clientY,
    };
    if (editable) capture(svgRef.current as unknown as Element, e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const g = gesture.current;
    if (!g) return;
    if (g.kind === "pan") {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect || rect.width < 1 || rect.height < 1) return;
      const sx = (g.startX - e.clientX) * (vb.w / rect.width);
      const sy = (g.startY - e.clientY) * (vb.h / rect.height);
      setVb({ ...g.vb, x: g.vb.x + sx, y: g.vb.y + sy });
    } else {
      // Only drag in editable mode, and only once past the click threshold.
      if (!editable) return;
      if (Math.hypot(e.clientX - g.startX, e.clientY - g.startY) < DRAG_THRESHOLD_PX) return;
      const at = toWorld(e.clientX, e.clientY);
      g.moved = true;
      setOverride((prev) => new Map(prev).set(g.id, { x: at.x - g.dx, y: at.y - g.dy }));
    }
  };
  const onPointerUp = () => {
    const g = gesture.current;
    gesture.current = null;
    if (g?.kind !== "node") return;
    if (g.moved) {
      if (onChange) onChange(persistLayout(workbook, nodes));
    } else {
      // A press with no real movement is a click → select the node.
      const nd = nodes.find((n) => n.id === g.id);
      if (nd) click(nd);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const dragId = e.dataTransfer.getData(DRAG_MIME);
    if (!dragId || !editable || !onChange) return;
    const at = toWorld(e.clientX, e.clientY);
    if (dragId.startsWith("libfac:")) onDropLibrary?.(dragId.slice(7), at.x, at.y);
    else if (dragId.startsWith("tech:")) {
      const tech = dragId.slice(5);
      if (onDropTech) onDropTech(tech, at.x, at.y);
      else onChange(addFacilityWithTech(workbook, tech, at.x, at.y));
    } else onChange(placeEntity(workbook, dragId, at.x, at.y));
  };

  const click = (nd: GraphNode) => {
    const map = SHEET_OF[nd.data.kind];
    onSelect?.({ ...map, id: nd.data.entityId });
  };

  const edgePath = (a: { x: number; y: number }, b: { x: number; y: number }) => {
    const x1 = a.x + NODE_W;
    const y1 = a.y + NODE_H / 2;
    const x2 = b.x;
    const y2 = b.y + NODE_H / 2;
    const c = Math.max(40, (x2 - x1) / 2);
    return `M${x1},${y1} C${x1 + c},${y1} ${x2 - c},${y2} ${x2},${y2}`;
  };

  return (
    <div className="canvas topo-canvas" onClick={() => menu && setMenu(null)}>
      <svg
        ref={svgRef}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onDragOver={(e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
        }}
        onDrop={onDrop}
        onContextMenu={(e) => {
          if (!editable) return;
          e.preventDefault();
          setMenu({ x: e.clientX, y: e.clientY });
        }}
        role="img"
        aria-label="process map"
      >
        <defs>
          <marker id="topo-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="#0f766e" />
          </marker>
        </defs>
        {edges.map((ed) => {
          const a = posOf.get(ed.source);
          const b = posOf.get(ed.target);
          if (!a || !b) return null;
          const buy = marketBuys.get(ed.source.split(":")[1] ?? "");
          const label = buy != null ? buy.toFixed(0) : ed.label;
          return (
            <g key={ed.id} className="topo-edge">
              <path d={edgePath(a, b)} fill="none" stroke="#0f766e" strokeWidth={1.4} markerEnd="url(#topo-arrow)" opacity={0.75} />
              {label && (
                <text x={(a.x + NODE_W + b.x) / 2} y={(a.y + b.y) / 2 + NODE_H / 2 - 6} fontSize="10" fill="#64748b" textAnchor="middle">
                  {label}
                </text>
              )}
            </g>
          );
        })}
        {nodes.map((nd) => {
          const tech = active.get(nd.data.entityId);
          const dim = result != null && nd.data.kind === "process" && !tech;
          return (
            <g
              key={nd.id}
              className={`topo-node topo-${nd.data.kind}${dim ? " is-dim" : ""}`}
              transform={`translate(${nd.position.x},${nd.position.y})`}
              onPointerDown={(e) => startNodeDrag(e, nd.id)}
              onContextMenu={(e) => {
                if (!editable) return;
                e.preventDefault();
                e.stopPropagation();
                setMenu({ x: e.clientX, y: e.clientY, nodeId: nd.id });
              }}
            >
              <rect width={NODE_W} height={NODE_H} rx={2} />
              <text className="topo-kind" x={8} y={14}>
                {nd.data.kind}
              </text>
              <text className="topo-label" x={8} y={31}>
                {nd.data.label.length > 22 ? `${nd.data.label.slice(0, 21)}…` : nd.data.label}
              </text>
              <text className="topo-sub" x={8} y={46}>
                {result != null && nd.data.kind === "process"
                  ? tech
                    ? `▶ ${tech}`
                    : "idle"
                  : (nd.data.sub ?? "")}
              </text>
              {/* left dot = input, right dot = output */}
              <circle className="topo-in" cx={0} cy={NODE_H / 2} r={4.5} />
              <circle className="topo-out" cx={NODE_W} cy={NODE_H / 2} r={4.5} />
            </g>
          );
        })}
      </svg>
      {menu && onChange && (
        <div className="context-menu" style={{ left: menu.x, top: menu.y }}>
          {menu.nodeId ? (
            <>
              <button
                onClick={() => {
                  onChange(unplace(workbook, menu.nodeId!));
                  setMenu(null);
                }}
              >
                Remove from map (keep data)
              </button>
              <button
                className="danger"
                onClick={() => {
                  onChange(deleteEntity(workbook, menu.nodeId!));
                  setMenu(null);
                }}
              >
                Delete from model
              </button>
              {menu.nodeId.startsWith("process:") && onAddTransition && (
                <button
                  onClick={() => {
                    onAddTransition(menu.nodeId!.slice("process:".length));
                    setMenu(null);
                  }}
                >
                  Add transition technology…
                </button>
              )}
              {(menu.nodeId.startsWith("process:") || menu.nodeId.startsWith("commodity:")) &&
                onAddMeasure && (
                  <button
                    onClick={() => {
                      const i = menu.nodeId!.indexOf(":");
                      onAddMeasure(
                        menu.nodeId!.slice(0, i) as NodeKind,
                        menu.nodeId!.slice(i + 1),
                      );
                      setMenu(null);
                    }}
                  >
                    Add measure…
                  </button>
                )}
              {menu.nodeId.startsWith("process:") && onApplySet && (
                <button
                  onClick={() => {
                    onApplySet(menu.nodeId!.slice("process:".length));
                    setMenu(null);
                  }}
                >
                  Apply MACC set…
                </button>
              )}
              {menu.nodeId.startsWith("process:") && (
                <button
                  className="danger"
                  onClick={() => {
                    onChange(deleteChain(workbook, menu.nodeId!.slice("process:".length)));
                    setMenu(null);
                  }}
                >
                  Delete connected chain
                </button>
              )}
            </>
          ) : (
            <button
              onClick={() => {
                onChange(clearLayout(workbook));
                setMenu(null);
              }}
            >
              Clear map (reset all positions)
            </button>
          )}
        </div>
      )}
    </div>
  );
}
