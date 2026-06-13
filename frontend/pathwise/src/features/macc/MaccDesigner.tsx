import { useMemo, useState } from "react";
import { resolveMeasures } from "../../lib/graph";
import type { Row, Workbook } from "../../types";

const str = (v: unknown, d = ""): string => (v == null ? d : String(v));
const num = (v: unknown, d = 0): number => (v == null || v === "" ? d : Number(v));

export interface MaccBar {
  measure: string;
  machine: string;
  type: string;
  target: string;
  potential: number; // abatement / energy-saving potential (per year)
  cost: number; // marginal cost per unit potential
  capex: number;
}

/** Best-effort reference (mirrors core/variables._references) so the designer's
 *  MACC reflects the same magnitudes the optimiser sees. */
function references(wb: Workbook) {
  const baseTech = new Map<string, string>(
    (wb.processes ?? []).map((p) => [str(p.process_id), str(p.baseline_technology)]),
  );
  const capacity = new Map<string, number>(
    (wb.processes ?? []).map((p) => [str(p.process_id), num(p.capacity)]),
  );
  // Intensities/impacts come from the unified `io` table (legacy sheets as
  // fallback) — mirroring lib/graph and the assembler.
  const intensity = new Map<string, number>(); // `${tech}|${commodity}`
  for (const r of wb.process_inputs ?? [])
    intensity.set(`${str(r.technology_id)}|${str(r.commodity_id)}`, num(r.intensity));
  const direct = new Map<string, number>(); // `${tech}|${impact}`
  for (const r of wb.tech_impacts ?? [])
    direct.set(`${str(r.technology_id)}|${str(r.impact_id)}`, num(r.factor));
  for (const r of wb.io ?? []) {
    const role = str(r.role, "input");
    if (role === "input")
      intensity.set(`${str(r.technology_id)}|${str(r.target)}`, num(r.coefficient));
    else if (role === "impact")
      direct.set(`${str(r.technology_id)}|${str(r.target)}`, num(r.coefficient));
  }
  const commodityImpact = new Map<string, number>(); // `${commodity}|${impact}`
  for (const r of wb.commodity_impacts ?? [])
    commodityImpact.set(`${str(r.commodity_id)}|${str(r.impact_id)}`, num(r.factor));

  const refConsumption = (p: string, commodity: string): number =>
    (capacity.get(p) ?? 0) * (intensity.get(`${baseTech.get(p)}|${commodity}`) ?? 0);
  const refImpact = (p: string, impact: string): number => {
    const tech = baseTech.get(p) ?? "";
    let total = (capacity.get(p) ?? 0) * (direct.get(`${tech}|${impact}`) ?? 0);
    const inputs = new Set<string>([
      ...(wb.process_inputs ?? [])
        .filter((r) => str(r.technology_id) === tech)
        .map((r) => str(r.commodity_id)),
      ...(wb.io ?? [])
        .filter((r) => str(r.technology_id) === tech && str(r.role, "input") === "input")
        .map((r) => str(r.target)),
    ]);
    for (const c of inputs)
      total += (commodityImpact.get(`${c}|${impact}`) ?? 0) * refConsumption(p, c);
    return total;
  };
  return { refConsumption, refImpact };
}

export function maccBars(wb: Workbook, macc?: string): MaccBar[] {
  const { refConsumption, refImpact } = references(wb);
  const blocks = new Map<string, Row[]>();
  for (const b of wb.measure_blocks ?? [])
    (blocks.get(str(b.measure_id)) ?? blocks.set(str(b.measure_id), []).get(str(b.measure_id))!).push(b);

  // Restricted to one MACC's member measures when given.
  const members = macc
    ? new Set(
        (wb.maccs ?? [])
          .filter((r) => str(r.macc) === macc)
          .map((r) => str(r.measure_id)),
      )
    : null;
  const out: MaccBar[] = [];
  // Expanded per-facility instances (MACC deployments + direct links included).
  for (const m of resolveMeasures(wb)) {
    if (members && !members.has(m.base_id)) continue;
    const id = m.measure_id;
    const p = m.applies_to;
    const type = m.type;
    const target = m.target;
    const ref = type === "energy_efficiency" ? refConsumption(p, target) : refImpact(p, target);
    for (const blk of blocks.get(m.base_id) ?? []) {
      const reduction = num(blk.reduction);
      const capex = num(blk.capex);
      const potential = reduction * ref;
      out.push({
        measure: id,
        machine: p,
        type,
        target,
        potential,
        capex,
        cost: potential > 0 ? capex / potential : Infinity,
      });
    }
  }
  return out;
}

const PALETTE = ["#2563eb", "#16a34a", "#db2777", "#d97706", "#7c3aed", "#0891b2"];

const formatAxis = (value: number): string => {
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(1)}k`;
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  return value.toFixed(2).replace(/\.?0+$/, "");
};

const niceTicks = (min: number, max: number, count: number): number[] => {
  if (!Number.isFinite(min) || !Number.isFinite(max) || count < 2) return [0];
  if (min === max) return [min];
  const span = max - min;
  const rawStep = span / (count - 1);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const residual = rawStep / magnitude;
  const niceResidual = residual >= 5 ? 5 : residual >= 2 ? 2 : 1;
  const step = niceResidual * magnitude;
  const first = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = first; v <= max + step * 0.25; v += step) ticks.push(Number(v.toPrecision(12)));
  if (!ticks.includes(0) && min < 0 && max > 0) ticks.push(0);
  return ticks.sort((a, b) => a - b);
};

/** Marginal Abatement Cost curve: bars sorted by marginal cost, width =
 *  potential. Interactive: hover/click a bar to pin its readout; click a
 *  legend entry to hide/show that facility's bars. */
export function MaccChart({
  data,
  width = 620,
  height = 260,
}: {
  data: MaccBar[];
  width?: number;
  height?: number;
}) {
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const usable = data.filter((b) => Number.isFinite(b.cost) && b.potential > 0);
  if (!usable.length) return <p className="muted">No measures with a positive potential yet.</p>;
  // Colors stay keyed to the FULL facility list so toggling doesn't reshuffle.
  const machines = [...new Set(usable.map((b) => b.machine))];
  const color = (m: string) => PALETTE[machines.indexOf(m) % PALETTE.length];
  const toggleMachine = (m: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(m)) next.delete(m);
      else next.add(m);
      return next;
    });
  const legend = (
    <div className="legend">
      {machines.map((m) => (
        <button
          key={m}
          className={`legend-item${hidden.has(m) ? " is-off" : ""}`}
          onClick={() => toggleMachine(m)}
          title={hidden.has(m) ? "show this facility" : "hide this facility"}
        >
          <span className="swatch" style={{ background: color(m) }} /> {m}
        </button>
      ))}
    </div>
  );
  const sorted = usable.filter((b) => !hidden.has(b.machine)).sort((a, b) => a.cost - b.cost);
  if (!sorted.length)
    return (
      <div className="macc-chart-shell">
        <p className="muted">All facilities hidden — click a legend entry to show them.</p>
        {legend}
      </div>
    );
  const totalW = sorted.reduce((s, b) => s + b.potential, 0);
  const minCost = Math.min(...sorted.map((b) => b.cost), 0);
  const maxCost = Math.max(...sorted.map((b) => b.cost), 1);
  const yMin = minCost === maxCost ? Math.min(0, minCost - 1) : minCost;
  const yMax = minCost === maxCost ? Math.max(1, maxCost + 1) : maxCost;

  const padL = 62;
  const padR = 14;
  const padT = 14;
  const padB = 44;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;
  const xScale = (value: number) => padL + (value / totalW) * plotW;
  const yScale = (value: number) => padT + ((yMax - value) / (yMax - yMin)) * plotH;
  const yZero = yScale(0);
  let cursor = 0;
  const bars = sorted.map((b, i) => {
    const x0 = cursor;
    const x1 = cursor + b.potential;
    cursor = x1;
    const key = `${b.measure}|${b.machine}|${i}`;
    return {
      ...b,
      key,
      x: xScale(x0),
      y: Math.min(yScale(b.cost), yZero),
      width: Math.max(xScale(x1) - xScale(x0) - 1, 1),
      height: Math.max(Math.abs(yScale(b.cost) - yZero), 1),
      x0,
      x1,
    };
  });
  const active = bars.find((b) => b.key === activeKey) ?? bars[0];
  const xTicks = niceTicks(0, totalW, 5);
  const yTicks = niceTicks(yMin, yMax, 5);

  return (
    <div className="macc-chart-shell">
      <div className="macc-chart-plot">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="interactive MACC chart">
          {xTicks.map((tick) => {
            const x = xScale(tick);
            return (
              <g key={`x-${tick}`}>
                <line x1={x} y1={padT} x2={x} y2={height - padB} className="macc-grid" />
                <line x1={x} y1={height - padB} x2={x} y2={height - padB + 4} className="macc-axis" />
                <text x={x} y={height - 24} textAnchor="middle" className="macc-tick">
                  {formatAxis(tick)}
                </text>
              </g>
            );
          })}
          {yTicks.map((tick) => {
            const y = yScale(tick);
            return (
              <g key={`y-${tick}`}>
                <line x1={padL} y1={y} x2={width - padR} y2={y} className="macc-grid" />
                <line x1={padL - 4} y1={y} x2={padL} y2={y} className="macc-axis" />
                <text x={padL - 8} y={y + 3} textAnchor="end" className="macc-tick">
                  {formatAxis(tick)}
                </text>
              </g>
            );
          })}
          <line x1={padL} y1={padT} x2={padL} y2={height - padB} className="macc-axis" />
          <line x1={padL} y1={yZero} x2={width - padR} y2={yZero} className="macc-zero-axis" />
          {bars.map((b) => {
            const activeBar = b.key === active.key;
            return (
            <rect
              key={b.key}
              x={b.x}
              y={b.y}
              width={b.width}
              height={b.height}
              fill={color(b.machine)}
              className={`macc-bar${activeBar ? " is-active" : ""}`}
              tabIndex={0}
              role="button"
              aria-label={`${b.measure} at ${b.machine}: ${b.potential.toFixed(
                1,
              )} potential, ${b.cost.toFixed(1)} dollars per unit`}
              onFocus={() => setActiveKey(b.key)}
              onPointerEnter={() => setActiveKey(b.key)}
              onClick={() => setActiveKey(b.key)}
            >
              <title>
                {b.measure} @ {b.machine}: {b.potential.toFixed(1)} potential, {b.cost.toFixed(1)} $/unit
              </title>
            </rect>
            );
          })}
          <text x={width / 2} y={height - 6} textAnchor="middle" className="macc-axis-label">
            cumulative potential
          </text>
          <text
            x={16}
            y={height / 2}
            textAnchor="middle"
            className="macc-axis-label"
            transform={`rotate(-90 16 ${height / 2})`}
          >
            marginal cost ($/unit)
          </text>
        </svg>
      </div>
      <div className="macc-chart-readout" aria-live="polite">
        <div>
          <span className="rail-count">BAR</span>
          <strong>{active.measure}</strong>
        </div>
        <dl>
          <div>
            <dt>facility</dt>
            <dd>{active.machine}</dd>
          </div>
          <div>
            <dt>target</dt>
            <dd>{active.target}</dd>
          </div>
          <div>
            <dt>range</dt>
            <dd>
              {formatAxis(active.x0)}-{formatAxis(active.x1)}
            </dd>
          </div>
          <div>
            <dt>potential</dt>
            <dd>{active.potential.toFixed(1)}</dd>
          </div>
          <div>
            <dt>cost</dt>
            <dd>{active.cost.toFixed(1)} $/unit</dd>
          </div>
        </dl>
      </div>
      {legend}
    </div>
  );
}

export function MaccMeasureTable({ data }: { data: MaccBar[] }) {
  const byMachine = new Map<string, MaccBar[]>();
  for (const b of data) byMachine.set(b.machine, [...(byMachine.get(b.machine) ?? []), b]);

  if (!data.length) return <p className="muted">No deployed measures yet.</p>;

  return (
    <div>
      {[...byMachine.entries()].map(([machine, bs]) => (
        <div key={machine} className="macc-machine">
          <strong>{machine}</strong>
          <table>
            <thead>
              <tr>
                <th>measure</th>
                <th>type</th>
                <th>target</th>
                <th>potential</th>
                <th>$/unit</th>
              </tr>
            </thead>
            <tbody>
              {bs.map((b, i) => (
                <tr key={i}>
                  <td>{b.measure}</td>
                  <td>{b.type}</td>
                  <td>{b.target}</td>
                  <td>{b.potential.toFixed(1)}</td>
                  <td>{Number.isFinite(b.cost) ? b.cost.toFixed(1) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

interface Props {
  workbook: Workbook;
  /** Restrict the chart to one MACC's member measures. */
  macc?: string;
}

/** Per-machine MACC summary + the aggregate MACC curve (whole model, or one
 *  MACC's members when `macc` is given). */
export function MaccDesigner({ workbook, macc }: Props) {
  const data = useMemo(() => maccBars(workbook, macc), [workbook, macc]);

  return (
    <div>
      <h3>Aggregate MACC (whole process)</h3>
      <MaccChart data={data} />
      <h3>Per-machine measures</h3>
      <MaccMeasureTable data={data} />
      {!data.length && <p className="muted">Add measures and cost blocks to build MACC curves.</p>}
    </div>
  );
}
