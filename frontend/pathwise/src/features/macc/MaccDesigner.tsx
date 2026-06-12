import { useMemo } from "react";
import { resolveMeasures } from "../../lib/graph";
import type { Row, Workbook } from "../../types";

const str = (v: unknown, d = ""): string => (v == null ? d : String(v));
const num = (v: unknown, d = 0): number => (v == null || v === "" ? d : Number(v));

interface Bar {
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

function bars(wb: Workbook): Bar[] {
  const { refConsumption, refImpact } = references(wb);
  const blocks = new Map<string, Row[]>();
  for (const b of wb.measure_blocks ?? [])
    (blocks.get(str(b.measure_id)) ?? blocks.set(str(b.measure_id), []).get(str(b.measure_id))!).push(b);

  const out: Bar[] = [];
  // Expanded per-facility instances (named sets + technology links included).
  for (const m of resolveMeasures(wb)) {
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

/** Marginal Abatement Cost curve: bars sorted by marginal cost, width = potential. */
function MaccChart({ data, width = 720, height = 280 }: { data: Bar[]; width?: number; height?: number }) {
  const usable = data.filter((b) => Number.isFinite(b.cost) && b.potential > 0);
  if (!usable.length) return <p className="muted">No measures with a positive potential yet.</p>;
  const sorted = [...usable].sort((a, b) => a.cost - b.cost);
  const totalW = sorted.reduce((s, b) => s + b.potential, 0);
  const maxCost = Math.max(...sorted.map((b) => b.cost), 1);
  const machines = [...new Set(sorted.map((b) => b.machine))];
  const color = (m: string) => PALETTE[machines.indexOf(m) % PALETTE.length];

  const padL = 56;
  const padB = 28;
  const plotW = width - padL - 10;
  const plotH = height - padB - 10;
  let xCursor = 0;

  return (
    <div>
      <svg width={width} height={height} role="img" aria-label="aggregate MACC">
        <line x1={padL} y1={height - padB} x2={width - 10} y2={height - padB} stroke="#999" />
        <line x1={padL} y1={10} x2={padL} y2={height - padB} stroke="#999" />
        <text x={6} y={18} fontSize="10" fill="#555">
          $/unit
        </text>
        <text x={width - 70} y={height - 8} fontSize="10" fill="#555">
          abatement →
        </text>
        {sorted.map((b, i) => {
          const w = (b.potential / totalW) * plotW;
          const h = (b.cost / maxCost) * plotH;
          const x = padL + (xCursor / totalW) * plotW;
          xCursor += b.potential;
          return (
            <rect
              key={i}
              x={x}
              y={height - padB - h}
              width={Math.max(w - 1, 1)}
              height={h}
              fill={color(b.machine)}
              opacity={0.85}
            >
              <title>
                {b.measure} @ {b.machine}: {b.potential.toFixed(1)} potential, {b.cost.toFixed(1)} $/unit
              </title>
            </rect>
          );
        })}
      </svg>
      <div className="legend">
        {machines.map((m) => (
          <span key={m} className="legend-item">
            <span className="swatch" style={{ background: color(m) }} /> {m}
          </span>
        ))}
      </div>
    </div>
  );
}

interface Props {
  workbook: Workbook;
}

/** Per-machine MACC summary + the whole process's aggregate MACC curve. */
export function MaccDesigner({ workbook }: Props) {
  const data = useMemo(() => bars(workbook), [workbook]);
  const byMachine = useMemo(() => {
    const m = new Map<string, Bar[]>();
    for (const b of data) (m.get(b.machine) ?? m.set(b.machine, []).get(b.machine)!).push(b);
    return m;
  }, [data]);

  return (
    <div>
      <h3>Aggregate MACC (whole process)</h3>
      <MaccChart data={data} />
      <h3>Per-machine measures</h3>
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
      {!data.length && <p className="muted">Add measures + blocks (in Tables) to build MACC curves.</p>}
    </div>
  );
}
