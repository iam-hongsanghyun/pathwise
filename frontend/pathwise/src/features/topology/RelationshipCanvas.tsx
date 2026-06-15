// RelationshipCanvas — the editable per-level "how do these children connect"
// view shown in the Value-Chain main panel. Renders the selected group's
// children + their stream-flow edges + market source/sink lanes; lets the user
// draw a connection by dragging from a child's output port to another's input
// port, select/delete an edge, and click a child to select it (drill via the
// tree). Reuses useViewBox + columnLayout + the .topo-* visual language.

import { useEffect, useMemo, useRef, useState } from "react";
import { SearchableSelect } from "../controls/SearchableSelect";
import { childrenOf, columnLayout, levelConnections, parseNodes, type GroupEdge } from "../../lib/groupGraph";
import type { Workbook } from "../../types";
import { useViewBox } from "./useViewBox";

const NODE_W = 172;
const NODE_H = 56;
const DRAG_PX = 3;

export interface ExternalStream {
  childId: string;
  commodity: string;
}

interface Props {
  wb: Workbook;
  groupId: string | null;
  selectedChildId: string | null;
  onSelectChild: (id: string) => void;
  onAddConnection: (from: string, to: string, commodity: string, lag: number) => void;
  onDeleteConnection: (rowIndex: number) => void;
  commodities: string[];
  /** Streams a child purchases (market → child). */
  externalIn: ExternalStream[];
  /** Streams a child sells (child → market). */
  externalOut: ExternalStream[];
}

function edgePath(a: { x: number; y: number }, b: { x: number; y: number }): string {
  const x1 = a.x + NODE_W;
  const y1 = a.y + NODE_H / 2;
  const x2 = b.x;
  const y2 = b.y + NODE_H / 2;
  const c = Math.max(40, (x2 - x1) / 2);
  return `M${x1},${y1} C${x1 + c},${y1} ${x2 - c},${y2} ${x2},${y2}`;
}

export function RelationshipCanvas({
  wb,
  groupId,
  selectedChildId,
  onSelectChild,
  onAddConnection,
  onDeleteConnection,
  commodities,
  externalIn,
  externalOut,
}: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const { vb, onWheel, onPanStart, onPanMove, onPanEnd, toWorld, fit } = useViewBox();

  const nodes = useMemo(() => parseNodes(wb), [wb]);
  const children = useMemo(() => childrenOf(nodes, groupId), [nodes, groupId]);
  const labelOf = useMemo(() => new Map(children.map((c) => [c.id, c.label])), [children]);
  const conns = useMemo(() => levelConnections(wb, groupId), [wb, groupId]);
  const edgesForLayout = useMemo<GroupEdge[]>(
    () => conns.map((c) => ({ from: c.from, to: c.to, commodity: c.commodity, lag: c.lag })),
    [conns],
  );
  const posMap = useMemo(() => columnLayout(children.map((c) => c.id), edgesForLayout), [children, edgesForLayout]);

  // Market lanes: source nodes left of the children, sink nodes to the right.
  const xs = [...posMap.values()].map((p) => p.x);
  const minX = xs.length ? Math.min(...xs) : 40;
  const maxX = xs.length ? Math.max(...xs) : 40;
  const inPos = new Map<string, { x: number; y: number; commodity: string; childId: string }>();
  externalIn.forEach((e, i) => {
    inPos.set(`in:${e.commodity}:${e.childId}`, { x: minX - 230, y: 40 + i * 70, commodity: e.commodity, childId: e.childId });
  });
  const outPos = new Map<string, { x: number; y: number; commodity: string; childId: string }>();
  externalOut.forEach((e, i) => {
    outPos.set(`out:${e.commodity}:${e.childId}`, { x: maxX + 230, y: 40 + i * 70, commodity: e.commodity, childId: e.childId });
  });

  const fitKey = children.map((c) => c.id).join("|") + `|${externalIn.length}|${externalOut.length}`;
  useEffect(() => {
    const all = [...posMap.values(), ...inPos.values(), ...outPos.values()];
    if (all.length) fit(all, NODE_W, NODE_H);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey]);

  const nodeGesture = useRef<{ id: string; x: number; y: number; moved: boolean } | null>(null);
  const [connect, setConnect] = useState<{ from: string; toWorldX: number; toWorldY: number } | null>(null);
  const [form, setForm] = useState<{ from: string; to: string; sx: number; sy: number } | null>(null);
  const [selEdge, setSelEdge] = useState<number | null>(null);

  const posOf = (id: string) => posMap.get(id);

  function bgDown(e: React.PointerEvent) {
    nodeGesture.current = null;
    onPanStart(e);
  }
  function bgMove(e: React.PointerEvent) {
    if (connect) {
      const w = toWorld(e.clientX, e.clientY, svgRef.current);
      setConnect({ ...connect, toWorldX: w.x, toWorldY: w.y });
      return;
    }
    const g = nodeGesture.current;
    if (g) {
      if (!g.moved && Math.hypot(e.clientX - g.x, e.clientY - g.y) >= DRAG_PX) g.moved = true;
      return;
    }
    onPanMove(e);
  }
  function bgUp() {
    nodeGesture.current = null;
    setConnect(null);
    onPanEnd();
  }

  return (
    <div className="canvas topo-canvas" style={{ position: "relative" }}>
      {children.length === 0 ? (
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <p className="muted">Empty — right-click in the tree to add a subgroup or component here.</p>
        </div>
      ) : (
        <svg
          ref={svgRef}
          viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
          onWheel={(e) => { e.stopPropagation(); onWheel(e); }}
          onPointerDown={bgDown}
          onPointerMove={bgMove}
          onPointerUp={bgUp}
          role="img"
          aria-label="relationship canvas"
        >
          <defs>
            <marker id="rc-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0,0 L8,4 L0,8 z" fill="#0f766e" />
            </marker>
          </defs>

          {/* child→child edges */}
          {conns.map((ed) => {
            const a = posOf(ed.from);
            const b = posOf(ed.to);
            if (!a || !b) return null;
            const mid = { x: (a.x + NODE_W + b.x) / 2, y: (a.y + b.y) / 2 + NODE_H / 2 - 6 };
            const sel = selEdge === ed.rowIndex;
            return (
              <g key={`${ed.rowIndex}`} className="topo-edge" style={{ cursor: "pointer" }}>
                <path d={edgePath(a, b)} fill="none" stroke={sel ? "#0b5d56" : "#0f766e"} strokeWidth={sel ? 2.4 : 1.4} markerEnd="url(#rc-arrow)" opacity={0.8} />
                {/* fat invisible hit area */}
                <path d={edgePath(a, b)} fill="none" stroke="transparent" strokeWidth={12} onClick={() => setSelEdge(sel ? null : ed.rowIndex)} />
                <rect x={mid.x - 30} y={mid.y - 10} width={60} height={15} rx={2} fill="var(--surface)" stroke="var(--border)" strokeWidth={0.8} opacity={0.95} onClick={() => setSelEdge(sel ? null : ed.rowIndex)} />
                <text x={mid.x} y={mid.y - 1} fontSize={9} fill="var(--muted)" textAnchor="middle" dominantBaseline="middle" style={{ pointerEvents: "none" }}>
                  {ed.commodity.length > 11 ? `${ed.commodity.slice(0, 10)}…` : ed.commodity}{ed.lag ? ` ·${ed.lag}y` : ""}
                </text>
                {sel && (
                  <g onClick={() => { onDeleteConnection(ed.rowIndex); setSelEdge(null); }} style={{ cursor: "pointer" }}>
                    <circle cx={mid.x + 38} cy={mid.y - 2} r={8} fill="var(--danger)" />
                    <text x={mid.x + 38} y={mid.y - 1} fontSize={10} fill="#fff" textAnchor="middle" dominantBaseline="middle">✕</text>
                  </g>
                )}
              </g>
            );
          })}

          {/* market source lanes (purchase) */}
          {[...inPos.values()].map((mk) => {
            const c = posOf(mk.childId);
            if (!c) return null;
            return (
              <g key={`in-${mk.commodity}-${mk.childId}`}>
                <path d={edgePath({ x: mk.x, y: mk.y }, c)} fill="none" stroke="var(--warn)" strokeWidth={1.2} markerEnd="url(#rc-arrow)" opacity={0.7} strokeDasharray="4 3" />
                <rect x={mk.x} y={mk.y} width={120} height={NODE_H} rx={3} fill="#fffbeb" stroke="var(--warn)" strokeWidth={1} />
                <text x={mk.x + 10} y={mk.y + 20} fontSize={10} fill="var(--warn-text)">buy ▸ market</text>
                <text x={mk.x + 10} y={mk.y + 38} fontSize={11} fill="var(--text)">{mk.commodity}</text>
              </g>
            );
          })}
          {/* market sink lanes (sell) */}
          {[...outPos.values()].map((mk) => {
            const c = posOf(mk.childId);
            if (!c) return null;
            return (
              <g key={`out-${mk.commodity}-${mk.childId}`}>
                <path d={edgePath(c, { x: mk.x, y: mk.y })} fill="none" stroke="var(--warn)" strokeWidth={1.2} markerEnd="url(#rc-arrow)" opacity={0.7} strokeDasharray="4 3" />
                <rect x={mk.x} y={mk.y} width={120} height={NODE_H} rx={3} fill="#fffbeb" stroke="var(--warn)" strokeWidth={1} />
                <text x={mk.x + 10} y={mk.y + 20} fontSize={10} fill="var(--warn-text)">sell ▸ market</text>
                <text x={mk.x + 10} y={mk.y + 38} fontSize={11} fill="var(--text)">{mk.commodity}</text>
              </g>
            );
          })}

          {/* rubber-band while connecting */}
          {connect && (() => {
            const a = posOf(connect.from);
            if (!a) return null;
            return <path d={edgePath(a, { x: connect.toWorldX - NODE_W, y: connect.toWorldY - NODE_H / 2 })} fill="none" stroke="#0f766e" strokeWidth={1.5} strokeDasharray="5 4" opacity={0.7} />;
          })()}

          {/* child nodes */}
          {children.map((nd) => {
            const pos = posOf(nd.id);
            if (!pos) return null;
            const isGroup = nd.kind === "group";
            const isSel = nd.id === selectedChildId;
            return (
              <g
                key={nd.id}
                className={`topo-node ${isGroup ? "topo-process" : "topo-commodity"}`}
                transform={`translate(${pos.x},${pos.y})`}
                onPointerDown={(e) => { e.stopPropagation(); nodeGesture.current = { id: nd.id, x: e.clientX, y: e.clientY, moved: false }; }}
                onPointerUp={(e) => {
                  e.stopPropagation();
                  const g = nodeGesture.current;
                  nodeGesture.current = null;
                  if (connect) return; // handled by in-port
                  if (g && g.id === nd.id && !g.moved) onSelectChild(nd.id);
                }}
                style={{ cursor: "pointer" }}
              >
                <rect width={NODE_W} height={NODE_H} rx={2} stroke={isSel ? "var(--brand)" : undefined} strokeWidth={isSel ? 2 : undefined} />
                <text className="topo-kind" x={8} y={14}>{isGroup ? "group" : "machine"}</text>
                <text className="topo-label" x={8} y={31}>{nd.label.length > 22 ? `${nd.label.slice(0, 21)}…` : nd.label}</text>
                <text className="topo-sub" x={8} y={46}>{nd.level || nd.id}</text>
                {/* input port (left) — drop target while connecting */}
                <circle
                  className="topo-in"
                  cx={0}
                  cy={NODE_H / 2}
                  r={6}
                  style={{ cursor: "crosshair" }}
                  onPointerUp={(e) => {
                    e.stopPropagation();
                    if (connect && connect.from !== nd.id) {
                      setForm({ from: connect.from, to: nd.id, sx: e.clientX, sy: e.clientY });
                    }
                    setConnect(null);
                    nodeGesture.current = null;
                  }}
                />
                {/* output port (right) — drag start */}
                <circle
                  className="topo-out"
                  cx={NODE_W}
                  cy={NODE_H / 2}
                  r={6}
                  style={{ cursor: "crosshair" }}
                  onPointerDown={(e) => {
                    e.stopPropagation();
                    const w = toWorld(e.clientX, e.clientY, svgRef.current);
                    setConnect({ from: nd.id, toWorldX: w.x, toWorldY: w.y });
                  }}
                />
              </g>
            );
          })}
        </svg>
      )}

      {/* inline connect form */}
      {form && (
        <ConnectForm
          fromLabel={labelOf.get(form.from) ?? form.from}
          toLabel={labelOf.get(form.to) ?? form.to}
          commodities={commodities}
          x={form.sx}
          y={form.sy}
          onCancel={() => setForm(null)}
          onConfirm={(commodity, lag) => {
            onAddConnection(form.from, form.to, commodity, lag);
            setForm(null);
          }}
        />
      )}
    </div>
  );
}

function ConnectForm({
  fromLabel,
  toLabel,
  commodities,
  x,
  y,
  onConfirm,
  onCancel,
}: {
  fromLabel: string;
  toLabel: string;
  commodities: string[];
  x: number;
  y: number;
  onConfirm: (commodity: string, lag: number) => void;
  onCancel: () => void;
}) {
  const [commodity, setCommodity] = useState("");
  const [lag, setLag] = useState(0);
  return (
    <div
      style={{
        position: "fixed",
        left: Math.min(x, window.innerWidth - 280),
        top: Math.min(y, window.innerHeight - 160),
        zIndex: 1000,
        background: "var(--surface)",
        border: "1px solid var(--border-strong)",
        borderRadius: "var(--radius-button)",
        boxShadow: "0 6px 24px rgba(0,0,0,0.14)",
        padding: 10,
        width: 250,
        fontSize: "0.78rem",
      }}
    >
      <div style={{ marginBottom: 6 }}>
        <b>{fromLabel}</b> → <b>{toLabel}</b>
      </div>
      <div style={{ marginBottom: 6 }}>
        <SearchableSelect value={commodity} options={commodities} onChange={setCommodity} onCreate={setCommodity} placeholder="stream / commodity" />
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <span className="muted">lag (yr)</span>
        <input type="number" value={lag} onChange={(e) => setLag(Number(e.target.value) || 0)} style={{ width: 60, padding: "3px 6px", border: "1px solid var(--border-strong)", borderRadius: 4, font: "inherit" }} />
      </label>
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
        <button className="ghost" onClick={onCancel}>cancel</button>
        <button className="run-button" disabled={!commodity} onClick={() => onConfirm(commodity, lag)}>＋ link</button>
      </div>
    </div>
  );
}
