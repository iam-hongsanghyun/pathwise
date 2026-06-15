// GroupCanvas — renders ONE level of the recursive group hierarchy as an SVG
// canvas. Reuses the visual conventions (CSS classes, bezier arrows, dot ports,
// drag-vs-click gesture) from TopologyCanvas.

import { useEffect, useMemo, useRef } from "react";
import {
  columnLayout,
  levelGraph,
  type GroupNode,
} from "../../lib/groupGraph";
import type { Workbook } from "../../types";
import { useViewBox } from "./useViewBox";

// ── Node box dimensions (match TopologyCanvas constants) ─────────────────────
const NODE_W = 172;
const NODE_H = 56;

// ── Click vs drag threshold (screen pixels) — mirrors TopologyCanvas ─────────
const DRAG_THRESHOLD_PX = 3;

interface Props {
  wb: Workbook;
  groupId: string | null;
  onDrill: (childId: string) => void;
  onSelect?: (id: string) => void;
}

/** Draw a cubic bezier from the right-middle of box A to the left-middle of
 *  box B (identical to TopologyCanvas.edgePath). */
function edgePath(
  a: { x: number; y: number },
  b: { x: number; y: number },
): string {
  const x1 = a.x + NODE_W;
  const y1 = a.y + NODE_H / 2;
  const x2 = b.x;
  const y2 = b.y + NODE_H / 2;
  const c = Math.max(40, (x2 - x1) / 2);
  return `M${x1},${y1} C${x1 + c},${y1} ${x2 - c},${y2} ${x2},${y2}`;
}

/** GroupCanvas renders one hierarchical level as a hand-rolled SVG canvas.
 *
 *  - Clicking a **group** node drills into it via `onDrill`.
 *  - Clicking a **machine** (leaf) node fires `onSelect`.
 *  - Mouse wheel zooms visually (center-preserving); it never changes level.
 *  - Background pointer drag pans the canvas.
 *  - A friendly empty state is shown when there are no children at this level.
 */
export function GroupCanvas({ wb, groupId, onDrill, onSelect }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const { vb, onWheel, onPanStart, onPanMove, onPanEnd, toWorld, fit } =
    useViewBox();

  const { children, edges } = useMemo(
    () => levelGraph(wb, groupId),
    [wb, groupId],
  );

  const posMap = useMemo(
    () => columnLayout(children.map((c) => c.id), edges),
    [children, edges],
  );

  // Fit the view whenever the level changes.
  const fitKey = children.map((c) => c.id).join("|");
  useEffect(() => {
    const positions = [...posMap.values()];
    if (positions.length > 0) fit(positions, NODE_W, NODE_H);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey]);

  // Per-node gesture tracking: we need one slot because only one node can be
  // pressed at a time. Null = no press in flight.
  const nodeGesture = useRef<{
    id: string;
    kind: "group" | "machine";
    startX: number;
    startY: number;
    moved: boolean;
  } | null>(null);

  // Whether a background pan is in progress — suppresses node click if the
  // pointer was pressed on the background and then released on a node.
  const panActive = useRef(false);

  const handleBgPointerDown = (e: React.PointerEvent) => {
    panActive.current = false;
    nodeGesture.current = null;
    onPanStart(e);
  };

  const handleBgPointerMove = (e: React.PointerEvent) => {
    const g = nodeGesture.current;
    if (g) {
      // Track whether the node pointer has moved past the drag threshold.
      if (
        !g.moved &&
        Math.hypot(e.clientX - g.startX, e.clientY - g.startY) >=
          DRAG_THRESHOLD_PX
      ) {
        g.moved = true;
      }
      return; // Don't pan while a node is held.
    }
    panActive.current = true;
    onPanMove(e);
  };

  const handleBgPointerUp = () => {
    nodeGesture.current = null;
    panActive.current = false;
    onPanEnd();
  };

  const handleNodePointerDown = (
    e: React.PointerEvent,
    nd: GroupNode,
  ) => {
    e.stopPropagation(); // Don't trigger background pan.
    nodeGesture.current = {
      id: nd.id,
      kind: nd.kind,
      startX: e.clientX,
      startY: e.clientY,
      moved: false,
    };
  };

  const handleNodePointerUp = (e: React.PointerEvent, nd: GroupNode) => {
    e.stopPropagation();
    const g = nodeGesture.current;
    if (!g || g.id !== nd.id || g.moved) {
      nodeGesture.current = null;
      return;
    }
    nodeGesture.current = null;
    // A press with no real movement → click.
    if (nd.kind === "group") {
      onDrill(nd.id);
    } else {
      onSelect?.(nd.id);
    }
  };

  // Prevent the SVG's wheel from scrolling the page.
  const handleWheel = (e: React.WheelEvent) => {
    e.stopPropagation();
    onWheel(e);
  };

  if (children.length === 0) {
    return (
      <div className="canvas topo-canvas" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
        <p className="muted" style={{ fontSize: "0.9rem" }}>
          No children at this level.
        </p>
      </div>
    );
  }

  // Compute edge label midpoint (world space) for the commodity stream box.
  const edgeLabelPos = (
    a: { x: number; y: number },
    b: { x: number; y: number },
  ) => ({
    x: (a.x + NODE_W + b.x) / 2,
    y: (a.y + b.y) / 2 + NODE_H / 2 - 6,
  });

  // Build a lookup for quick position access.
  const posOf = (id: string) => posMap.get(id);

  // Derive a display label for toWorld (used for tooltip future work; keep ref).
  void toWorld;

  return (
    <div className="canvas topo-canvas">
      <svg
        ref={svgRef}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        onWheel={handleWheel}
        onPointerDown={handleBgPointerDown}
        onPointerMove={handleBgPointerMove}
        onPointerUp={handleBgPointerUp}
        role="img"
        aria-label="group topology"
      >
        <defs>
          {/* Reuse same arrow marker id as TopologyCanvas when both are mounted
              — they share the same SVG defs namespace within a document, so
              we use a distinct id to avoid conflicts. */}
          <marker
            id="group-arrow"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="7"
            markerHeight="7"
            orient="auto"
          >
            <path d="M0,0 L8,4 L0,8 z" fill="#0f766e" />
          </marker>
        </defs>

        {/* Edges (drawn below nodes) */}
        {edges.map((ed) => {
          const a = posOf(ed.from);
          const b = posOf(ed.to);
          if (!a || !b) return null;
          const lp = edgeLabelPos(a, b);
          return (
            <g key={`${ed.from}->${ed.to}:${ed.commodity}`} className="topo-edge">
              <path
                d={edgePath(a, b)}
                fill="none"
                stroke="#0f766e"
                strokeWidth={1.4}
                markerEnd="url(#group-arrow)"
                opacity={0.75}
              />
              {/* Commodity stream label — a small box mimicking a "stream box". */}
              <rect
                x={lp.x - 28}
                y={lp.y - 10}
                width={56}
                height={14}
                rx={2}
                fill="var(--surface, #fff)"
                stroke="var(--border, #cbd5e1)"
                strokeWidth={0.8}
                opacity={0.9}
              />
              <text
                x={lp.x}
                y={lp.y}
                fontSize={9}
                fill="var(--muted, #64748b)"
                textAnchor="middle"
                dominantBaseline="middle"
              >
                {ed.commodity.length > 10
                  ? `${ed.commodity.slice(0, 9)}…`
                  : ed.commodity}
              </text>
              {ed.lag > 0 && (
                <text
                  x={lp.x}
                  y={lp.y + 12}
                  fontSize={8}
                  fill="var(--muted, #94a3b8)"
                  textAnchor="middle"
                >
                  {`lag ${ed.lag}y`}
                </text>
              )}
            </g>
          );
        })}

        {/* Nodes */}
        {children.map((nd) => {
          const pos = posOf(nd.id);
          if (!pos) return null;
          const isGroup = nd.kind === "group";
          return (
            <g
              key={nd.id}
              className={`topo-node ${isGroup ? "topo-process" : "topo-commodity"}`}
              transform={`translate(${pos.x},${pos.y})`}
              onPointerDown={(e) => handleNodePointerDown(e, nd)}
              onPointerUp={(e) => handleNodePointerUp(e, nd)}
              style={{ cursor: isGroup ? "zoom-in" : "pointer" }}
            >
              <rect width={NODE_W} height={NODE_H} rx={2} />
              <text className="topo-kind" x={8} y={14}>
                {isGroup ? "group" : "machine"}
              </text>
              <text className="topo-label" x={8} y={31}>
                {nd.label.length > 22
                  ? `${nd.label.slice(0, 21)}…`
                  : nd.label}
              </text>
              <text className="topo-sub" x={8} y={46}>
                {nd.level || nd.id}
              </text>
              {/* Left dot = input port, right dot = output port */}
              <circle className="topo-in" cx={0} cy={NODE_H / 2} r={4.5} />
              <circle className="topo-out" cx={NODE_W} cy={NODE_H / 2} r={4.5} />
              {/* Drill-in indicator for groups */}
              {isGroup && (
                <text
                  x={NODE_W - 8}
                  y={14}
                  fontSize={9}
                  fill="var(--brand, #0f766e)"
                  textAnchor="end"
                >
                  ▸
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
