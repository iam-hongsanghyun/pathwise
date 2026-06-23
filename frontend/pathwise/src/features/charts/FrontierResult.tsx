import { ChartTip, useTip } from "./charting";
import type { FrontierBlock } from "../../types";

/** Cost–impact Pareto frontier: a scatter-line of `(achieved impact, cost)` over
 *  a swept cap. Lower-left dominates — the decision-grade trade-off curve. */
export function FrontierResult({ frontier }: { frontier: FrontierBlock }) {
  const { tip, wrapRef, show, hide } = useTip();
  const pts = frontier.points
    .filter((p) => p.status === "optimal" && p.cost != null && p.impact != null)
    .map((p) => ({ x: p.impact as number, y: p.cost as number, cap: p.cap }))
    .sort((a, b) => a.x - b.x);
  const infeasible = frontier.points.filter((p) => p.status !== "optimal").length;

  const fmt = (v: number, d = 1) => v.toLocaleString(undefined, { maximumFractionDigits: d });
  const W = 640, H = 320, padL = 70, padB = 40, padT = 14;
  const xs = pts.map((p) => p.x);
  const ys = pts.map((p) => p.y);
  const xmin = Math.min(...xs, 0), xmax = Math.max(...xs, 1);
  const ymin = Math.min(...ys, 0), ymax = Math.max(...ys, 1);
  const X = (v: number) => padL + ((v - xmin) / (xmax - xmin || 1)) * (W - padL - 14);
  const Y = (v: number) => padT + (H - padB - padT) - ((v - ymin) / (ymax - ymin || 1)) * (H - padB - padT);
  const path = pts.map((p, i) => `${i === 0 ? "M" : "L"}${X(p.x)},${Y(p.y)}`).join(" ");

  return (
    <div className="view">
      <div className="card">
        <h3>Cost–impact frontier — {frontier.impact}</h3>
        <p className="muted">
          Each point is the least-cost plan at a {frontier.impact} cap. The curve is the
          cost↔{frontier.impact} trade-off — lower-left is better.
          {infeasible ? ` ${infeasible} cap(s) were infeasible (below the achievable minimum).` : ""}
        </p>
        {pts.length < 2 ? (
          <p className="muted">Not enough feasible points to draw a frontier.</p>
        ) : (
          <div className="chart-wrap" ref={wrapRef}>
            <svg width={W} height={H} role="img" aria-label="cost–impact frontier">
              <line x1={padL} y1={padT} x2={padL} y2={padT + (H - padB - padT)} stroke="#cbd5e1" />
              <line x1={padL} y1={H - padB} x2={W - 14} y2={H - padB} stroke="#cbd5e1" />
              <text x={6} y={padT + 8} fontSize="9" fill="#64748b">{fmt(ymax)}</text>
              <text x={6} y={H - padB} fontSize="9" fill="#64748b">{fmt(ymin)}</text>
              <text x={padL} y={H - 8} fontSize="9" fill="#64748b">{fmt(xmin)}</text>
              <text x={W - 14} y={H - 8} fontSize="9" fill="#64748b" textAnchor="end">{fmt(xmax)}</text>
              <text x={(padL + W) / 2} y={H - 8} fontSize="10" fill="#475569" textAnchor="middle">{frontier.impact} (achieved)</text>
              <text x={14} y={padT - 2} fontSize="10" fill="#475569">cost</text>
              <path d={path} fill="none" stroke="#0f766e" strokeWidth={1.5} />
              {pts.map((p, i) => (
                <circle
                  key={i}
                  cx={X(p.x)}
                  cy={Y(p.y)}
                  r={3}
                  fill="#0f766e"
                  onMouseMove={(e) =>
                    show(e, [`cap ${fmt(p.cap)}`, `${frontier.impact}: ${fmt(p.x)}`, `cost: ${fmt(p.y)}`])
                  }
                  onMouseLeave={hide}
                />
              ))}
            </svg>
            <ChartTip tip={tip} />
          </div>
        )}
        <div style={{ overflowX: "auto", marginTop: ".5rem" }}>
          <table className="grid-table">
            <thead>
              <tr><th>Cap</th><th>Achieved {frontier.impact}</th><th>Cost</th></tr>
            </thead>
            <tbody>
              {frontier.points.map((p, i) => (
                <tr key={i}>
                  <td>{fmt(p.cap)}</td>
                  <td>{p.status === "optimal" ? fmt(p.impact ?? 0) : "—"}</td>
                  <td>{p.status === "optimal" ? fmt(p.cost ?? 0) : p.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
