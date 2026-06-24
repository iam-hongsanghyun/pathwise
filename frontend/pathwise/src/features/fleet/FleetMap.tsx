// Presentational world map for the Fleet designer. Renders coastlines, graticule,
// geodesic routes and draggable port markers — all through the SAME d3 projection,
// so everything is aligned by construction. Drag uses pointer capture + a moved
// flag (so a drag never also lays a route) and converts client px → viewBox units
// before projection.invert (the SVG is width:100%, so px ≠ viewBox units).

import { useRef } from "react";
import type { GeoProjection } from "d3-geo";
import { GRATICULE, LAND, MAP_H, MAP_W, geoPath } from "./basemap";

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

export function FleetMap({
  projection,
  ports,
  routes,
  selId,
  pendingFrom,
  onMovePort,
  onClickPort,
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
  onSelectRoute: (proc: string) => void;
  onBackground: () => void;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ id: string; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const path = geoPath(projection);
  const d = (obj: Parameters<typeof path>[0]) => path(obj) ?? undefined;

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    drag.current.moved = true;
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const vx = ((e.clientX - rect.left) / rect.width) * MAP_W;
    const vy = ((e.clientY - rect.top) / rect.height) * MAP_H;
    const ll = projection.invert?.([vx, vy]);
    if (!ll || !Number.isFinite(ll[0]) || !Number.isFinite(ll[1])) return;
    onMovePort(drag.current.id, Math.round(ll[0] * 100) / 100, Math.round(ll[1] * 100) / 100);
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (drag.current?.moved) suppressClick.current = true;
    drag.current = null;
    try { svgRef.current?.releasePointerCapture(e.pointerId); } catch { /* not captured */ }
  };

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${MAP_W} ${MAP_H}`}
      className={`fleet-map${pendingFrom ? " is-connecting" : ""}`}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
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
            <circle className="fleet-port-dot" cx={xy[0]} cy={xy[1]} r={pendingFrom === p.id ? 7 : 5} />
            <text className="fleet-port-label" x={xy[0] + 8} y={xy[1] + 4}>{p.label}</text>
          </g>
        );
      })}
    </svg>
  );
}
