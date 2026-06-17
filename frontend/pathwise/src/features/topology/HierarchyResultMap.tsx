// HierarchyResultMap — the read-only result process map that shows ALL levels of
// the node hierarchy (country → company → facility → machine) in ONE chart, with
// a year slider on top that scrubs the solved run: active technology, throughput
// and inter-node flows update per year. Three layouts share one renderer:
//   • nested      — recursive containers (the whole tree at once)
//   • swimlane    — one band per level + parent→child connectors
//   • expandable  — nested, but groups collapse/expand on click (drill-down)

import { useEffect, useMemo, useState } from "react";
import { buildOverlay, ResultYearBar, type YearOverlay } from "../valuechain/panels";
import { parseNodes, rootIds } from "../../lib/groupGraph";
import { layoutFor, type LaidEdge, type LaidNode, type MapMode } from "../../lib/hierarchyLayout";
import { useViewBox } from "./useViewBox";
import type { RunResult, Workbook } from "../../types";

const MODES: { id: MapMode; label: string }[] = [
  { id: "nested", label: "Nested" },
  { id: "swimlane", label: "Swimlanes" },
  { id: "expandable", label: "Expandable" },
];

function fmtVal(n: number): string {
  const a = Math.abs(n);
  if (a >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return `${Math.round(n)}`;
}

function clip(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

interface Props {
  workbook: Workbook;
  result: RunResult;
}

export function HierarchyResultMap({ workbook, result }: Props) {
  const [mode, setMode] = useState<MapMode>("nested");
  const overlayIdx = useMemo(() => buildOverlay(result), [result]);
  const [year, setYear] = useState<number>(() => overlayIdx.years[0] ?? 0);
  useEffect(() => {
    setYear((y) => (overlayIdx.years.includes(y) ? y : (overlayIdx.years[0] ?? 0)));
  }, [overlayIdx]);
  const overlay: YearOverlay | null = useMemo(
    () => (overlayIdx.years.length ? overlayIdx.at(year) : null),
    [overlayIdx, year],
  );

  // Expandable mode: which groups are open. Default = the roots (drill down).
  const roots = useMemo(() => rootIds(parseNodes(workbook)), [workbook]);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(roots));
  useEffect(() => setExpanded(new Set(roots)), [roots]);

  const laid = useMemo(
    () => layoutFor(workbook, mode, expanded),
    [workbook, mode, expanded],
  );
  const boxById = useMemo(() => new Map(laid.nodes.map((n) => [n.id, n])), [laid]);

  const { vb, setVb, onWheel, onPanStart, onPanMove, onPanEnd } = useViewBox();
  // Frame the whole layout whenever its extent changes.
  const fitKey = `${mode}|${laid.width}x${laid.height}|${laid.nodes.length}`;
  useEffect(() => {
    const pad = 50;
    setVb({ x: -pad, y: -pad, w: laid.width + 2 * pad, h: laid.height + 2 * pad });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey]);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const containers = laid.nodes
    .filter((n) => n.kind === "group" && !n.collapsed && mode !== "swimlane")
    .sort((a, b) => a.depth - b.depth);
  const leaves =
    mode === "swimlane"
      ? laid.nodes
      : laid.nodes.filter((n) => n.kind === "machine" || n.collapsed);

  return (
    <div className="canvas topo-canvas" style={{ display: "flex", flexDirection: "column" }}>
      {/* Top toolbar — row 1: layout toggle; row 2: full-width year slider */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "6px 12px",
          background: "var(--surface)",
        }}
      >
        <div style={{ display: "inline-flex", border: "1px solid var(--border-strong)", borderRadius: 6, overflow: "hidden" }}>
          {MODES.map((m) => (
            <button
              key={m.id}
              onClick={() => setMode(m.id)}
              className={mode === m.id ? "run-button" : "ghost"}
              style={{ borderRadius: 0, padding: "3px 12px", fontSize: "0.76rem", border: "none" }}
            >
              {m.label}
            </button>
          ))}
        </div>
        <span className="muted" style={{ fontSize: "0.74rem" }}>
          all levels in one chart
          {mode === "expandable" ? " · click a group to expand / collapse" : ""}
        </span>
      </div>
      {overlayIdx.years.length > 0 && (
        <ResultYearBar years={overlayIdx.years} year={year} onYear={setYear} />
      )}

      <svg
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        preserveAspectRatio="xMidYMin meet"
        onWheel={onWheel}
        onPointerDown={onPanStart}
        onPointerMove={onPanMove}
        onPointerUp={onPanEnd}
        role="img"
        aria-label="hierarchy result map"
        style={{ flex: 1, minHeight: 0 }}
      >
        <defs>
          <marker id="hr-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="#0f766e" />
          </marker>
        </defs>

        {/* swimlane: parent→child belonging connectors (drawn faint, behind) */}
        {mode === "swimlane" &&
          laid.nodes.map((n) => {
            if (!n.parentId) return null;
            const p = boxById.get(n.parentId);
            if (!p) return null;
            return (
              <line
                key={`pc-${n.id}`}
                x1={p.x + p.w / 2}
                y1={p.y + p.h}
                x2={n.x + n.w / 2}
                y2={n.y}
                stroke="var(--border-strong)"
                strokeWidth={1}
                opacity={0.5}
              />
            );
          })}

        {/* group containers (nested / expandable) */}
        {containers.map((g) => (
          <g key={`c-${g.id}`} onClick={() => mode === "expandable" && toggle(g.id)} style={{ cursor: mode === "expandable" ? "pointer" : "default" }}>
            <rect
              x={g.x}
              y={g.y}
              width={g.w}
              height={g.h}
              rx={6}
              fill="var(--surface)"
              stroke="var(--border-strong)"
              strokeWidth={1}
              opacity={0.5 + 0.12 * Math.min(3, g.depth)}
            />
            <text x={g.x + 10} y={g.y + 16} fontSize={11} fontWeight={600} fill="var(--text)">
              {clip(g.label, Math.max(8, Math.floor(g.w / 8)))}
            </text>
            <text x={g.x + g.w - 8} y={g.y + 16} fontSize={9} fill="var(--muted)" textAnchor="end">
              {g.level || "group"}
              {mode === "expandable" ? " ▾" : ""}
            </text>
          </g>
        ))}

        {/* flow edges (machine-level, valued per year) */}
        {laid.edges.map((e: LaidEdge) => {
          const a = boxById.get(e.from);
          const b = boxById.get(e.to);
          if (!a || !b) return null;
          const x1 = a.x + a.w;
          const y1 = a.y + a.h / 2;
          const x2 = b.x;
          const y2 = b.y + b.h / 2;
          const c = Math.max(40, (x2 - x1) / 2);
          const fv = overlay?.flow(e.origFrom, e.origTo, e.commodity);
          const active = fv != null && fv > 1e-6;
          const mx = (x1 + x2) / 2;
          const my = (y1 + y2) / 2;
          return (
            <g key={e.id} className="topo-edge">
              <path
                d={`M${x1},${y1} C${x1 + c},${y1} ${x2 - c},${y2} ${x2},${y2}`}
                fill="none"
                stroke="#0f766e"
                strokeWidth={active ? 2.2 : 1.3}
                markerEnd="url(#hr-arrow)"
                opacity={overlay && !active ? 0.28 : 0.75}
              />
              <text x={mx} y={my - 4} fontSize={9} fill={active ? "var(--text)" : "var(--muted)"} textAnchor="middle">
                {active ? `${clip(e.commodity, 8)} ${fmtVal(fv!)}` : clip(e.commodity, 10)}
              </text>
            </g>
          );
        })}

        {/* leaf boxes: machines (with per-year overlay) + collapsed groups */}
        {leaves.map((n: LaidNode) => {
          const isMachine = n.kind === "machine";
          const tech = isMachine ? overlay?.tech(n.id) : undefined;
          const toTech = isMachine ? overlay?.transitionedTo(n.id) : undefined;
          const tput = isMachine ? overlay?.throughput(n.id) : undefined;
          const idle = isMachine && !!overlay && tech == null;
          const sub = isMachine ? (tech ? (toTech ? `⇄ ${tech}` : tech) : n.level || "idle") : n.level || "group";
          const stroke = toTech ? "var(--warn)" : undefined;
          const clickable = mode === "expandable" && n.collapsed;
          return (
            <g
              key={`n-${n.id}`}
              className={`topo-node ${isMachine ? "topo-commodity" : "topo-process"}`}
              transform={`translate(${n.x},${n.y})`}
              opacity={idle ? 0.45 : 1}
              onClick={() => clickable && toggle(n.id)}
              onPointerDown={(e) => clickable && e.stopPropagation()}
              style={{ cursor: clickable ? "pointer" : "default" }}
            >
              <rect width={n.w} height={n.h} rx={3} stroke={stroke} strokeWidth={stroke ? 2 : undefined} />
              <text className="topo-kind" x={8} y={14}>
                {isMachine ? "machine" : n.collapsed ? "group ▸" : "group"}
              </text>
              {tput != null && (
                <text className="topo-kind" x={n.w - 8} y={14} textAnchor="end">
                  {fmtVal(tput)}
                </text>
              )}
              <text className="topo-label" x={8} y={31}>
                {clip(n.label, 22)}
              </text>
              <text className="topo-sub" x={8} y={46} fill={toTech ? "var(--warn-text)" : undefined}>
                {clip(sub, 24)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
