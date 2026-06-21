// HierarchyMap — one multi-level map for the WHOLE node hierarchy (country →
// company → facility → machine) in a single chart. Groups expand/collapse on
// click (drill-down); Expand all / Collapse all are in the top-left toolbar.
//
// Read-only (Analytics result map): pass `result` → a year slider scrubs active
// technology / throughput / flows per year.
// Editable (Value-chain map): pass `editable` + the connection callbacks → links
// are drawn between nodes; drag a node's right port to another's left port to add
// a link, click a link to delete it, click a node to select it (right rail).

import { useEffect, useMemo, useRef, useState } from "react";
import { SearchableSelect } from "../controls/SearchableSelect";
import { buildOverlay, ResultYearBar, type CascadeResult, type YearOverlay } from "../valuechain/panels";
import { parseNodes } from "../../lib/groupGraph";
import {
  applyManualLayout,
  defaultExpanded,
  editEdges,
  layoutFor,
  sourceStreams,
  type LaidNode,
  type MapMode,
} from "../../lib/hierarchyLayout";
import { useViewBox } from "./useViewBox";
import type { RunResult, Workbook } from "../../types";

const DRAG_PX = 3;

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
  /** A solved run (joint or cascade) → show the year slider and per-year overlay. */
  result?: RunResult | CascadeResult | null;
  /** Enable link editing + node selection on the canvas (the value-chain map). */
  editable?: boolean;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  onAddConnection?: (from: string, to: string, commodity: string, lag: number) => void;
  onEditConnection?: (rowIndex: number, commodity: string, lag: number) => void;
  onDeleteConnection?: (rowIndex: number) => void;
  /** Persist manual node positions (upserted into the `node_layout` sheet). */
  onMoveNodes?: (positions: { id: string; x: number; y: number }[]) => void;
  commodities?: string[];
}

export function HierarchyMap({
  workbook,
  result,
  editable = false,
  selectedId,
  onSelect,
  onAddConnection,
  onEditConnection,
  onDeleteConnection,
  onMoveNodes,
  commodities = [],
}: Props) {
  const mode: MapMode = "expandable"; // the only layout: an expandable drill-down
  const overlayIdx = useMemo(() => (result ? buildOverlay(result) : null), [result]);
  const [year, setYear] = useState<number>(() => overlayIdx?.years[0] ?? 0);
  useEffect(() => {
    if (overlayIdx) setYear((y) => (overlayIdx.years.includes(y) ? y : (overlayIdx.years[0] ?? 0)));
  }, [overlayIdx]);
  const overlay: YearOverlay | null = useMemo(
    () => (overlayIdx && overlayIdx.years.length ? overlayIdx.at(year) : null),
    [overlayIdx, year],
  );

  // Every group that has children (the expand/collapse-able set). The ▦ Expand-all
  // button uses this; Collapse all → just the roots.
  const allGroupIds = useMemo(() => {
    const ns = parseNodes(workbook);
    const parents = new Set(ns.map((n) => n.parentId).filter((p): p is string => !!p));
    return ns.filter((n) => n.kind === "group" && parents.has(n.id)).map((n) => n.id);
  }, [workbook]);
  // Default: expand as much as fits a node budget — small models open fully, large
  // ones (e.g. the 248-machine petrochemical chain) open a level or two down so the
  // canvas doesn't paint hundreds of boxes + source-flow lines at once and freeze.
  const initialExpanded = useMemo(() => defaultExpanded(workbook), [workbook]);
  const [expanded, setExpanded] = useState<Set<string>>(initialExpanded);
  useEffect(() => setExpanded(initialExpanded), [initialExpanded]);
  const expandAll = () => setExpanded(new Set(allGroupIds));
  const collapseAll = () => setExpanded(new Set());

  // Flow-aggregation level (independent of expand/collapse): null = Component (every
  // machine→machine link). The selectable group levels come from the TREE itself
  // (never hardcoded), ordered deepest→shallowest (least→most aggregation).
  const [flowLevel, setFlowLevel] = useState<string | null>(null);
  const flowLevels = useMemo(() => {
    const ns = parseNodes(workbook);
    const parent = new Map(ns.map((n) => [n.id, n.parentId]));
    const depth = (id: string): number => {
      let d = 0;
      let cur = parent.get(id) ?? null;
      const seen = new Set<string>();
      while (cur && !seen.has(cur)) { d++; seen.add(cur); cur = parent.get(cur) ?? null; }
      return d;
    };
    const minDepth = new Map<string, number>();
    for (const n of ns) {
      if (n.kind === "machine" || !n.level) continue;
      const d = depth(n.id);
      if (!minDepth.has(n.level) || d < (minDepth.get(n.level) as number)) minDepth.set(n.level, d);
    }
    return [...minDepth.entries()].sort((a, b) => b[1] - a[1]).map(([lvl]) => lvl);
  }, [workbook]);
  useEffect(() => {
    // Drop the selection if the model no longer has that level.
    if (flowLevel && !flowLevels.includes(flowLevel)) setFlowLevel(null);
  }, [flowLevels, flowLevel]);
  const titleCase = (s: string) => s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  // Manual node positions (node_layout) overlaid on the auto-layout. A live drag
  // updates `dragDraft`; on drop it's committed to node_layout via onMoveNodes.
  const positions = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>();
    for (const r of workbook.node_layout ?? []) {
      const id = r.id == null ? "" : String(r.id);
      const x = Number(r.x);
      const y = Number(r.y);
      if (id && Number.isFinite(x) && Number.isFinite(y)) m.set(id, { x, y });
    }
    return m;
  }, [workbook]);
  const [dragDraft, setDragDraft] = useState<Map<string, { x: number; y: number }> | null>(null);
  const dragDraftRef = useRef<Map<string, { x: number; y: number }> | null>(null);
  const laid = useMemo(
    () => applyManualLayout(layoutFor(workbook, mode, expanded), dragDraft ?? positions),
    [workbook, mode, expanded, positions, dragDraft],
  );

  // Source streams (consumed but produced by none — raw materials) sit in a band
  // across the top; the hierarchy is shifted down by `bandH` to make room.
  const sources = useMemo(() => sourceStreams(workbook), [workbook]);
  const SRC_W = 158;
  const SRC_H = 46;
  const SRC_GAP = 18;
  const SRC_X0 = 24;
  const SRC_Y = 16;
  const bandH = sources.length > 0 ? SRC_H + 50 : 0;
  const srcPos = useMemo(
    () => new Map(sources.map((sx, i) => [sx.id, { x: SRC_X0 + i * (SRC_W + SRC_GAP), y: SRC_Y }])),
    [sources],
  );
  const bandW = sources.length > 0 ? SRC_X0 + sources.length * (SRC_W + SRC_GAP) : 0;

  const placed = useMemo(
    () => (bandH ? laid.nodes.map((n) => ({ ...n, y: n.y + bandH })) : laid.nodes),
    [laid, bandH],
  );
  const boxById = useMemo(() => new Map(placed.map((n) => [n.id, n])), [placed]);
  // Nearest VISIBLE ancestor — routes a source→consumer arrow to a collapsed
  // group when the consuming machine is hidden (expandable mode).
  const parentOf = useMemo(
    () => new Map(parseNodes(workbook).map((n) => [n.id, n.parentId])),
    [workbook],
  );
  const resolveVisible = (id: string): string | null => {
    let cur: string | null = id;
    const seen = new Set<string>();
    while (cur && !seen.has(cur)) {
      if (boxById.has(cur)) return cur;
      seen.add(cur);
      cur = parentOf.get(cur) ?? null;
    }
    return null;
  };
  const edges = useMemo(
    () =>
      editable
        ? editEdges(workbook, laid.nodes, flowLevel).map((e) => ({ ...e, origFrom: e.from, origTo: e.to }))
        : laid.edges.map((e) => ({ ...e, rowIndex: -1, lag: 0, count: 1 })),
    [editable, workbook, laid, flowLevel],
  );
  const edgeKey = (e: { from: string; to: string; commodity: string; rowIndex: number }) =>
    `${e.from}-${e.to}-${e.commodity}-${e.rowIndex}`;
  // Stagger labels of edges whose midpoints collide, so two flows between the
  // same area (e.g. two hydrogen links) don't print on top of each other.
  const edgeLabelRank = useMemo(() => {
    const bucket = new Map<string, number>();
    const rank = new Map<string, number>();
    for (const e of edges) {
      const a = boxById.get(e.from);
      const b = boxById.get(e.to);
      if (!a || !b) continue;
      const mx = (a.x + a.w + b.x) / 2;
      const my = (a.y + a.h / 2 + b.y + b.h / 2) / 2;
      const key = `${Math.round(mx / 30)}|${Math.round(my / 18)}`;
      const r = bucket.get(key) ?? 0;
      bucket.set(key, r + 1);
      rank.set(edgeKey(e), r);
    }
    return rank;
  }, [edges, boxById]);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const { vb, setVb, onWheel, onPanStart, onPanMove, onPanEnd, toWorld } = useViewBox();
  const fitKey = `${mode}|${laid.width}x${laid.height}|${laid.nodes.length}|${sources.length}`;
  // The "fit everything" viewBox — the 100% baseline and the reset target.
  const fitBox = useMemo(() => {
    const pad = 50;
    return {
      x: -pad,
      y: -pad,
      w: Math.max(laid.width, bandW) + 2 * pad,
      h: bandH + laid.height + 2 * pad,
    };
  }, [laid.width, laid.height, bandW, bandH]);
  useEffect(() => {
    setVb(fitBox); // re-fit when the layout (mode / size) changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey]);
  // Zoom controls: scale the viewBox around its centre; 100% = the fit view.
  const zoomBy = (f: number) =>
    setVb((v) => {
      const cx = v.x + v.w / 2;
      const cy = v.y + v.h / 2;
      const w = Math.max(50, v.w / f);
      const h = Math.max(50, v.h / f);
      return { x: cx - w / 2, y: cy - h / 2, w, h };
    });
  const zoomPct = vb.w > 0 ? Math.round((fitBox.w / vb.w) * 100) : 100;

  // Editing gestures: a press (select), an output→input port drag (connect).
  const press = useRef<{ id: string; x: number; y: number; moved: boolean } | null>(null);
  // Background/container press: the SVG captures the pointer for panning, so a
  // click on a container rect can't use onClick (the click retargets to the SVG).
  // We record the pointer-down target's group id here and act on a no-move up.
  const bgPress = useRef<{ x: number; y: number; moved: boolean; groupId: string | null; toggleId: string | null } | null>(null);
  const [connect, setConnect] = useState<{ from: string; wx: number; wy: number } | null>(null);
  const [form, setForm] = useState<{ from: string; to: string; sx: number; sy: number; editRowIndex?: number; commodity?: string; lag?: number } | null>(null);
  const [selEdge, setSelEdge] = useState<number | null>(null);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  // Leaf boxes (machine / collapsed group) under `groupId` — the things a group
  // drag moves; the group box itself re-fits around them afterwards.
  const descendantLeaves = (groupId: string): string[] => {
    const out: string[] = [];
    for (const n of laid.nodes) {
      if (n.kind === "group" && !n.collapsed) continue;
      let cur: string | null = n.id;
      const seen = new Set<string>();
      while (cur && !seen.has(cur)) {
        if (cur === groupId) {
          if (n.id !== groupId) out.push(n.id);
          break;
        }
        seen.add(cur);
        cur = parentOf.get(cur) ?? null;
      }
    }
    return out;
  };

  // Drag `leafIds` (a leaf, or a group's descendant leaves) by the pointer delta;
  // a real drag commits new positions to node_layout, a no-move tap runs onClick.
  function startNodeDrag(leafIds: string[], onClick: () => void, e: React.PointerEvent) {
    if (connect || !editable) {
      onClick();
      return;
    }
    e.stopPropagation();
    const svg = svgRef.current;
    const start = toWorld(e.clientX, e.clientY, svg);
    const starts = new Map<string, { x: number; y: number }>();
    for (const id of leafIds) {
      const b = boxById.get(id);
      if (b) starts.set(id, { x: b.x, y: b.y });
    }
    let moved = false;
    const move = (ev: PointerEvent) => {
      if (!moved && Math.hypot(ev.clientX - e.clientX, ev.clientY - e.clientY) < DRAG_PX) return;
      moved = true;
      const now = toWorld(ev.clientX, ev.clientY, svg);
      const dx = now.x - start.x;
      const dy = now.y - start.y;
      const draft = new Map(positions);
      for (const [id, s0] of starts) draft.set(id, { x: Math.round(s0.x + dx), y: Math.round(s0.y + dy) });
      dragDraftRef.current = draft;
      setDragDraft(draft);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (moved && dragDraftRef.current) {
        onMoveNodes?.([...dragDraftRef.current].map(([id, p]) => ({ id, x: p.x, y: p.y })));
      } else {
        onClick();
      }
      dragDraftRef.current = null;
      setDragDraft(null);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function bgDown(e: React.PointerEvent) {
    press.current = null;
    setSelEdge(null);
    const el = e.target as Element;
    const groupId = el?.getAttribute?.("data-group") ?? null;
    const toggleId = el?.getAttribute?.("data-toggle") ?? null;
    // The ▾ grip toggles (no drag); a group header drags the whole group (its
    // descendant leaves) or, on a no-move tap, selects it; the background pans.
    if (toggleId) {
      startNodeDrag([], () => toggle(toggleId), e);
      return;
    }
    if (groupId) {
      startNodeDrag(descendantLeaves(groupId), () => onSelect?.(groupId), e);
      return;
    }
    bgPress.current = { x: e.clientX, y: e.clientY, moved: false, groupId: null, toggleId: null };
    onPanStart(e);
  }
  function bgMove(e: React.PointerEvent) {
    if (connect) {
      const w = toWorld(e.clientX, e.clientY, svgRef.current);
      setConnect({ ...connect, wx: w.x, wy: w.y });
      return;
    }
    const b = bgPress.current;
    if (b && !b.moved && Math.hypot(e.clientX - b.x, e.clientY - b.y) >= DRAG_PX) b.moved = true;
    onPanMove(e);
  }
  function bgUp() {
    // Background pan end (group select / toggle / drag are handled in startNodeDrag).
    bgPress.current = null;
    onPanEnd();
    setConnect(null);
  }
  function nodeClick(n: LaidNode) {
    // Collapsed groups in the read-only (analytics) map still drill on click; the
    // editable map selects (details) and toggles only via the top-right grip.
    if (!editable && mode === "expandable" && n.collapsed) toggle(n.id);
    onSelect?.(n.id);
  }

  const containers = placed
    .filter((n) => n.kind === "group" && !n.collapsed)
    .sort((a, b) => a.depth - b.depth);
  const leaves = placed.filter((n) => n.kind === "machine" || n.collapsed);

  // Port circles (left = input, right = output) for editing every node box.
  const ports = (n: LaidNode) =>
    editable ? (
      <>
        <circle
          className="topo-in"
          cx={0}
          cy={n.h / 2}
          r={6}
          style={{ cursor: "crosshair" }}
          onPointerUp={(e) => {
            e.stopPropagation();
            if (connect && connect.from !== n.id) setForm({ from: connect.from, to: n.id, sx: e.clientX, sy: e.clientY });
            setConnect(null);
            press.current = null;
          }}
        />
        <circle
          className="topo-out"
          cx={n.w}
          cy={n.h / 2}
          r={6}
          style={{ cursor: "crosshair" }}
          onPointerDown={(e) => {
            e.stopPropagation();
            e.preventDefault(); // don't let the drag start a text/area selection
            const w = toWorld(e.clientX, e.clientY, svgRef.current);
            setConnect({ from: n.id, wx: w.x, wy: w.y });
          }}
        />
      </>
    ) : null;

  return (
    <div className="canvas topo-canvas" style={{ display: "flex", flexDirection: "column", position: "relative" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 12px", background: "var(--surface)" }}>
        <button className="ghost" style={{ padding: "3px 10px", fontSize: "0.76rem" }} onClick={expandAll} title="Expand every group">
          ⊞ Expand all
        </button>
        <button className="ghost" style={{ padding: "3px 10px", fontSize: "0.76rem" }} onClick={collapseAll} title="Collapse every group">
          ⊟ Collapse all
        </button>
        {editable && flowLevels.length > 0 && (
          <label style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: "0.74rem" }} title="Aggregate the flows to this level (independent of expand/collapse)">
            <span className="muted">flows by</span>
            <select
              value={flowLevel ?? ""}
              onChange={(e) => setFlowLevel(e.target.value || null)}
              style={{ fontSize: "0.74rem", padding: "2px 4px", border: "1px solid var(--border-strong)", borderRadius: 4, background: "var(--surface)", font: "inherit" }}
            >
              <option value="">Component</option>
              {flowLevels.map((lvl) => (
                <option key={lvl} value={lvl}>{titleCase(lvl)}</option>
              ))}
            </select>
          </label>
        )}
        <span className="muted" style={{ fontSize: "0.74rem" }}>
          click a group's name for details · its ▾ grip to collapse / expand{editable ? " · drag a node's right dot → another's left dot to link" : ""}
        </span>
        {sources.length > 0 && (
          <span className="muted" style={{ fontSize: "0.72rem", marginLeft: "auto", display: "inline-flex", gap: 12, alignItems: "center" }}>
            <span title="a node→node flow inside the chain (free internal transfer)"><span style={{ color: "#0f766e", fontWeight: 700 }}>→</span> connection (in-chain)</span>
            <span title="a raw stream produced by no node — bought from outside the chain"><span style={{ color: "var(--warn)", fontWeight: 700 }}>▾</span> source (bought outside)</span>
          </span>
        )}
      </div>
      {overlayIdx && overlayIdx.years.length > 0 && (
        <ResultYearBar years={overlayIdx.years} year={year} onYear={setYear} />
      )}

      <svg
        ref={svgRef}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        preserveAspectRatio="xMidYMin meet"
        onWheel={onWheel}
        onPointerDown={bgDown}
        onPointerMove={bgMove}
        onPointerUp={bgUp}
        role="img"
        aria-label="hierarchy map"
        style={{ flex: 1, minHeight: 0 }}
      >
        <defs>
          <marker id="hm-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="#0f766e" />
          </marker>
        </defs>

        {/* Top sources band: raw-material streams feeding the chain. */}
        {sources.map((src) => {
          const sp = srcPos.get(src.id)!;
          const consumed = overlay
            ? src.consumers.reduce((acc, cid) => acc + (overlay.buy(cid, src.id) ?? 0), 0)
            : 0;
          const isSel = selectedId === `stream:${src.id}`;
          return (
            <g
              key={`src-${src.id}`}
              className="topo-node"
              transform={`translate(${sp.x},${sp.y})`}
              style={{ cursor: editable ? "pointer" : "default" }}
              onClick={() => editable && onSelect?.(`stream:${src.id}`)}
            >
              <rect width={SRC_W} height={SRC_H} rx={3} fill="#fffbeb" stroke={isSel ? "var(--brand)" : "var(--warn)"} strokeWidth={isSel ? 2 : 1} />
              <text x={8} y={14} fontSize={9} fill="var(--warn-text)">source ▾</text>
              {overlay && consumed > 1e-6 && <text x={SRC_W - 8} y={14} fontSize={9} textAnchor="end" fill="var(--text)">{fmtVal(consumed)}</text>}
              <text x={8} y={31} fontSize={12} fontWeight={600} fill="var(--text)">{clip(src.id, 20)}</text>
              <text x={8} y={43} fontSize={9} fill="var(--muted)">{src.consumers.length} consumer{src.consumers.length === 1 ? "" : "s"}</text>
            </g>
          );
        })}
        {/* arrows: source → each visible consumer */}
        {sources.flatMap((src) => {
          const sp = srcPos.get(src.id)!;
          const seen = new Set<string>();
          return src.consumers.flatMap((cid) => {
            const vis = resolveVisible(cid);
            if (!vis || seen.has(vis)) return [];
            seen.add(vis);
            const b = boxById.get(vis);
            if (!b) return [];
            const x1 = sp.x + SRC_W / 2;
            const y1 = sp.y + SRC_H;
            const x2 = b.x + b.w / 2;
            const y2 = b.y;
            const qty = overlay?.buy(cid, src.id);
            const active = qty != null && qty > 1e-6;
            return [
              <path key={`sa-${src.id}-${vis}`} d={`M${x1},${y1} C${x1},${(y1 + y2) / 2} ${x2},${(y1 + y2) / 2} ${x2},${y2}`} fill="none" stroke="var(--warn)" strokeWidth={active ? 1.8 : 1} strokeDasharray="4 3" markerEnd="url(#hm-arrow)" opacity={overlay && !active ? 0.25 : 0.6} />,
            ];
          });
        })}

        {containers.map((g) => {
          // In expandable mode the whole header strip toggles (click to collapse);
          // otherwise it just selects. Children cover the body, so the header is
          // the reliable click target. `data-group` lets the SVG-level pointer
          // handler toggle this group on a no-drag click (the SVG captures the
          // pointer for panning, so the rect's own onClick can't be used).
          const sel = selectedId === g.id;
          return (
            <g key={`c-${g.id}`}>
              {/* body — not a toggle target (clicking/dragging it pans); only the
                  header collapses the group. */}
              <rect
                x={g.x}
                y={g.y}
                width={g.w}
                height={g.h}
                rx={6}
                fill="var(--surface)"
                stroke={sel ? "var(--brand)" : "var(--border-strong)"}
                strokeWidth={sel ? 3 : 1}
                opacity={0.5 + 0.12 * Math.min(3, g.depth)}
              />
              {/* header strip — the NAME / select target (data-group): click shows
                  details, leaving the chart level as is. */}
              <rect data-group={g.id} x={g.x} y={g.y} width={g.w} height={22} rx={6} fill={sel ? "var(--brand-fill)" : "var(--bg-hover)"} style={{ cursor: "pointer" }} />
              <text x={g.x + 10} y={g.y + 16} fontSize={11} fontWeight={600} fill="var(--text)" style={{ pointerEvents: "none" }}>
                {clip(g.label, Math.max(6, Math.floor((g.w - 30) / 8)))}
              </text>
              {/* top-right grip — the collapse/expand target (data-toggle). */}
              <rect data-toggle={g.id} x={g.x + g.w - 26} y={g.y} width={26} height={22} rx={6} fill="transparent" style={{ cursor: "pointer" }}>
                <title>collapse</title>
              </rect>
              <text x={g.x + g.w - 9} y={g.y + 16} fontSize={11} fill="var(--muted)" textAnchor="end" style={{ pointerEvents: "none" }}>
                ▾
              </text>
              {editable && <g transform={`translate(${g.x},${g.y})`}>{ports(g)}</g>}
            </g>
          );
        })}

        {edges.map((e) => {
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
          const sel = editable && e.rowIndex >= 0 && selEdge === e.rowIndex;
          const d = `M${x1},${y1} C${x1 + c},${y1} ${x2 - c},${y2} ${x2},${y2}`;
          const label =
            (active ? `${clip(e.commodity, 8)} ${fmtVal(fv!)}` : clip(e.commodity, 10)) +
            (e.count > 1 ? ` ×${e.count}` : "") +
            (e.lag ? ` ·${e.lag}y` : "");
          const labelY = my - 4 - (edgeLabelRank.get(edgeKey(e)) ?? 0) * 12;
          return (
            <g key={edgeKey(e)} className="topo-edge">
              <path d={d} fill="none" stroke={sel ? "#0b5d56" : "#0f766e"} strokeWidth={sel ? 2.6 : active ? 2.2 : 1.3} markerEnd="url(#hm-arrow)" opacity={overlay && !active ? 0.28 : 0.78} />
              {editable && e.rowIndex >= 0 && (
                <path d={d} fill="none" stroke="transparent" strokeWidth={12} style={{ cursor: "pointer" }} onClick={() => setSelEdge(sel ? null : e.rowIndex)} />
              )}
              <text x={mx} y={labelY} fontSize={9} fill={active ? "var(--text)" : "var(--muted)"} textAnchor="middle" style={{ pointerEvents: "none" }}>
                {label}
              </text>
              {sel && onEditConnection && (
                <g style={{ cursor: "pointer" }} onClick={(ev) => setForm({ from: e.from, to: e.to, sx: ev.clientX, sy: ev.clientY, editRowIndex: e.rowIndex, commodity: e.commodity, lag: e.lag })}>
                  <circle cx={mx + 22} cy={my - 2} r={8} fill="var(--brand)" />
                  <text x={mx + 22} y={my - 1} fontSize={9} fill="#fff" textAnchor="middle" dominantBaseline="middle">✎</text>
                </g>
              )}
              {sel && onDeleteConnection && (
                <g style={{ cursor: "pointer" }} onClick={() => { onDeleteConnection(e.rowIndex); setSelEdge(null); }}>
                  <circle cx={mx + 40} cy={my - 2} r={8} fill="var(--danger)" />
                  <text x={mx + 40} y={my - 1} fontSize={10} fill="#fff" textAnchor="middle" dominantBaseline="middle">✕</text>
                </g>
              )}
            </g>
          );
        })}

        {/* rubber-band while connecting */}
        {connect && (() => {
          const a = boxById.get(connect.from);
          if (!a) return null;
          return <path d={`M${a.x + a.w},${a.y + a.h / 2} L${connect.wx},${connect.wy}`} fill="none" stroke="#0f766e" strokeWidth={1.5} strokeDasharray="5 4" opacity={0.7} />;
        })()}

        {leaves.map((n: LaidNode) => {
          const isMachine = n.kind === "machine";
          const tech = isMachine ? overlay?.tech(n.id) : undefined;
          const toTech = isMachine ? overlay?.transitionedTo(n.id) : undefined;
          const tput = isMachine ? overlay?.throughput(n.id) : undefined;
          const idle = isMachine && !!overlay && tech == null;
          const sub = isMachine ? (tech ? (toTech ? `⇄ ${tech}` : tech) : n.level || "idle") : n.level || "group";
          const isSel = selectedId === n.id;
          const stroke = toTech ? "var(--warn)" : isSel ? "var(--brand)" : undefined;
          const fill = isSel ? "var(--brand-fill)" : undefined; // clear selection tint (like the tree)
          return (
            <g
              key={`n-${n.id}`}
              className={`topo-node ${isMachine ? "topo-commodity" : "topo-process"}`}
              transform={`translate(${n.x},${n.y})`}
              opacity={idle ? 0.45 : 1}
              style={{ cursor: editable ? "grab" : "pointer" }}
              onPointerDown={(e) => startNodeDrag([n.id], () => nodeClick(n), e)}
            >
              <rect width={n.w} height={n.h} rx={3} fill={fill} stroke={stroke} strokeWidth={isSel || toTech ? 2.5 : undefined} />
              <text className="topo-kind" x={8} y={14}>{isMachine ? "machine" : !editable && n.collapsed ? "group ▸" : "group"}</text>
              {tput != null && <text className="topo-kind" x={n.w - 8} y={14} textAnchor="end">{fmtVal(tput)}</text>}
              <text className="topo-label" x={8} y={31}>{clip(n.label, 22)}</text>
              <text className="topo-sub" x={8} y={46} fill={toTech ? "var(--warn-text)" : undefined}>{clip(sub, 24)}</text>
              {/* top-right grip — expand this collapsed group (the body click selects). */}
              {editable && n.kind === "group" && n.collapsed && (
                <g
                  onPointerDown={(e) => e.stopPropagation()}
                  onPointerUp={(e) => { e.stopPropagation(); press.current = null; toggle(n.id); }}
                  style={{ cursor: "pointer" }}
                >
                  <rect x={n.w - 22} y={0} width={22} height={22} rx={3} fill="transparent" />
                  <text x={n.w - 8} y={15} textAnchor="end" fontSize={12} fill="var(--muted)" style={{ pointerEvents: "none" }}>▸</text>
                </g>
              )}
              {ports(n)}
            </g>
          );
        })}
      </svg>

      {/* zoom controls (bottom-right): − / fit% / + */}
      <div
        style={{
          position: "absolute",
          right: 12,
          bottom: 12,
          display: "flex",
          alignItems: "stretch",
          border: "1px solid var(--border-strong)",
          borderRadius: 6,
          overflow: "hidden",
          background: "var(--surface)",
          boxShadow: "0 1px 4px rgba(0,0,0,0.12)",
          fontSize: "0.8rem",
        }}
      >
        <button className="ghost" style={{ borderRadius: 0, border: "none", padding: "4px 10px" }} title="Zoom out" onClick={() => zoomBy(1 / 1.2)}>
          −
        </button>
        <button
          className="ghost"
          style={{ borderRadius: 0, border: "none", borderLeft: "1px solid var(--border)", borderRight: "1px solid var(--border)", padding: "4px 8px", minWidth: 52 }}
          title="Fit to view (100%)"
          onClick={() => setVb(fitBox)}
        >
          {zoomPct}%
        </button>
        <button className="ghost" style={{ borderRadius: 0, border: "none", padding: "4px 10px" }} title="Zoom in" onClick={() => zoomBy(1.2)}>
          +
        </button>
      </div>

      {form && (
        <ConnectForm
          fromLabel={boxById.get(form.from)?.label ?? form.from}
          toLabel={boxById.get(form.to)?.label ?? form.to}
          commodities={commodities}
          initialCommodity={form.commodity ?? ""}
          initialLag={form.lag ?? 0}
          editing={form.editRowIndex != null}
          x={form.sx}
          y={form.sy}
          onCancel={() => setForm(null)}
          onConfirm={(commodity, lag) => {
            if (form.editRowIndex != null) onEditConnection?.(form.editRowIndex, commodity, lag);
            else onAddConnection?.(form.from, form.to, commodity, lag);
            setForm(null);
            setSelEdge(null);
          }}
        />
      )}
    </div>
  );
}

function ConnectForm({
  fromLabel, toLabel, commodities, x, y, onConfirm, onCancel, initialCommodity = "", initialLag = 0, editing = false,
}: {
  fromLabel: string; toLabel: string; commodities: string[]; x: number; y: number;
  onConfirm: (commodity: string, lag: number) => void;
  onCancel: () => void;
  initialCommodity?: string; initialLag?: number; editing?: boolean;
}) {
  const [commodity, setCommodity] = useState(initialCommodity);
  const [lag, setLag] = useState(initialLag);
  return (
    <div style={{ position: "fixed", left: Math.min(x, window.innerWidth - 300), top: Math.min(y, window.innerHeight - 160), zIndex: 1000, background: "var(--surface)", border: "1px solid var(--border-strong)", borderRadius: "var(--radius-button)", boxShadow: "0 6px 24px rgba(0,0,0,0.14)", padding: 10, width: 268, fontSize: "0.78rem" }}>
      <div style={{ marginBottom: 6 }}><b>{fromLabel}</b> → <b>{toLabel}</b></div>
      <div style={{ marginBottom: 6 }}>
        <SearchableSelect value={commodity} options={commodities} onChange={setCommodity} onCreate={setCommodity} placeholder="stream / commodity" />
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <span className="muted" style={{ width: 70 }}>lag (yr)</span>
        <input type="number" value={lag} onChange={(e) => setLag(Number(e.target.value) || 0)} style={{ width: 70, padding: "3px 6px", border: "1px solid var(--border-strong)", borderRadius: 4, font: "inherit" }} />
      </label>
      <p className="muted" style={{ fontSize: "0.72rem", margin: "0 0 8px" }}>
        Min/max offtake is set per machine in the machine popup (per provider machine).
      </p>
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
        <button className="ghost" onClick={onCancel}>cancel</button>
        <button className="run-button" disabled={!commodity} onClick={() => onConfirm(commodity, lag)}>{editing ? "✓ update" : "＋ link"}</button>
      </div>
    </div>
  );
}
