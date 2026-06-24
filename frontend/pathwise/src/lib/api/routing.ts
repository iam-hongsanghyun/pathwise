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
