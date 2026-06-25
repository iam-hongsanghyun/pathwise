// World map for the Fleet designer. Two views, one projection abstraction:
//   • FLAT  — geoEquirectangular, rendered as THREE horizontal copies so panning is
//             CONTINUOUS (a route never falls off an edge); polylines are split at the
//             antimeridian so a trans-Pacific lane doesn't streak across the map.
//   • GLOBE — geoOrthographic (an actual sphere); drag to rotate, wheel to zoom. The
//             back hemisphere is clipped, so dateline wrapping simply doesn't exist.
// Routes carry hover tooltips (distance, from→to, fleets, flow) and an optional
// dotted ALTERNATIVE path (the detour a chokepoint closure would force).

import { useEffect, useMemo, useRef, useState } from "react";
import { geoDistance, geoEquirectangular, geoOrthographic, type GeoProjection } from "d3-geo";
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
  /** The detour polyline if a chokepoint on this lane closed — drawn dotted. */
  altPath?: [number, number][];
  // hover metadata
  fromLabel?: string;
  toLabel?: string;
  mode?: string;
  flow?: string;
  distanceKm?: number;
  fleets?: string[];
  /** Maritime chokepoints this lane crosses that carry a risk/toll (labels). */
  chokepoints?: string[];
  /** Σ per-voyage toll over those chokepoints (in the model currency). */
  tollPerVoyage?: number;
}

interface View {
  x: number;
  y: number;
  w: number;
  h: number;
}
const FULL_VIEW: View = { x: 0, y: 0, w: MAP_W, h: MAP_H };
const ASPECT = MAP_H / MAP_W;
const MIN_W = MAP_W / 16; // 16× max zoom-in (flat)
const OFFSETS = [-MAP_W, 0, MAP_W]; // the three horizontal world copies (flat)
const GLOBE_R = (MAP_H / 2) * 0.92; // base sphere radius
const GLOBE_MIN = 0.6;
const GLOBE_MAX = 8;

// Break a [lon,lat] polyline wherever consecutive points jump > 180° of longitude
// (an antimeridian crossing), so the flat projection doesn't draw a streak across.
function splitDateline(line: [number, number][]): [number, number][][] {
  const out: [number, number][][] = [];
  let cur: [number, number][] = [];
  for (let i = 0; i < line.length; i++) {
    if (i > 0 && Math.abs(line[i][0] - line[i - 1][0]) > 180) {
      if (cur.length > 1) out.push(cur);
      cur = [];
    }
    cur.push(line[i]);
  }
  if (cur.length > 1) out.push(cur);
  return out;
}

export function FleetMap({
  ports,
  routes,
  selId,
  pendingFrom,
  currency = "",
  onMovePort,
  onClickPort,
  onDropNode,
  onSelectRoute,
  onBackground,
}: {
  ports: MapPort[];
  routes: MapRoute[];
  selId: string | null;
  pendingFrom: string | null;
  currency?: string;
  onMovePort: (id: string, lon: number, lat: number) => void;
  onClickPort: (id: string) => void;
  /** A Facility node dragged from the rail was dropped here — give it a location. */
  onDropNode?: (id: string, lon: number, lat: number) => void;
  onSelectRoute: (proc: string) => void;
  onBackground: () => void;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ id: string; moved: boolean } | null>(null);
  const pan = useRef<{ cx: number; cy: number; view: View; rot: [number, number]; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const [mode, setMode] = useState<"flat" | "globe">("flat");
  const [view, setView] = useState<View>(FULL_VIEW); // flat viewBox
  const [rot, setRot] = useState<[number, number]>([-10, -12]); // globe rotation [λ, φ]
  const [gScale, setGScale] = useState(1); // globe zoom multiplier
  const [hover, setHover] = useState<{ x: number; y: number; r: MapRoute } | null>(null);

  const projection: GeoProjection = useMemo(() => {
    if (mode === "globe") {
      return geoOrthographic()
        .translate([MAP_W / 2, MAP_H / 2])
        .scale(GLOBE_R * gScale)
        .rotate([rot[0], rot[1]])
        .clipAngle(90);
    }
    return geoEquirectangular().fitSize([MAP_W, MAP_H], { type: "Sphere" });
  }, [mode, rot, gScale]);

  const path = geoPath(projection);
  const d = (obj: Parameters<typeof path>[0]) => path(obj) ?? undefined;
  const k = mode === "globe" ? gScale : MAP_W / view.w; // on-screen → counter-scale factor
  // The globe centre in lon/lat, for back-hemisphere culling of point markers.
  const center: [number, number] = [-rot[0], -rot[1]];

  const clamp = (v: View): View => {
    const w = Math.min(MAP_W, Math.max(MIN_W, v.w));
    const h = w * ASPECT;
    return { w, h, x: v.x, y: Math.min(MAP_H - h, Math.max(0, v.y)) }; // x is FREE (wrap), y clamped
  };
  // Keep x within one world width so the three copies always cover the viewport.
  const wrapX = (v: View): View => {
    let x = v.x % MAP_W;
    if (x < 0) x += MAP_W;
    return { ...v, x };
  };
  const zoomTo = (factor: number, fx: number, fy: number) =>
    setView((v) => {
      const w = Math.min(MAP_W, Math.max(MIN_W, v.w * factor));
      const h = w * ASPECT;
      return wrapX(clamp({ w, h, x: fx - (fx - v.x) * (w / v.w), y: fy - (fy - v.y) * (h / v.h) }));
    });
  const zoomCenter = (factor: number) => {
    if (mode === "globe") {
      setGScale((s) => Math.min(GLOBE_MAX, Math.max(GLOBE_MIN, s * factor)));
      return;
    }
    setView((v) => {
      const fx = v.x + v.w / 2;
      const fy = v.y + v.h / 2;
      const w = Math.min(MAP_W, Math.max(MIN_W, v.w * factor));
      const h = w * ASPECT;
      return wrapX(clamp({ w, h, x: fx - (fx - v.x) * (w / v.w), y: fy - (fy - v.y) * (h / v.h) }));
    });
  };

  // client px → viewBox user coords via the SVG's own transform. getScreenCTM honours
  // the viewBox AND preserveAspectRatio letterboxing (the panel isn't 2:1, so the map
  // is letterboxed) — manual rect math would land the cursor off by the letterbox band.
  const toViewBox = (clientX: number, clientY: number): [number, number] | null => {
    const svg = svgRef.current;
    const ctm = svg?.getScreenCTM();
    if (!svg || !ctm) return null;
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const p = pt.matrixTransform(ctm.inverse());
    return [p.x, p.y];
  };
  const toLonLat = (clientX: number, clientY: number): [number, number] | null => {
    const vb = toViewBox(clientX, clientY);
    if (!vb) return null;
    const ll = projection.invert?.(vb);
    if (!ll || !Number.isFinite(ll[0]) || !Number.isFinite(ll[1])) return null;
    // Wrap longitude into [-180,180]: a continuous flat pan can read into copy +1.
    const lon = (((ll[0] + 180) % 360) + 360) % 360 - 180;
    return [Math.round(lon * 100) / 100, Math.round(ll[1] * 100) / 100];
  };

  // Wheel zoom — native + non-passive so we can preventDefault (no page scroll).
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (mode === "globe") {
        setGScale((s) => Math.min(GLOBE_MAX, Math.max(GLOBE_MIN, s * (e.deltaY < 0 ? 1 / 0.85 : 0.85))));
        return;
      }
      const vb = toViewBox(e.clientX, e.clientY);
      if (vb) zoomTo(e.deltaY < 0 ? 0.85 : 1 / 0.85, vb[0], vb[1]);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, mode, gScale]);

  const onPointerDownBg = (e: React.PointerEvent) => {
    const t = e.target as Element;
    if (t.classList?.contains("fleet-route")) return; // let the route handle the click
    pan.current = { cx: e.clientX, cy: e.clientY, view, rot, moved: false };
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
      if (mode === "globe") {
        // Drag rotates the globe; speed scales with the on-screen sphere size.
        const speed = 90 / (GLOBE_R * gScale);
        const dx = (e.clientX - pan.current.cx) * speed;
        const dy = (e.clientY - pan.current.cy) * speed;
        const [λ0, φ0] = pan.current.rot;
        setRot([λ0 + dx, Math.max(-90, Math.min(90, φ0 - dy))]);
        return;
      }
      const dx = ((e.clientX - pan.current.cx) / rect.width) * pan.current.view.w;
      const dy = ((e.clientY - pan.current.cy) / rect.height) * pan.current.view.h;
      setView(wrapX(clamp({ ...pan.current.view, x: pan.current.view.x - dx, y: pan.current.view.y - dy })));
    }
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (drag.current?.moved || pan.current?.moved) suppressClick.current = true;
    drag.current = null;
    pan.current = null;
    try { svgRef.current?.releasePointerCapture(e.pointerId); } catch { /* not captured */ }
  };

  const resetView = () => { setView(FULL_VIEW); setRot([-10, -12]); setGScale(1); };

  // ── Render helpers ───────────────────────────────────────────────────────────
  const routeCls = (r: MapRoute) =>
    `fleet-route${selId === r.process ? " is-selected" : ""}${r.blocked ? " is-blocked" : r.alt ? " is-alt" : ""}`;
  const onRouteHover = (r: MapRoute) => (e: React.MouseEvent) => {
    const rect = svgRef.current?.parentElement?.getBoundingClientRect();
    setHover({ x: e.clientX - (rect?.left ?? 0), y: e.clientY - (rect?.top ?? 0), r });
  };

  // One world copy (flat: called per offset; globe: called once with dx=0).
  const worldLayers = (dx: number) => (
    <g key={dx} transform={dx ? `translate(${dx},0)` : undefined}>
      <path className="fleet-ocean" d={d({ type: "Sphere" })} />
      <path className="fleet-graticule" d={d(GRATICULE)} />
      {LAND.features.map((f, i) => (
        <path key={i} className="fleet-land" d={d(f)} />
      ))}
      {/* Alternative (detour) paths — dotted, drawn under the base lines. Each segment
          gets a wide invisible hit path so it's easy to hover/click near the line. */}
      {routes.map((r) => {
        if (!r.altPath || r.altPath.length < 2) return null;
        const segs = mode === "globe" ? [r.altPath] : splitDateline(r.altPath);
        return segs.map((seg, i) => {
          const dd = d({ type: "LineString", coordinates: seg });
          if (!dd) return null;
          return (
            <g key={`${r.process}-alt-${i}`} onMouseMove={onRouteHover(r)} onMouseLeave={() => setHover(null)}
              onClick={(e) => { e.stopPropagation(); onSelectRoute(r.process); }}>
              <path className="fleet-route-hit" d={dd} />
              <path className={`fleet-route is-alt-path${selId === r.process ? " is-selected" : ""}`} d={dd} />
            </g>
          );
        });
      })}
      {/* Base routes (+ a wide invisible hit path under each segment). */}
      {routes.map((r) => {
        const line = r.path && r.path.length > 1 ? r.path : [[r.from.lon, r.from.lat], [r.to.lon, r.to.lat]] as [number, number][];
        const segs = mode === "globe" ? [line] : splitDateline(line);
        return segs.map((seg, i) => {
          const dd = d({ type: "LineString", coordinates: seg });
          if (!dd) return null;
          return (
            <g key={`${r.process}-${i}`} onMouseMove={onRouteHover(r)} onMouseLeave={() => setHover(null)}
              onClick={(e) => { e.stopPropagation(); onSelectRoute(r.process); }}>
              <path className="fleet-route-hit" d={dd} />
              <path className={routeCls(r)} d={dd} />
            </g>
          );
        });
      })}
      {/* Ports. */}
      {ports.map((p) => {
        const xy = projection([p.lon, p.lat]);
        if (!xy) return null;
        if (mode === "globe" && geoDistance([p.lon, p.lat], center) > Math.PI / 2) return null; // back of globe
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
    </g>
  );

  return (
    <div className="fleet-map-wrap">
      <svg
        ref={svgRef}
        viewBox={mode === "globe" ? `0 0 ${MAP_W} ${MAP_H}` : `${view.x} ${view.y} ${view.w} ${view.h}`}
        className={`fleet-map${pendingFrom ? " is-connecting" : ""}${mode === "globe" ? " is-globe" : ""}`}
        onPointerDown={onPointerDownBg}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onDragOver={(e) => {
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
        {mode === "globe" ? worldLayers(0) : OFFSETS.map((dx) => worldLayers(dx))}
      </svg>

      {hover && (() => {
        const r = hover.r;
        const fleets = (r.fleets ?? []).filter(Boolean);
        return (
          <div className="route-tip" style={{ left: Math.min(hover.x + 14, MAP_W * 2), top: hover.y + 14 }}>
            <div className="route-tip-title">{r.fromLabel ?? "?"} → {r.toLabel ?? "?"}</div>
            <table className="route-tip-tbl">
              <tbody>
                {r.distanceKm != null && <tr><td>Distance</td><td>{Math.round(r.distanceKm).toLocaleString()} km</td></tr>}
                {r.mode && <tr><td>Mode</td><td>{r.mode}</td></tr>}
                {r.flow && <tr><td>Cargo</td><td>{r.flow}</td></tr>}
                <tr><td>Fleets</td><td>{fleets.length ? fleets.join(", ") : "any (optimiser)"}</td></tr>
                {r.chokepoints && r.chokepoints.length > 0 && (
                  <tr><td>Chokepoints</td><td>{r.chokepoints.join(", ")}</td></tr>
                )}
                {!!r.tollPerVoyage && r.tollPerVoyage > 0 && (
                  <tr><td>Toll</td><td>{currency ? `${currency} ` : ""}{Math.round(r.tollPerVoyage).toLocaleString()}/voyage</td></tr>
                )}
                {r.altPath && <tr><td>If shut</td><td>reroutes (dotted)</td></tr>}
              </tbody>
            </table>
          </div>
        );
      })()}

      <div className="fleet-zoom">
        <button type="button" title="Zoom in" aria-label="Zoom in" onClick={() => zoomCenter(1 / 1.5)}>＋</button>
        <button type="button" className="fleet-zoom-reset" title="Reset view" aria-label="Reset view" onClick={resetView}>{Math.round(k * 100)}%</button>
        <button type="button" title="Zoom out" aria-label="Zoom out" disabled={mode === "flat" && k <= 1} onClick={() => zoomCenter(1.5)}>－</button>
      </div>
      <div className="fleet-viewtoggle">
        <button type="button" className={mode === "flat" ? "is-active" : ""} title="Flat map (continuous)" onClick={() => setMode("flat")}>Map</button>
        <button type="button" className={mode === "globe" ? "is-active" : ""} title="Globe (rotate to explore)" onClick={() => setMode("globe")}>Globe</button>
      </div>
    </div>
  );
}
