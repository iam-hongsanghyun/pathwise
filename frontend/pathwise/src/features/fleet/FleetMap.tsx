// Presentational world map for the Fleet designer. Renders coastlines, graticule,
// geodesic routes and draggable port markers — all through the SAME d3 projection,
// so everything is aligned by construction. Zoom/pan is done by moving the SVG
// viewBox (so geometry stays vector-crisp); markers + labels are counter-scaled by
// the zoom factor so they keep a constant on-screen size. Client px are converted to
// the current viewBox window before projection.invert (the SVG is width:100%).

import { useEffect, useRef, useState } from "react";
import type { GeoProjection } from "d3-geo";
import { GRATICULE, LAND, MAP_H, MAP_W, geoPath } from "./basemap";
import { NODE_DRAG_TYPE } from "./fleetGraph";

export interface MapPort {
  id: string;
  label: string;
  lon: number;
  lat: number;
}
export interface MapRoute {
  process: string;
  from: { lon: number; lat: number };
  to: { lon: number; lat: number };
  blocked: boolean;
  alt: boolean;
  /** The real sea/land polyline ([lon,lat]…). Absent ⇒ straight fallback. */
  path?: [number, number][];
}

interface View {
  x: number;
  y: number;
  w: number;
  h: number;
}
const FULL_VIEW: View = { x: 0, y: 0, w: MAP_W, h: MAP_H };
const ASPECT = MAP_H / MAP_W;
const MIN_W = MAP_W / 16; // 16× max zoom-in

export function FleetMap({
  projection,
  ports,
  routes,
  selId,
  pendingFrom,
  onMovePort,
  onClickPort,
  onDropNode,
  onSelectRoute,
  onBackground,
}: {
  projection: GeoProjection;
  ports: MapPort[];
  routes: MapRoute[];
  selId: string | null;
  pendingFrom: string | null;
  onMovePort: (id: string, lon: number, lat: number) => void;
  onClickPort: (id: string) => void;
  /** A Facility endpoint dragged from the rail was dropped here — give it a location. */
  onDropNode?: (id: string, lon: number, lat: number) => void;
  onSelectRoute: (proc: string) => void;
  onBackground: () => void;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ id: string; moved: boolean } | null>(null);
  const pan = useRef<{ cx: number; cy: number; view: View; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const [view, setView] = useState<View>(FULL_VIEW);
  const path = geoPath(projection);
  const d = (obj: Parameters<typeof path>[0]) => path(obj) ?? undefined;
  const k = MAP_W / view.w; // zoom factor (1 = 100% / fit)

  const clamp = (v: View): View => {
    const w = Math.min(MAP_W, Math.max(MIN_W, v.w));
    const h = w * ASPECT;
    return {
      w,
      h,
      x: Math.min(MAP_W - w, Math.max(0, v.x)),
      y: Math.min(MAP_H - h, Math.max(0, v.y)),
    };
  };
  // Zoom by `factor` (<1 = in, >1 = out), keeping the viewBox point (fx,fy) fixed.
  const zoomTo = (factor: number, fx: number, fy: number) =>
    setView((v) => {
      const w = Math.min(MAP_W, Math.max(MIN_W, v.w * factor));
      const h = w * ASPECT;
      return clamp({ w, h, x: fx - (fx - v.x) * (w / v.w), y: fy - (fy - v.y) * (h / v.h) });
    });
  // Zoom about the current viewBox centre — computed inside the updater so it stays
  // correct even across rapid clicks (no stale closure).
  const zoomCenter = (factor: number) =>
    setView((v) => {
      const fx = v.x + v.w / 2;
      const fy = v.y + v.h / 2;
      const w = Math.min(MAP_W, Math.max(MIN_W, v.w * factor));
      const h = w * ASPECT;
      return clamp({ w, h, x: fx - (fx - v.x) * (w / v.w), y: fy - (fy - v.y) * (h / v.h) });
    });

  // client px → current viewBox coords (the SVG is width:100%, so px ≠ viewBox units).
  const toViewBox = (clientX: number, clientY: number): [number, number] | null => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return null;
    return [view.x + ((clientX - rect.left) / rect.width) * view.w, view.y + ((clientY - rect.top) / rect.height) * view.h];
  };
  const toLonLat = (clientX: number, clientY: number): [number, number] | null => {
    const vb = toViewBox(clientX, clientY);
    if (!vb) return null;
    const ll = projection.invert?.(vb);
    if (!ll || !Number.isFinite(ll[0]) || !Number.isFinite(ll[1])) return null;
    return [Math.round(ll[0] * 100) / 100, Math.round(ll[1] * 100) / 100];
  };

  // Wheel zoom — native + non-passive so we can preventDefault (no page scroll).
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const vb = toViewBox(e.clientX, e.clientY);
      if (vb) zoomTo(e.deltaY < 0 ? 0.85 : 1 / 0.85, vb[0], vb[1]);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  const onPointerDownBg = (e: React.PointerEvent) => {
    // Pan only from the empty map: ports stop propagation; ignore route lines so
    // their click still selects.
    const t = e.target as Element;
    if (t.classList?.contains("fleet-route")) return;
    pan.current = { cx: e.clientX, cy: e.clientY, view, moved: false };
    svgRef.current?.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (drag.current) {
      drag.current.moved = true;
      const ll = toLonLat(e.clientX, e.clientY);
      if (ll) onMovePort(drag.current.id, ll[0], ll[1]);
      return;
    }
    if (pan.current) {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return;
      pan.current.moved = true;
      const dx = ((e.clientX - pan.current.cx) / rect.width) * pan.current.view.w;
      const dy = ((e.clientY - pan.current.cy) / rect.height) * pan.current.view.h;
      setView(clamp({ ...pan.current.view, x: pan.current.view.x - dx, y: pan.current.view.y - dy }));
    }
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (drag.current?.moved || pan.current?.moved) suppressClick.current = true;
    drag.current = null;
    pan.current = null;
    try { svgRef.current?.releasePointerCapture(e.pointerId); } catch { /* not captured */ }
  };

  return (
    <div className="fleet-map-wrap">
      <svg
        ref={svgRef}
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        className={`fleet-map${pendingFrom ? " is-connecting" : ""}`}
        onPointerDown={onPointerDownBg}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onDragOver={(e) => {
          // Accept our own chip drag OR a TreeExplorer row drag (text/plain = node id).
          if (onDropNode && (e.dataTransfer.types.includes(NODE_DRAG_TYPE) || e.dataTransfer.types.includes("text/plain")))
            e.preventDefault();
        }}
        onDrop={(e) => {
          if (!onDropNode) return;
          const id = e.dataTransfer.getData(NODE_DRAG_TYPE) || e.dataTransfer.getData("text/plain");
          if (!id) return;
          e.preventDefault();
          const ll = toLonLat(e.clientX, e.clientY);
          if (ll) onDropNode(id, ll[0], ll[1]);
        }}
        onClick={() => { if (suppressClick.current) { suppressClick.current = false; return; } onBackground(); }}
      >
        <path className="fleet-ocean" d={d({ type: "Sphere" })} />
        <path className="fleet-graticule" d={d(GRATICULE)} />
        {LAND.features.map((f, i) => (
          <path key={i} className="fleet-land" d={d(f)} />
        ))}

        {routes.map((r) => {
          const line = r.path && r.path.length > 1 ? r.path : [[r.from.lon, r.from.lat], [r.to.lon, r.to.lat]];
          const dd = d({ type: "LineString", coordinates: line });
          if (!dd) return null;
          const cls = `fleet-route${selId === r.process ? " is-selected" : ""}${r.blocked ? " is-blocked" : r.alt ? " is-alt" : ""}`;
          return (
            <path key={r.process} className={cls} d={dd}
              onClick={(e) => { e.stopPropagation(); onSelectRoute(r.process); }} />
          );
        })}

        {ports.map((p) => {
          const xy = projection([p.lon, p.lat]);
          if (!xy) return null;
          const cls = `fleet-port${selId === p.id ? " is-selected" : ""}${pendingFrom === p.id ? " is-pending" : ""}`;
          return (
            <g key={p.id} className={cls}
              onPointerDown={(e) => { e.stopPropagation(); svgRef.current?.setPointerCapture(e.pointerId); drag.current = { id: p.id, moved: false }; }}
              onClick={(e) => { e.stopPropagation(); if (suppressClick.current) { suppressClick.current = false; return; } onClickPort(p.id); }}
            >
              <circle className="fleet-port-dot" cx={xy[0]} cy={xy[1]} r={(pendingFrom === p.id ? 7 : 5) / k} />
              <text className="fleet-port-label" x={xy[0] + 8 / k} y={xy[1] + 4 / k} style={{ fontSize: `${11 / k}px` }}>{p.label}</text>
            </g>
          );
        })}
      </svg>

      <div className="fleet-zoom">
        <button type="button" title="Zoom in" aria-label="Zoom in" onClick={() => zoomCenter(1 / 1.5)}>＋</button>
        <button type="button" className="fleet-zoom-reset" title="Reset to 100%" aria-label="Reset zoom to 100%" onClick={() => setView(FULL_VIEW)}>{Math.round(k * 100)}%</button>
        <button type="button" title="Zoom out" aria-label="Zoom out" disabled={k <= 1} onClick={() => zoomCenter(1.5)}>－</button>
      </div>
    </div>
  );
}
