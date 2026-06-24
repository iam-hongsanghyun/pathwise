// World basemap + projection for the Fleet map. d3-geo is used ONLY for projection
// + path math (no d3 DOM selection) — everything renders through React/SVG. The
// world outline is world-atlas TopoJSON, converted to GeoJSON ONCE here (skipping
// feature() leaves the map blank — the classic symptom). geoEquirectangular is
// chosen because it is exactly + cheaply invertible everywhere on-canvas, which is
// what keeps port-dragging correct; the 2:1 viewBox matches its natural ratio.

import { geoEquirectangular, geoGraticule10, geoPath, type GeoProjection } from "d3-geo";
import type { FeatureCollection } from "geojson";
import { feature } from "topojson-client";
// world-atlas ships TopoJSON; vite imports JSON natively.
import worldTopo from "world-atlas/countries-110m.json";

export const MAP_W = 960;
export const MAP_H = 480; // 2:1 — equirectangular's natural aspect ratio

export const MODES = [
  { value: "sea", label: "Sea (searoute)" },
  { value: "road", label: "Road (×1.4)" },
  { value: "rail", label: "Rail (×1.2)" },
  { value: "air", label: "Air" },
];

// TopoJSON → GeoJSON, once at module scope.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const topo = worldTopo as any;
export const LAND = feature(topo, topo.objects.countries) as unknown as FeatureCollection;
export const GRATICULE = geoGraticule10();

/** A projection fitted to the canvas sphere — the SINGLE source of forward (project)
 *  and inverse (drag) coordinates, so coastlines, ports and routes always align. */
export function makeProjection(w = MAP_W, h = MAP_H): GeoProjection {
  return geoEquirectangular().fitSize([w, h], { type: "Sphere" });
}

export { geoPath };
