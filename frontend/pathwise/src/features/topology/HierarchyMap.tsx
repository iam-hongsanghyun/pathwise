// HierarchyMap — one multi-level map for the WHOLE node hierarchy (country →
// company → facility → asset) in a single chart. Groups expand/collapse on
// click (drill-down); Expand all / Collapse all are in the top-left toolbar.
//
// Read-only (Analytics result map): pass `result` → a year slider scrubs active
// technology / throughput / flows per year.
// Editable (Value-chain map): pass `editable` + the link callbacks → links
// are drawn between nodes; drag a node's right port to another's left port to add
// a link, click a link to delete it, click a node to select it (right rail).

import { useEffect, useMemo, useRef, useState } from "react";
import { SearchableSelect } from "../controls/SearchableSelect";
import { buildOverlay, ResultYearBar, type CascadeResult, type YearOverlay } from "../valuechain/panels";
import { parseNodes } from "../../lib/groupGraph";
import {
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
  onAddLink?: (from: string, to: string, commodity: string, lag: number) => void;
  onEditLink?: (rowIndex: number, commodity: string, lag: number) => void;
  onDeleteLink?: (rowIndex: number) => void;
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
  onAddLink,
  onEditLink,
  onDeleteLink,
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
  // ones (e.g. the 248-asset petrochemical chain) open a level or two down so the
  // canvas doesn't paint hundreds of boxes + source-flow lines at once and freeze.
  const initialExpanded = useMemo(() => defaultExpanded(workbook), [workbook]);
  const [expanded, setExpanded] = useState<Set<string>>(initialExpanded);
  useEffect(() => setExpanded(initialExpanded), [initialExpanded]);
  const expandAll = () => setExpanded(new Set(allGroupIds));
  const collapseAll = () => setExpanded(new Set());

  // Flow-aggregation level (independent of expand/collapse): null = Component (every
  // asset→asset link). The selectable group levels come from the TREE itself
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
      if (n.kind === "asset" || !n.level) continue;
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
  // Commodity text on the flow lines is OFF by default (it crowds the map); the
  // "Commodity" toolbar toggle turns it on. Hovering a line always shows the popup.
  const [showCommodity, setShowCommodity] = useState(false);
  const horiz = orientation === "h";

  // Pure auto-layout (nodes are not draggable). Re-fits the camera only on a real
  // structural change (expand/collapse, orientation, model edit).
  const laid = useMemo(
    () => layoutFor(workbook, mode, expanded, orientation),
    [workbook, mode, expanded, orientation],
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
  // Link ports follow the flow direction: horizontal links exit the right
  // edge → enter the left edge; vertical links exit the bottom → enter the top.
  const outPt = (b: LaidNode) => (horiz ? { x: b.x + b.w, y: b.y + b.h / 2 } : { x: b.x + b.w / 2, y: b.y + b.h });
  const inPt = (b: LaidNode) => (horiz ? { x: b.x, y: b.y + b.h / 2 } : { x: b.x + b.w / 2, y: b.y });
  // Nearest VISIBLE ancestor — routes a source→consumer arrow to a collapsed
  // group when the consuming asset is hidden (expandable mode).
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

  // Per-edge render geometry, computed once: the path `d` and the polyline points
  // (so labels can be placed inline on a clear segment near each end).
  const edgeViews = useMemo(() => {
    const out: {
      e: (typeof edges)[number];
      d: string;
      active: boolean;
      poly: { x: number; y: number }[];
    }[] = [];
    for (const e of edges) {
      const a = boxById.get(e.from);
      const b = boxById.get(e.to);
      if (!a || !b) continue;
      const p1 = outPt(a);
      const p2 = inPt(b);
      const fv = overlay?.flow(e.origFrom, e.origTo, e.commodity);
      const active = fv != null && fv > 1e-6;
      let poly: { x: number; y: number }[];
      const routed = ortho ? orthoRoutes.get(edgeKey(e)) : undefined;
      if (routed && routed.length >= 2) {
        poly = routed;
      } else if (ortho) {
        const cx = (p1.x + p2.x) / 2;
        const cy = (p1.y + p2.y) / 2;
        poly = horiz
          ? [p1, { x: cx, y: p1.y }, { x: cx, y: p2.y }, p2]
          : [p1, { x: p1.x, y: cy }, { x: p2.x, y: cy }, p2];
      } else {
        poly = [p1, p2]; // bézier — approximate with the chord for label placement
      }
      let d: string;
      if (!ortho) {
        const c = Math.max(40, (horiz ? p2.x - p1.x : p2.y - p1.y) / 2);
        d = horiz
          ? `M${p1.x},${p1.y} C${p1.x + c},${p1.y} ${p2.x - c},${p2.y} ${p2.x},${p2.y}`
          : `M${p1.x},${p1.y} C${p1.x},${p1.y + c} ${p2.x},${p2.y - c} ${p2.x},${p2.y}`;
      } else {
        d = poly.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ");
      }
      out.push({ e, d, active, poly });
    }
    return out;
  }, [edges, boxById, ortho, orthoRoutes, horiz, overlay]);

  // Flow labels: horizontal text next to each connector, then de-overlapped so no
  // two ever touch. Memoised (the O(n²) push only re-runs when geometry changes —
  // not on hover / pan / year scrub).
  const LABEL_LH = 11;
  const placedLabels = useMemo(() => {
    if (!showCommodity) return []; // labels hidden → skip the de-overlap work entirely
    const LH = LABEL_LH;
    const CW = 5.4; // approx char width at 9px
    const PAD = 5; // gap from the line
    const G = 3; // min gap between two labels
    type Lbl = {
      key: string; lines: string[]; w: number; h: number;
      bx: number; by: number; tx: number; ta: "start" | "middle" | "end"; dx: number; dy: number; active: boolean;
    };
    const raw: Lbl[] = [];
    for (const { e, poly, active } of edgeViews) {
      const lines = e.commodities.map((c) => clip(c, 16) + (e.lag ? ` ·${e.lag}y` : ""));
      const w = Math.max(...lines.map((l) => l.length)) * CW;
      const h = lines.length * LH;
      for (const out of [true, false]) {
        const port = out ? poly[0] : poly[poly.length - 1];
        const nxt = out ? poly[1] : poly[poly.length - 2];
        const lineH = Math.abs(nxt.x - port.x) >= Math.abs(nxt.y - port.y);
        const px = port.x + (lineH ? Math.sign(nxt.x - port.x) * 10 : 0);
        const py = port.y + (lineH ? 0 : Math.sign(nxt.y - port.y) * 10);
        let bx: number;
        let by: number;
        let tx: number;
        let ta: "start" | "middle" | "end";
        let dx = 0;
        let dy = 0;
        if (lineH) {
          bx = px - w / 2; tx = px; ta = "middle";
          by = out ? py - PAD - h : py + PAD;
          dy = out ? -1 : 1;
        } else {
          if (out) { bx = px - PAD - w; tx = px - PAD; ta = "end"; dx = -1; }
          else { bx = px + PAD; tx = px + PAD; ta = "start"; dx = 1; }
          by = py - h / 2;
        }
        raw.push({ key: `${out ? "ls" : "ld"}-${edgeKey(e)}`, lines, w, h, bx, by, tx, ta, dx, dy, active });
      }
    }
    const hit = (a: Lbl, b: Lbl) =>
      a.bx < b.bx + b.w + G && b.bx < a.bx + a.w + G && a.by < b.by + b.h + G && b.by < a.by + a.h + G;
    const placed: Lbl[] = [];
    for (const L of raw) {
      let guard = 0;
      while (guard++ < 240 && placed.some((p) => hit(L, p))) {
        L.bx += L.dx * 4;
        L.by += L.dy * 4;
        L.tx += L.dx * 4;
      }
      placed.push(L);
    }
    return placed;
  }, [edgeViews, showCommodity]);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const { vb, setVb, onWheel, onPanStart, onPanMove, onPanEnd, toWorld } = useViewBox();
  const fitKey = `${mode}|${orientation}|${laid.width}x${laid.height}|${laid.nodes.length}|${sources.length}`;
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

  // Background/container press: the SVG captures the pointer for panning, so a
  // click on a container rect can't use onClick (the click retargets to the SVG).
  // We record the pointer-down target's group id here and act on a no-move up.
  const bgPress = useRef<{ x: number; y: number; moved: boolean; kind: "toggle" | "group" | "node" | "empty"; id: string | null } | null>(null);
  const [connect, setConnect] = useState<{ from: string; wx: number; wy: number } | null>(null);
  const [form, setForm] = useState<{ from: string; to: string; sx: number; sy: number; editRowIndex?: number; commodity?: string; lag?: number } | null>(null);
  const [selEdge, setSelEdge] = useState<number | null>(null);
  // Hover-a-flow popup: which arrow, and where the cursor is.
  const [hover, setHover] = useState<{ x: number; y: number; from: string; to: string; commodities: string[]; lag: number } | null>(null);
  // Changing the aggregation / orientation rebuilds the edge set, so a selected
  // edge (and its edit/delete controls) would point at a stale rowIndex — clear it.
  useEffect(() => setSelEdge(null), [flowLevel, orientation, ortho]);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  // Every press — on a node, a group, or empty canvas — starts a potential PAN
  // (so you can drag the canvas from anywhere). On pointer-up, a no-move tap is
  // resolved to a select / toggle; a real drag was a pan. Nodes aren't repositioned.
  function bgDown(e: React.PointerEvent) {
    setSelEdge(null);
    const el = e.target as Element;
    const toggleId = el?.closest?.("[data-toggle]")?.getAttribute("data-toggle") ?? null;
    const nodeId = el?.closest?.("[data-node]")?.getAttribute("data-node") ?? null;
    const groupId = el?.closest?.("[data-group]")?.getAttribute("data-group") ?? null;
    let kind: "toggle" | "group" | "node" | "empty" = "empty";
    let id: string | null = null;
    if (toggleId) { kind = "toggle"; id = toggleId; }
    else if (nodeId) { kind = "node"; id = nodeId; }
    else if (groupId) { kind = "group"; id = groupId; }
    bgPress.current = { x: e.clientX, y: e.clientY, moved: false, kind, id };
    if (!connect) onPanStart(e);
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
  function bgUp(e?: React.PointerEvent) {
    const b = bgPress.current;
    bgPress.current = null;
    onPanEnd();
    if (connect) {
      // Complete the link if released anywhere on a destination node/group (not
      // just on its tiny in-port dot); otherwise cancel.
      const el = e?.target as Element | undefined;
      const to =
        el?.closest?.("[data-node]")?.getAttribute("data-node") ??
        el?.closest?.("[data-group]")?.getAttribute("data-group") ??
        null;
      if (to && to !== connect.from && e) {
        setForm({ from: connect.from, to, sx: e.clientX, sy: e.clientY });
      }
      setConnect(null);
      return;
    }
    // A no-move tap → act on whatever was under the cursor; a drag was a pan.
    if (b && !b.moved) {
      if (b.kind === "toggle" && b.id) toggle(b.id);
      else if (b.kind === "node" && b.id) {
        const n = boxById.get(b.id);
        if (n) nodeClick(n);
      } else if (b.kind === "group" && b.id) {
        if (selectedId === b.id && onBackgroundClick) onBackgroundClick();
        else onSelect?.(b.id);
      } else onBackgroundClick?.();
    }
  }
  function nodeClick(n: LaidNode) {
    // Collapsed groups in the read-only (analytics) map still drill on click; the
    // editable map selects (details) and toggles only via the top-right grip.
    if (!editable && mode === "expandable" && n.collapsed) toggle(n.id);
    // Clicking the already-selected node again closes the inspector.
    if (selectedId === n.id && onBackgroundClick) onBackgroundClick();
    else onSelect?.(n.id);
  }

  const containers = placed
    .filter((n) => n.kind === "group" && !n.collapsed)
    .sort((a, b) => a.depth - b.depth);
  const leaves = placed.filter((n) => n.kind === "asset" || n.collapsed);

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
            // Capture so move/up reach the SVG even if released off-canvas (and so
            // the link completes via bgUp's hit-test instead of the tiny in-port).
            try { svgRef.current?.setPointerCapture(e.pointerId); } catch { /* synthetic */ }
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
          </>
        )}
        <button
          className="ghost"
          style={{
            ...toolBtn,
            background: showCommodity ? "var(--brand-fill)" : undefined,
            borderColor: showCommodity ? "var(--brand)" : undefined,
            color: showCommodity ? "var(--brand)" : undefined,
          }}
          onClick={() => setShowCommodity((v) => !v)}
          title="Show / hide the commodity name written on each flow line (hover a line for details either way)"
        >
          <span style={{ fontSize: "0.95rem" }}>🏷</span>
          <span>Commodity</span>
        </button>
        {editable && (
          <label style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: "0.74rem" }} title="Aggregate the flows to this level (independent of expand/collapse). The top 'Value Chain' level draws each flow where its two sides first diverge.">
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
            <span title="a node→node flow inside the chain (free internal transfer)"><span style={{ color: "#0f766e", fontWeight: 700 }}>→</span> link (in-chain)</span>
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
        onPointerUp={(e) => bgUp(e)}
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

        {/* EDGE LINES (visible) — drawn BEHIND every box, so a line crossing a box
            reads as dimmed (the box, white + translucent, sits on top). The
            interactive hit-paths are a separate pass ON TOP (after the boxes) so
            hover still works where a line runs behind a box. */}
        {edgeViews.map(({ e, d, active }) => {
          const sel = editable && e.rowIndex >= 0 && selEdge === e.rowIndex;
          return (
            <path key={`el-${edgeKey(e)}`} className="topo-edge" d={d} fill="none" stroke={sel ? "#0b5d56" : "#0f766e"} strokeWidth={sel ? 2.6 : active ? 2.2 : 1.3} markerEnd="url(#hm-arrow)" opacity={overlay && !active ? 0.28 : 0.72} />
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
              {/* body (data-group): a no-move tap selects the group (tap again to
                  clear); a drag pans the canvas. The ▾ grip collapses/expands;
                  children on top keep their own handlers. */}
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
          const isAsset = n.kind === "asset";
          const tech = isAsset ? overlay?.tech(n.id) : undefined;
          const toTech = isAsset ? overlay?.transitionedTo(n.id) : undefined;
          const tput = isAsset ? overlay?.throughput(n.id) : undefined;
          const idle = isAsset && !!overlay && tech == null;
          const sub = isAsset ? (tech ? (toTech ? `⇄ ${tech}` : tech) : n.level || "idle") : n.level || "group";
          const isSel = selectedId === n.id;
          const stroke = toTech ? "var(--warn)" : isSel ? "var(--brand)" : undefined;
          // White, slightly translucent fill so a flow line passing BEHIND the box
          // reads as dimmed (the box stays in front and legible).
          const fill = isSel ? "var(--brand-fill)" : "var(--surface)";
          return (
            <g
              key={`n-${n.id}`}
              data-node={n.id}
              className={`topo-node ${isAsset ? "topo-commodity" : "topo-process"}`}
              transform={`translate(${n.x},${n.y})`}
              opacity={idle ? 0.45 : 1}
              style={{ cursor: "pointer" }}
            >
              <rect width={n.w} height={n.h} rx={3} fill={fill} fillOpacity={isSel ? 1 : 0.92} stroke={stroke} strokeWidth={isSel || toTech ? 2.5 : undefined} />
              <text className="topo-kind" x={8} y={14}>{isAsset ? "asset" : !editable && n.collapsed ? "group ▸" : "group"}</text>
              {tput != null && <text className="topo-kind" x={n.w - 8} y={14} textAnchor="end">{fmtVal(tput)}</text>}
              <text className="topo-label" x={8} y={31}>{clip(n.label, 22)}</text>
              <text className="topo-sub" x={8} y={46} fill={toTech ? "var(--warn-text)" : undefined}>{clip(sub, 24)}</text>
              {/* top-right grip — expand this collapsed group (the body click selects). */}
              {editable && n.kind === "group" && n.collapsed && (
                <g
                  onPointerDown={(e) => e.stopPropagation()}
                  onPointerUp={(e) => { e.stopPropagation(); toggle(n.id); }}
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

        {/* EDGE LABELS — horizontal commodity text next to each connector (off by
            default; the "Commodity" toggle shows them). Hover still works either way. */}
        {showCommodity &&
          placedLabels.map((L) => (
            <text key={L.key} x={L.tx} y={L.by + LABEL_LH - 2} fontSize={9} fill={L.active ? "var(--text)" : "var(--muted)"} textAnchor={L.ta} style={{ pointerEvents: "none" }}>
              {L.lines.map((l, i) => (<tspan key={i} x={L.tx} dy={i ? LABEL_LH : 0}>{l}</tspan>))}
            </text>
          ))}

        {/* interactive hit-paths ON TOP of the boxes — so hovering a flow line shows
            its popup even where the line runs behind a box. */}
        {edgeViews.map(({ e, d }) => {
          const sel = editable && e.rowIndex >= 0 && selEdge === e.rowIndex;
          const onHover = (ev: React.MouseEvent) =>
            setHover({ x: ev.clientX, y: ev.clientY, from: e.from, to: e.to, commodities: e.commodities, lag: e.lag });
          return (
            <path
              key={`eh-${edgeKey(e)}`}
              d={d}
              fill="none"
              stroke="transparent"
              strokeWidth={14}
              style={{ cursor: "pointer" }}
              onMouseEnter={onHover}
              onMouseMove={onHover}
              onMouseLeave={() => setHover(null)}
              // Don't let the press reach the SVG (it would clear the selection /
              // pan); the click below toggles this edge's selection.
              onPointerDown={(ev) => ev.stopPropagation()}
              onClick={editable && e.rowIndex >= 0 ? () => setSelEdge(sel ? null : e.rowIndex) : undefined}
            />
          );
        })}

        {/* edit / delete controls for the selected edge (top layer, clickable) */}
        {editable &&
          selEdge != null &&
          edgeViews
            .filter((v) => v.e.rowIndex === selEdge)
            .map(({ e, poly }) => {
              const m = poly[Math.floor(poly.length / 2)];
              return (
                <g key={`ec-${edgeKey(e)}`}>
                  {onEditLink && (
                    <g style={{ cursor: "pointer" }} onPointerDown={(ev) => ev.stopPropagation()} onClick={(ev) => setForm({ from: e.from, to: e.to, sx: ev.clientX, sy: ev.clientY, editRowIndex: e.rowIndex, commodity: e.commodity, lag: e.lag })}>
                      <circle cx={m.x - 11} cy={m.y} r={8} fill="var(--brand)" />
                      <text x={m.x - 11} y={m.y + 1} fontSize={9} fill="#fff" textAnchor="middle" dominantBaseline="middle">✎</text>
                    </g>
                  )}
                  {onDeleteLink && (
                    <g style={{ cursor: "pointer" }} onPointerDown={(ev) => ev.stopPropagation()} onClick={() => { onDeleteLink(e.rowIndex); setSelEdge(null); }}>
                      <circle cx={m.x + 11} cy={m.y} r={8} fill="var(--danger)" />
                      <text x={m.x + 11} y={m.y + 1} fontSize={10} fill="#fff" textAnchor="middle" dominantBaseline="middle">✕</text>
                    </g>
                  )}
                </g>
              );
            })}
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
            if (form.editRowIndex != null) onEditLink?.(form.editRowIndex, commodity, lag);
            else onAddLink?.(form.from, form.to, commodity, lag);
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
        Min/max offtake is set per asset in the asset popup (per provider asset).
      </p>
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
        <button className="ghost" onClick={onCancel}>cancel</button>
        <button className="run-button" disabled={!commodity} onClick={() => onConfirm(commodity, lag)}>{editing ? "✓ update" : "＋ link"}</button>
      </div>
    </div>
  );
}
