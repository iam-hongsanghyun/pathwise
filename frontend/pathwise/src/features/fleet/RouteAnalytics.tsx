// Read-only analytics map for the solved physical routes. Draws each physicalised
// corridor on the world basemap, weighted by a chosen metric (cargo / ships / fuel /
// emissions), with a YEAR slider and HOVER tooltips showing that route's allocation.
// Emissions are derived from the model's own commodity_impacts (fuel_used × factor) —
// never hardcoded.

import { useEffect, useMemo, useState } from "react";
import { GRATICULE, LAND, MAP_H, MAP_W, geoPath, makeProjection } from "./basemap";
import { buildCoordMap } from "./fleetGraph";
import { routePath } from "../../lib/api/routing";
import type { Row, RunResult, Workbook } from "../../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const n = (v: unknown): number => (v == null || v === "" ? 0 : Number(v) || 0);

type Metric = "cargo" | "ships" | "fuel" | "co2";
const METRICS: { id: Metric; label: string }[] = [
  { id: "cargo", label: "Cargo moved" },
  { id: "ships", label: "Carriers" },
  { id: "fuel", label: "Fuel burned" },
  { id: "co2", label: "Emissions" },
];

interface RouteAgg {
  process: string;
  from: { lon: number; lat: number };
  to: { lon: number; lat: number };
  label: string;
  fleets: { fleet: string; ships: number; cargo: number; fuel: string }[];
  ships: number;
  cargo: number;
  fuelUsed: number;
  fuelName: string;
  emissions: Record<string, number>;
  co2: number;
}

export function RouteAnalytics({ workbook, result }: { workbook: Workbook; result: RunResult }) {
  const projection = useMemo(makeProjection, []);
  const coord = useMemo(() => buildCoordMap(workbook), [workbook]);
  const labelOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const nd of workbook.nodes ?? []) m.set(s(nd.node_id), s(nd.label) || s(nd.node_id));
    return (id: string) => m.get(id) ?? id;
  }, [workbook]);
  // commodity -> {impact: factor} (the model's own factors; never hardcoded here).
  const fuelFactors = useMemo(() => {
    const m = new Map<string, Record<string, number>>();
    for (const r of workbook.commodity_impacts ?? []) {
      const c = s(r.commodity_id);
      if (!c) continue;
      (m.get(c) ?? m.set(c, {}).get(c)!)[s(r.impact_id)] = n(r.factor);
    }
    return m;
  }, [workbook]);
  // process -> {from,to} geography (any route row whose endpoints carry coordinates).
  const geo = useMemo(() => {
    const m = new Map<string, { from: { lon: number; lat: number }; to: { lon: number; lat: number } }>();
    for (const r of workbook.routes ?? []) {
      const from = coord.get(s(r.from_node));
      const to = coord.get(s(r.to_node));
      if (from && to) m.set(s(r.process), { from, to });
    }
    return m;
  }, [workbook, coord]);

  // Blocked corridors (so the drawn lanes reroute to match the solved distances).
  const avoid = useMemo(
    () => (workbook.corridors ?? []).filter((r) => r.blocked === true || s(r.blocked) === "true").map((r) => s(r.corridor)).filter(Boolean),
    [workbook],
  );
  const fleetRows = useMemo(() => (result.outputs.fleet ?? []) as Row[], [result]);
  const years = useMemo(
    () => [...new Set(fleetRows.map((r) => n(r.period)))].sort((a, b) => a - b),
    [fleetRows],
  );
  const [year, setYear] = useState<number | null>(null);
  const activeYear = year ?? years[years.length - 1] ?? 0;
  const [metric, setMetric] = useState<Metric>("cargo");
  const [hover, setHover] = useState<{ x: number; y: number; r: RouteAgg } | null>(null);

  // Aggregate the chosen carriers per route for the active year.
  const routes = useMemo<RouteAgg[]>(() => {
    const by = new Map<string, RouteAgg>();
    for (const r of fleetRows) {
      if (n(r.period) !== activeYear) continue;
      const proc = s(r.process);
      const g = geo.get(proc);
      if (!g) continue; // not a drawable physical route
      let agg = by.get(proc);
      if (!agg) {
        agg = {
          process: proc,
          from: g.from,
          to: g.to,
          label: `${labelOf(s(r.from_node) || "")}`,
          fleets: [],
          ships: 0,
          cargo: 0,
          fuelUsed: 0,
          fuelName: "",
          emissions: {},
          co2: 0,
        };
        by.set(proc, agg);
      }
      const cargo = n(r.throughput);
      const ships = n(r.ships);
      const fuelUsed = n(r.fuel_used);
      const fuel = s(r.fuel);
      agg.fleets.push({ fleet: s(r.fleet), ships, cargo, fuel });
      agg.ships += ships;
      agg.cargo += cargo;
      agg.fuelUsed += fuelUsed;
      agg.fuelName = fuel || agg.fuelName;
      for (const [imp, fac] of Object.entries(fuelFactors.get(fuel) ?? {}))
        agg.emissions[imp] = (agg.emissions[imp] ?? 0) + fuelUsed * fac;
    }
    for (const a of by.values()) a.co2 = a.emissions["co2"] ?? Object.values(a.emissions)[0] ?? 0;
    return [...by.values()];
  }, [fleetRows, activeYear, geo, fuelFactors, labelOf]);

  // Sea polylines (cached by rounded endpoints) so corridors trace real lanes.
  const [paths, setPaths] = useState<Map<string, [number, number][]>>(new Map());
  const keyed = useMemo(
    () =>
      routes.map((r) => ({
        ...r,
        key: `${r.from.lon.toFixed(2)},${r.from.lat.toFixed(2)}|${r.to.lon.toFixed(2)},${r.to.lat.toFixed(2)}|${avoid.join(",")}`,
      })),
    [routes, avoid],
  );
  useEffect(() => {
    const miss = keyed.filter((r) => !paths.has(r.key));
    if (!miss.length) return;
    const t = setTimeout(() => {
      void Promise.all(
        miss.map((r) => routePath(r.from, r.to, "sea", avoid).then((c) => [r.key, c] as const).catch(() => null)),
      ).then((ps) => {
        const ok = ps.filter((p): p is readonly [string, [number, number][]] => p !== null);
        if (ok.length) setPaths((prev) => { const m = new Map(prev); for (const [k, v] of ok) m.set(k, v); return m; });
      });
    }, 200);
    return () => clearTimeout(t);
  }, [keyed, paths, avoid]);

  const valOf = (r: RouteAgg): number =>
    metric === "cargo" ? r.cargo : metric === "ships" ? r.ships : metric === "fuel" ? r.fuelUsed : r.co2;
  const maxVal = Math.max(1e-9, ...keyed.map(valOf));
  const path = geoPath(projection);
  const draw = (obj: Parameters<typeof path>[0]) => path(obj) ?? undefined;
  const fmt = (v: number) => (v >= 1000 ? Math.round(v).toLocaleString() : v.toPrecision(3));

  if (years.length === 0 || geo.size === 0)
    return <p className="muted" style={{ padding: 16 }}>No physical routes in this result. Physicalise a value-chain link in the Fleet tab and re-run.</p>;

  return (
    <>
      <div className="year-slider" style={{ borderTop: "none", borderBottom: "1px solid var(--border)", gap: 14 }}>
        <span className="muted">Year</span>
        <input
          type="range"
          min={0}
          max={Math.max(years.length - 1, 0)}
          value={years.indexOf(activeYear)}
          onChange={(e) => setYear(years[Number(e.target.value)])}
        />
        <strong>{activeYear}</strong>
        <span style={{ flex: 1 }} />
        <span className="muted">Weight by</span>
        <div style={{ display: "flex", gap: 2 }}>
          {METRICS.map((mt) => (
            <button
              key={mt.id}
              className="ghost"
              style={{
                fontSize: "0.72rem",
                padding: "2px 8px",
                color: metric === mt.id ? "var(--brand)" : "var(--muted)",
                fontWeight: metric === mt.id ? 600 : 400,
              }}
              onClick={() => setMetric(mt.id)}
            >
              {mt.label}
            </button>
          ))}
        </div>
      </div>
      <div className="topology-wrap" style={{ position: "relative" }}>
        <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} className="fleet-map" style={{ cursor: "default" }}>
          <path className="fleet-ocean" d={draw({ type: "Sphere" })} />
          <path className="fleet-graticule" d={draw(GRATICULE)} />
          {LAND.features.map((f, i) => (
            <path key={i} className="fleet-land" d={draw(f)} />
          ))}
          {keyed.map((r) => {
            const line = paths.get(r.key) ?? [[r.from.lon, r.from.lat], [r.to.lon, r.to.lat]];
            const dd = draw({ type: "LineString", coordinates: line });
            if (!dd) return null;
            const w = 1.2 + 7 * (valOf(r) / maxVal);
            const hot = hover?.r.process === r.process;
            return (
              <path
                key={r.process}
                d={dd}
                fill="none"
                stroke={hot ? "var(--brand)" : "var(--muted)"}
                strokeWidth={w}
                strokeLinecap="round"
                opacity={hover && !hot ? 0.4 : 0.85}
                vectorEffect="non-scaling-stroke"
                style={{ cursor: "pointer" }}
                onMouseMove={(e) => {
                  const wrap = (e.currentTarget.closest(".topology-wrap") as HTMLElement)?.getBoundingClientRect();
                  setHover({ x: e.clientX - (wrap?.left ?? 0), y: e.clientY - (wrap?.top ?? 0), r });
                }}
                onMouseLeave={() => setHover(null)}
              />
            );
          })}
          {[...coord.entries()].map(([id, c]) => {
            const xy = projection([c.lon, c.lat]);
            if (!xy) return null;
            return (
              <g key={id}>
                <circle cx={xy[0]} cy={xy[1]} r={3} fill="var(--brand)" stroke="var(--surface)" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
                <text x={xy[0] + 6} y={xy[1] + 3} fontSize={10} fill="var(--text)" style={{ pointerEvents: "none" }}>{labelOf(id)}</text>
              </g>
            );
          })}
        </svg>
        {hover && (
          <div
            className="route-tip"
            style={{ left: Math.min(hover.x + 12, 1e9), top: hover.y + 12 }}
          >
            <div style={{ fontWeight: 600, marginBottom: 3 }}>
              {routeTitle(workbook, hover.r.process, labelOf)}
            </div>
            <div className="muted" style={{ fontSize: "0.7rem" }}>{activeYear}</div>
            <table className="route-tip-tbl">
              <tbody>
                <tr><td>Carriers</td><td>{hover.r.ships}</td></tr>
                <tr><td>Cargo</td><td>{fmt(hover.r.cargo)}</td></tr>
                <tr><td>Fuel{hover.r.fuelName ? ` (${hover.r.fuelName})` : ""}</td><td>{fmt(hover.r.fuelUsed)}</td></tr>
                {Object.entries(hover.r.emissions).map(([imp, v]) => (
                  <tr key={imp}><td>{imp}</td><td>{fmt(v)}</td></tr>
                ))}
              </tbody>
            </table>
            {hover.r.fleets.length > 0 && (
              <div className="muted" style={{ fontSize: "0.68rem", marginTop: 4 }}>
                {hover.r.fleets.map((f) => `${f.fleet} ×${f.ships}`).join(" · ")}
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}

// Route title "from → to" from the routes sheet (endpoints' labels).
function routeTitle(wb: Workbook, process: string, labelOf: (id: string) => string): string {
  const r = (wb.routes ?? []).find((x) => s(x.process) === process);
  if (!r) return process;
  return `${labelOf(s(r.from_node))} → ${labelOf(s(r.to_node))}`;
}
