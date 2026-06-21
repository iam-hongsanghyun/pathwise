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
  routeWithStubs,
  sourceStreams,
  type LaidNode,
  type MapMode,
  type Orientation,
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
  /** Clear all manual positions — "reset layout" back to the auto arrangement. */
  onResetLayout?: () => void;
  /** A no-drag click on empty canvas — clears the selection / closes the inspector. */
  onBackgroundClick?: () => void;
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
  onResetLayout,
  onBackgroundClick,
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

  // Flow direction of the auto-layout ("h" = left→right, "v" = top→bottom) and
  // orthogonal (right-angle) edge routing. Both are view toggles in the toolbar.
  const [orientation, setOrientation] = useState<Orientation>("h");
  const [ortho, setOrtho] = useState(false);
  const horiz = orientation === "h";

  // Manual node positions (node_layout) overlaid on the auto-layout. A live drag
  // updates `dragDraft`; on drop it's committed to node_layout via onMoveNodes.
  // Manual positions are scoped per orientation: vertical-layout positions are
  // stored under a `v::` id prefix so the two arrangements never collide (and so
  // the backend, which keys placement off bare ids, ignores the vertical rows).
  const positions = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>();
    for (const r of workbook.node_layout ?? []) {
      let id = r.id == null ? "" : String(r.id);
      const isV = id.startsWith("v::");
      if (isV !== !horiz) continue; // only this orientation's rows
      if (isV) id = id.slice(3);
      const x = Number(r.x);
      const y = Number(r.y);
      if (id && Number.isFinite(x) && Number.isFinite(y)) m.set(id, { x, y });
    }
    return m;
  }, [workbook, horiz]);
  const [dragDraft, setDragDraft] = useState<Map<string, { x: number; y: number }> | null>(null);
  const dragDraftRef = useRef<Map<string, { x: number; y: number }> | null>(null);
  // The auto-layout WITHOUT manual positions — its size only changes on a real
  // structural edit (expand/collapse, orientation, model change), never on a drag.
  // The viewBox auto-fit keys off this so dragging never yanks the camera.
  const structural = useMemo(
    () => layoutFor(workbook, mode, expanded, orientation),
    [workbook, mode, expanded, orientation],
  );
  const laid = useMemo(
    () => applyManualLayout(structural, dragDraft ?? positions),
    [structural, positions, dragDraft],
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
  // Connection ports follow the flow direction: horizontal links exit the right
  // edge → enter the left edge; vertical links exit the bottom → enter the top.
  const outPt = (b: LaidNode) => (horiz ? { x: b.x + b.w, y: b.y + b.h / 2 } : { x: b.x + b.w / 2, y: b.y + b.h });
  const inPt = (b: LaidNode) => (horiz ? { x: b.x, y: b.y + b.h / 2 } : { x: b.x + b.w / 2, y: b.y });
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
        : laid.edges.map((e) => ({ ...e, rowIndex: -1, lag: 0, count: 1, commodities: [e.commodity] })),
    [editable, workbook, laid, flowLevel],
  );
  // Lowest-common-ancestor box of two endpoints — orthogonal routing stays INSIDE
  // it (a flow between two children of one box never leaves that box).
  const lcaBox = (fromId: string, toId: string): LaidNode | null => {
    const anc = new Set<string>();
    let c: string | null = fromId;
    const seen = new Set<string>();
    while (c && !seen.has(c)) { anc.add(c); seen.add(c); c = parentOf.get(c) ?? null; }
    let d: string | null = toId;
    const seen2 = new Set<string>();
    while (d && !seen2.has(d)) { if (anc.has(d)) return boxById.get(d) ?? null; seen2.add(d); d = parentOf.get(d) ?? null; }
    return null;
  };
  const edgeKey = (e: { from: string; to: string; commodity: string; rowIndex: number }) =>
    `${e.from}-${e.to}-${e.commodity}-${e.rowIndex}`;

  // The child of `ancId` that lies on the path down to `descId` (its diverging box).
  const childTowards = (descId: string, ancId: string): string => {
    let cur: string | null = descId;
    const seen = new Set<string>();
    while (cur && !seen.has(cur)) {
      if (parentOf.get(cur) === ancId) return cur;
      seen.add(cur);
      cur = parentOf.get(cur) ?? null;
    }
    return descId;
  };
  // Precompute the obstacle-avoiding orthogonal path for every edge (only in
  // straight-line mode). Each flow routes the SHORTEST right-angle path inside its
  // lowest-common-ancestor box, around the sibling boxes — so lines don't cross
  // group / component boxes. Memoised so hover / pan don't recompute the A*.
  const orthoRoutes = useMemo(() => {
    const map = new Map<string, { x: number; y: number }[]>();
    if (!ortho) return map;
    const childrenByParent = new Map<string, LaidNode[]>();
    for (const n of placed) {
      if (!n.parentId) continue;
      const arr = childrenByParent.get(n.parentId);
      if (arr) arr.push(n);
      else childrenByParent.set(n.parentId, [n]);
    }
    for (const e of edges) {
      const a = boxById.get(e.from);
      const b = boxById.get(e.to);
      const L = lcaBox(e.from, e.to);
      if (!a || !b || !L) continue;
      const sa = childTowards(e.from, L.id);
      const sb = childTowards(e.to, L.id);
      const obstacles = (childrenByParent.get(L.id) ?? [])
        .filter((n) => n.id !== sa && n.id !== sb)
        .map((n) => ({ x: n.x, y: n.y, w: n.w, h: n.h }));
      const path = routeWithStubs(
        outPt(a),
        inPt(b),
        obstacles,
        { x: L.x, y: L.y, w: L.w, h: L.h },
        orientation,
        { x: a.x, y: a.y, w: a.w, h: a.h },
        { x: b.x, y: b.y, w: b.w, h: b.h },
      );
      if (path && path.length >= 2) map.set(edgeKey(e), path);
    }
    return map;
  }, [ortho, edges, placed, boxById, horiz, orientation]);

  // Per-edge render geometry, computed once: the path `d`, plus a label anchor at
  // EACH end (in the perpendicular-stub gutter, i.e. where the flow starts and
  // where it connects) so the text never lands on another item's box.
  const edgeViews = useMemo(() => {
    const STUB = 16;
    const out: {
      e: (typeof edges)[number];
      d: string;
      active: boolean;
      src: { x: number; y: number };
      dst: { x: number; y: number };
    }[] = [];
    for (const e of edges) {
      const a = boxById.get(e.from);
      const b = boxById.get(e.to);
      if (!a || !b) continue;
      const p1 = outPt(a);
      const p2 = inPt(b);
      const fv = overlay?.flow(e.origFrom, e.origTo, e.commodity);
      const active = fv != null && fv > 1e-6;
      const mid = (u: { x: number; y: number }, v: { x: number; y: number }) => ({ x: (u.x + v.x) / 2, y: (u.y + v.y) / 2 });
      let d: string;
      let src: { x: number; y: number };
      let dst: { x: number; y: number };
      const routed = ortho ? orthoRoutes.get(edgeKey(e)) : undefined;
      if (routed && routed.length >= 2) {
        d = routed.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ");
        src = mid(routed[0], routed[1]); // source stub
        dst = mid(routed[routed.length - 2], routed[routed.length - 1]); // target stub
      } else {
        if (ortho) {
          const cx = (p1.x + p2.x) / 2;
          const cy = (p1.y + p2.y) / 2;
          d = horiz
            ? `M${p1.x},${p1.y} L${cx},${p1.y} L${cx},${p2.y} L${p2.x},${p2.y}`
            : `M${p1.x},${p1.y} L${p1.x},${cy} L${p2.x},${cy} L${p2.x},${p2.y}`;
        } else {
          const c = Math.max(40, (horiz ? p2.x - p1.x : p2.y - p1.y) / 2);
          d = horiz
            ? `M${p1.x},${p1.y} C${p1.x + c},${p1.y} ${p2.x - c},${p2.y} ${p2.x},${p2.y}`
            : `M${p1.x},${p1.y} C${p1.x},${p1.y + c} ${p2.x},${p2.y - c} ${p2.x},${p2.y}`;
        }
        src = horiz ? { x: p1.x + STUB, y: p1.y } : { x: p1.x, y: p1.y + STUB };
        dst = horiz ? { x: p2.x - STUB, y: p2.y } : { x: p2.x, y: p2.y - STUB };
      }
      out.push({ e, d, active, src, dst });
    }
    return out;
  }, [edges, boxById, ortho, orthoRoutes, horiz, overlay]);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const { vb, setVb, onWheel, onPanStart, onPanMove, onPanEnd, toWorld } = useViewBox();
  const fitKey = `${mode}|${orientation}|${structural.width}x${structural.height}|${structural.nodes.length}|${sources.length}`;
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
  // Hover-a-flow popup: which arrow, and where the cursor is.
  const [hover, setHover] = useState<{ x: number; y: number; from: string; to: string; commodities: string[]; lag: number } | null>(null);

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
      // boxById is in PLACED space (y shifted by bandH); positions / dragDraft
      // live in pre-band laid space, so capture the origin without the band.
      if (b) starts.set(id, { x: b.x, y: b.y - bandH });
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
        onMoveNodes?.(
          [...dragDraftRef.current].map(([id, p]) => ({ id: horiz ? id : `v::${id}`, x: p.x, y: p.y })),
        );
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
    // Walk ancestors (not just e.target) so a click anywhere inside the group box
    // — body, header, label — resolves to the group; the ▾ grip wins via toggle.
    const toggleId = el?.closest?.("[data-toggle]")?.getAttribute("data-toggle") ?? null;
    const groupId = el?.closest?.("[data-group]")?.getAttribute("data-group") ?? null;
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
    const b = bgPress.current;
    bgPress.current = null;
    onPanEnd();
    // A no-move tap on empty canvas (not a pan, not a link drag) clears the
    // selection so the floating inspector closes.
    if (b && !b.moved && !connect) onBackgroundClick?.();
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
          cx={horiz ? 0 : n.w / 2}
          cy={horiz ? n.h / 2 : 0}
          r={6}
          style={{ cursor: "pointer" }}
          onPointerUp={(e) => {
            e.stopPropagation();
            if (connect && connect.from !== n.id) setForm({ from: connect.from, to: n.id, sx: e.clientX, sy: e.clientY });
            setConnect(null);
            press.current = null;
          }}
        />
        <circle
          className="topo-out"
          cx={horiz ? n.w : n.w / 2}
          cy={horiz ? n.h / 2 : n.h}
          r={6}
          style={{ cursor: "pointer" }}
          onPointerDown={(e) => {
            e.stopPropagation();
            e.preventDefault(); // don't let the drag start a text/area selection
            const w = toWorld(e.clientX, e.clientY, svgRef.current);
            setConnect({ from: n.id, wx: w.x, wy: w.y });
          }}
        />
      </>
    ) : null;

  // Uniform fixed size for every toolbar button — icon on top, label below — so
  // they align and the orientation toggle never resizes when its label flips.
  const toolBtn: React.CSSProperties = {
    width: 82,
    height: 46,
    padding: "4px 4px",
    fontSize: "0.72rem",
    lineHeight: 1.15,
    display: "inline-flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 2,
    textAlign: "center",
    cursor: "pointer",
  };
  return (
    <div className="canvas topo-canvas" style={{ display: "flex", flexDirection: "column", position: "relative" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 12px", background: "var(--surface)" }}>
        <button className="ghost" style={toolBtn} onClick={expandAll} title="Expand every group">
          <span style={{ fontSize: "0.95rem" }}>⊞</span>
          <span>Expand all</span>
        </button>
        <button className="ghost" style={toolBtn} onClick={collapseAll} title="Collapse every group">
          <span style={{ fontSize: "0.95rem" }}>⊟</span>
          <span>Collapse all</span>
        </button>
        {editable && (
          <>
            <button
              className="ghost"
              style={toolBtn}
              onClick={() => setOrientation((o) => (o === "h" ? "v" : "h"))}
              title="Switch flow direction — left→right ↔ top→bottom"
            >
              <span style={{ fontSize: "0.95rem" }}>{horiz ? "⇄" : "⇳"}</span>
              <span>{horiz ? "Horizontal" : "Vertical"}</span>
            </button>
            <button
              className="ghost"
              style={{
                ...toolBtn,
                background: ortho ? "var(--brand-fill)" : undefined,
                borderColor: ortho ? "var(--brand)" : undefined,
                color: ortho ? "var(--brand)" : undefined,
              }}
              onClick={() => setOrtho((v) => !v)}
              title="Straight flow lines — shortest right-angle path around the boxes"
            >
              <span style={{ fontSize: "0.95rem" }}>⌐</span>
              <span>Straight lines</span>
            </button>
            {onResetLayout && (
              <button
                className="ghost"
                style={toolBtn}
                onClick={() => {
                  onResetLayout();
                  const pad = 50;
                  setVb({ x: -pad, y: -pad, w: Math.max(structural.width, bandW) + 2 * pad, h: bandH + structural.height + 2 * pad });
                }}
                title="Reset all moved nodes back to the automatic layout"
              >
                <span style={{ fontSize: "0.95rem" }}>↺</span>
                <span>Reset layout</span>
              </button>
            )}
          </>
        )}
        {editable && (
          <label style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: "0.74rem" }} title="Aggregate the flows to this level (independent of expand/collapse). Dynamic draws each flow where its two sides first diverge.">
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

        {/* EDGE LINES — drawn BEHIND every box, so a line crossing a box reads as
            dimmed (the box, white + translucent, sits on top). Labels + controls
            are a separate pass after the boxes. */}
        {edgeViews.map(({ e, d, active }) => {
          const sel = editable && e.rowIndex >= 0 && selEdge === e.rowIndex;
          const onHover = (ev: React.MouseEvent) =>
            setHover({ x: ev.clientX, y: ev.clientY, from: e.from, to: e.to, commodities: e.commodities, lag: e.lag });
          return (
            <g key={`el-${edgeKey(e)}`} className="topo-edge">
              <path d={d} fill="none" stroke={sel ? "#0b5d56" : "#0f766e"} strokeWidth={sel ? 2.6 : active ? 2.2 : 1.3} markerEnd="url(#hm-arrow)" opacity={overlay && !active ? 0.28 : 0.72} />
              <path
                d={d}
                fill="none"
                stroke="transparent"
                strokeWidth={14}
                style={{ cursor: "pointer" }}
                onMouseEnter={onHover}
                onMouseMove={onHover}
                onMouseLeave={() => setHover(null)}
                onClick={editable && e.rowIndex >= 0 ? () => setSelEdge(sel ? null : e.rowIndex) : undefined}
              />
            </g>
          );
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
              {/* body — also a drag/select target (data-group): grab anywhere on
                  the box (not on a child) to move the whole group. The ▾ grip
                  still collapses; children on top keep their own handlers. */}
              <rect
                data-group={g.id}
                x={g.x}
                y={g.y}
                width={g.w}
                height={g.h}
                rx={6}
                fill="var(--surface)"
                fillOpacity={0.34}
                stroke={sel ? "var(--brand)" : "var(--border-strong)"}
                strokeWidth={sel ? 3 : 1}
                style={{ cursor: "pointer" }}
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

        {/* (edge lines are drawn above, before the boxes; labels + controls are a
            separate top pass below, after the leaves) */}

        {/* rubber-band while connecting */}
        {connect && (() => {
          const a = boxById.get(connect.from);
          if (!a) return null;
          const p = outPt(a);
          return <path d={`M${p.x},${p.y} L${connect.wx},${connect.wy}`} fill="none" stroke="#0f766e" strokeWidth={1.5} strokeDasharray="5 4" opacity={0.7} />;
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
          // White, slightly translucent fill so a flow line passing BEHIND the box
          // reads as dimmed (the box stays in front and legible).
          const fill = isSel ? "var(--brand-fill)" : "var(--surface)";
          return (
            <g
              key={`n-${n.id}`}
              className={`topo-node ${isMachine ? "topo-commodity" : "topo-process"}`}
              transform={`translate(${n.x},${n.y})`}
              opacity={idle ? 0.45 : 1}
              style={{ cursor: "pointer" }}
              onPointerDown={(e) => startNodeDrag([n.id], () => nodeClick(n), e)}
            >
              <rect width={n.w} height={n.h} rx={3} fill={fill} fillOpacity={isSel ? 1 : 0.92} stroke={stroke} strokeWidth={isSel || toTech ? 2.5 : undefined} />
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

        {/* EDGE LABELS — on TOP of the boxes, at BOTH ends of each flow (where it
            starts and where it connects), each commodity on its own line over a
            backing chip so the text is never hidden or written across a box. */}
        {(() => {
          const used = new Map<string, number>(); // stagger labels that share a port cell
          const LH = 11;
          const chip = (key: string, at: { x: number; y: number }, lines: string[], active: boolean) => {
            const cell = `${Math.round(at.x / 36)}|${Math.round(at.y / 28)}`;
            const rank = used.get(cell) ?? 0;
            used.set(cell, rank + 1);
            const blockH = lines.length * LH;
            const boxW = Math.max(...lines.map((l) => l.length)) * 5.6 + 10;
            const topY = at.y - blockH / 2 + LH - 2 + rank * (blockH + 5);
            return (
              <g key={key} style={{ pointerEvents: "none" }}>
                <rect x={at.x - boxW / 2} y={topY - LH + 2} width={boxW} height={blockH + 4} rx={3} fill="var(--surface)" opacity={0.92} stroke="var(--border)" strokeWidth={0.5} />
                <text x={at.x} y={topY} fontSize={9} fill={active ? "var(--text)" : "var(--muted)"} textAnchor="middle">
                  {lines.map((l, i) => (
                    <tspan key={i} x={at.x} dy={i ? LH : 0}>{l}</tspan>
                  ))}
                </text>
              </g>
            );
          };
          return edgeViews.flatMap(({ e, src, dst, active }) => {
            const lines = e.commodities.map((c) => clip(c, 16) + (e.lag ? ` ·${e.lag}y` : ""));
            return [chip(`ls-${edgeKey(e)}`, src, lines, active), chip(`ld-${edgeKey(e)}`, dst, lines, active)];
          });
        })()}

        {/* edit / delete controls for the selected edge (top layer, clickable) */}
        {editable &&
          selEdge != null &&
          edgeViews
            .filter((v) => v.e.rowIndex === selEdge)
            .map(({ e, src }) => (
              <g key={`ec-${edgeKey(e)}`}>
                {onEditConnection && (
                  <g style={{ cursor: "pointer" }} onClick={(ev) => setForm({ from: e.from, to: e.to, sx: ev.clientX, sy: ev.clientY, editRowIndex: e.rowIndex, commodity: e.commodity, lag: e.lag })}>
                    <circle cx={src.x} cy={src.y + 16} r={8} fill="var(--brand)" />
                    <text x={src.x} y={src.y + 17} fontSize={9} fill="#fff" textAnchor="middle" dominantBaseline="middle">✎</text>
                  </g>
                )}
                {onDeleteConnection && (
                  <g style={{ cursor: "pointer" }} onClick={() => { onDeleteConnection(e.rowIndex); setSelEdge(null); }}>
                    <circle cx={src.x + 20} cy={src.y + 16} r={8} fill="var(--danger)" />
                    <text x={src.x + 20} y={src.y + 17} fontSize={10} fill="#fff" textAnchor="middle" dominantBaseline="middle">✕</text>
                  </g>
                )}
              </g>
            ))}
      </svg>

      {/* hover-a-flow popup: what commodities travel along the arrow under the cursor */}
      {hover && (
        <div
          style={{
            position: "fixed",
            left: Math.min(hover.x + 14, window.innerWidth - 240),
            top: Math.min(hover.y + 14, window.innerHeight - 120),
            zIndex: 1200,
            pointerEvents: "none",
            background: "var(--surface)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--radius-button)",
            boxShadow: "0 6px 24px rgba(0,0,0,0.16)",
            padding: "8px 10px",
            maxWidth: 240,
            fontSize: "0.76rem",
          }}
        >
          <div style={{ marginBottom: 4 }}>
            <b>{boxById.get(hover.from)?.label ?? hover.from}</b>
            <span className="muted"> → </span>
            <b>{boxById.get(hover.to)?.label ?? hover.to}</b>
          </div>
          <div className="muted" style={{ marginBottom: 2, fontSize: "0.7rem" }}>
            {hover.commodities.length} flow{hover.commodities.length === 1 ? "" : "s"}
            {hover.lag ? ` · ${hover.lag}y lag` : ""}
          </div>
          <ul style={{ margin: 0, padding: "0 0 0 14px" }}>
            {hover.commodities.map((c) => (
              <li key={c} style={{ color: "var(--text)" }}>{c}</li>
            ))}
          </ul>
        </div>
      )}

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
