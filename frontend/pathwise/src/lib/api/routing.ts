// Route-path API client — the drawable polyline for a transport route, so the map
// follows real sea lanes (searoute, via Suez/Panama) instead of a great-circle over
// land. POST /api/route-path → [[lon, lat], …].

export type LonLat = [number, number];

export async function routePath(
  from: { lon: number; lat: number },
  to: { lon: number; lat: number },
  mode: string,
  avoid: string[] = [],
): Promise<LonLat[]> {
  const resp = await fetch("/api/route-path", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      from_lon: from.lon,
      from_lat: from.lat,
      to_lon: to.lon,
      to_lat: to.lat,
      mode,
      avoid,
    }),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  const data = (await resp.json()) as { coordinates: LonLat[] };
  return data.coordinates;
}

// ── Chokepoint exposure (corridor sensitivity) ─────────────────────────────────
// For each maritime corridor: which sea routes traverse it and how far each would
// detour (or whether it is stranded) if it closed. Pure geometry — the annual
// closure probability is overlaid client-side, so prob edits need no re-fetch.

export interface ExposureRouteInput {
  id: string;
  from: { lon: number; lat: number };
  to: { lon: number; lat: number };
  mode?: string;
}

export interface AffectedRoute {
  route_id: string;
  base_km: number;
  /** null ⇒ no alternative (the route is stranded if this corridor closes). */
  detour_km: number | null;
  delta_km: number | null;
  delta_pct: number | null;
}

export interface CorridorExposure {
  id: string;
  n_routes: number;
  n_stranded: number;
  total_delta_km: number;
  routes: AffectedRoute[];
}

export async function routeExposure(
  routes: ExposureRouteInput[],
  corridors: { id: string; prob: number }[],
): Promise<CorridorExposure[]> {
  const resp = await fetch("/api/route-exposure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      routes: routes.map((r) => ({
        id: r.id,
        from_lon: r.from.lon,
        from_lat: r.from.lat,
        to_lon: r.to.lon,
        to_lat: r.to.lat,
        mode: r.mode ?? "sea",
      })),
      corridors,
    }),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  const data = (await resp.json()) as { corridors: CorridorExposure[] };
  return data.corridors;
}
