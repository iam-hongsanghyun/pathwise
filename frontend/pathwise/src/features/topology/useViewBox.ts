// Reusable SVG viewBox hook: wheel zoom (center-preserving) + background pan.
// Mirrors the proven logic in TopologyCanvas.tsx but as a standalone hook so
// HierarchyMap (and future canvases) can share it without touching TopologyCanvas.

import { useCallback, useRef, useState } from "react";

export interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface NodePos {
  x: number;
  y: number;
}

/** Zoom factor per wheel tick — matches TopologyCanvas. */
const ZOOM_FACTOR = 1.12;

/** Minimum canvas dimensions to prevent collapsing to zero. */
const MIN_DIM = 50;

export interface UseViewBoxResult {
  vb: ViewBox;
  setVb: React.Dispatch<React.SetStateAction<ViewBox>>;
  /** Wheel handler: zooms around the cursor position. Mutates viewBox only;
   *  never triggers a level change. Call as `onWheel={onWheel}` on the SVG. */
  onWheel: (e: React.WheelEvent) => void;
  /** Pointer-down handler for background pan — call on the SVG element. */
  onPanStart: (e: React.PointerEvent) => void;
  /** Pointer-move handler — call on the SVG element. */
  onPanMove: (e: React.PointerEvent) => void;
  /** Pointer-up handler — call on the SVG element. */
  onPanEnd: () => void;
  /** Convert client (screen) coordinates to SVG world coordinates.
   *  Returns the viewBox origin when the SVG element is not mounted yet. */
  toWorld: (clientX: number, clientY: number, svgEl: SVGSVGElement | null) => NodePos;
  /** Frame a set of node positions so they fill the canvas with padding.
   *  Call after `levelGraph` produces a new set of children. */
  fit: (positions: NodePos[], nodeW?: number, nodeH?: number) => void;
}

export function useViewBox(initial: ViewBox = { x: 0, y: 0, w: 1200, h: 700 }): UseViewBoxResult {
  const [vb, setVb] = useState<ViewBox>(initial);

  // Track an active pan gesture (start clientX/Y + the viewBox snapshot at
  // pan start).  Null when no pan is in progress.
  const pan = useRef<{ startX: number; startY: number; vb: ViewBox } | null>(null);
  // Hold a ref to the SVG for coordinate math during pan (we can't rely on the
  // caller passing the svgEl through every event because pointer capture means
  // moves fire on the SVG even when the pointer has left).
  const svgRef = useRef<SVGSVGElement | null>(null);

  const toWorld = useCallback(
    (clientX: number, clientY: number, svgEl: SVGSVGElement | null): NodePos => {
      const el = svgEl ?? svgRef.current;
      // getScreenCTM() maps the (post-viewBox, post-preserveAspectRatio) user
      // space to the screen — its inverse turns the cursor into world units
      // EXACTLY, including the letterbox offset/scale from `meet`. The rect
      // math below only holds for preserveAspectRatio="none" and is a fallback.
      const ctm = el?.getScreenCTM?.();
      if (el && ctm) {
        const p = new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse());
        return { x: p.x, y: p.y };
      }
      const rect = el?.getBoundingClientRect();
      if (!rect || rect.width < 1 || rect.height < 1) return { x: vb.x, y: vb.y };
      return {
        x: vb.x + ((clientX - rect.left) / rect.width) * vb.w,
        y: vb.y + ((clientY - rect.top) / rect.height) * vb.h,
      };
    },
    [vb],
  );

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      const svgEl = e.currentTarget as SVGSVGElement;
      svgRef.current = svgEl;
      const at = toWorld(e.clientX, e.clientY, svgEl); // world point under the cursor
      const k = e.deltaY > 0 ? ZOOM_FACTOR : 1 / ZOOM_FACTOR;
      setVb((v) => ({
        x: at.x - (at.x - v.x) * k,
        y: at.y - (at.y - v.y) * k,
        w: Math.max(MIN_DIM, v.w * k),
        h: Math.max(MIN_DIM, v.h * k),
      }));
    },
    [toWorld],
  );

  const onPanStart = useCallback(
    (e: React.PointerEvent) => {
      const svgEl = e.currentTarget as SVGSVGElement;
      svgRef.current = svgEl;
      try {
        svgEl.setPointerCapture(e.pointerId);
      } catch {
        // synthetic events may carry no active pointer — capture is best-effort
      }
      pan.current = { startX: e.clientX, startY: e.clientY, vb };
    },
    [vb],
  );

  const onPanMove = useCallback((e: React.PointerEvent) => {
    const g = pan.current;
    if (!g) return;
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || rect.width < 1 || rect.height < 1) return;
    // Uniform scale (preserveAspectRatio="meet" fits the smaller ratio), so a
    // screen-pixel drag maps to the same world delta on both axes.
    const scale = Math.min(rect.width / g.vb.w, rect.height / g.vb.h);
    const sx = (g.startX - e.clientX) / scale;
    const sy = (g.startY - e.clientY) / scale;
    setVb({ ...g.vb, x: g.vb.x + sx, y: g.vb.y + sy });
  }, []);

  const onPanEnd = useCallback(() => {
    pan.current = null;
  }, []);

  const fit = useCallback((positions: NodePos[], nodeW = 172, nodeH = 56) => {
    if (positions.length === 0) return;
    const xs = positions.map((p) => p.x);
    const ys = positions.map((p) => p.y);
    const pad = 60;
    const x = Math.min(...xs) - pad;
    const y = Math.min(...ys) - pad;
    const w = Math.max(...xs) + nodeW - x + pad;
    const h = Math.max(...ys) + nodeH - y + pad;
    setVb({ x, y, w: Math.max(w, 600), h: Math.max(h, 400) });
  }, []);

  return { vb, setVb, onWheel, onPanStart, onPanMove, onPanEnd, toWorld, fit };
}
