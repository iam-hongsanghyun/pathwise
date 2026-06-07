import { ChartTip, useTip } from "./charting";
import type { PortfolioResultBlock } from "../types";

const BRAND = "#0f766e";
const ACCENT = "#db2777";
const GRID = "#cbd5e1";
const AXIS = "#64748b";

const fmt = (v: number, d = 3) =>
  Math.abs(v) >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : v.toFixed(d);

interface Props {
  portfolio: PortfolioResultBlock;
}

/** Portfolio result: allocation weights, efficient frontier (x = return,
 *  y = risk), and the per-scenario reward distribution. Hand-rolled SVG (no
 *  chart dependency); every chart has hover tooltips + highlighting. */
export function PortfolioResult({ portfolio }: Props) {
  const rewardLabel = portfolio.reward_mode === "profit" ? "profit" : "cost reduction";
  const unit = portfolio.normalize_by_capex ? " (per unit capex)" : "";
  return (
    <div className="view">
      <section className="card">
        <h3>
          Allocation · {portfolio.method.toUpperCase()} · {rewardLabel}
        </h3>
        <p className="muted">
          Expected {rewardLabel}: <strong>{fmt(portfolio.expected_return)}</strong>
          {unit} · Risk (σ): <strong>{fmt(portfolio.risk)}</strong>
          {portfolio.cvar != null && (
            <>
              {" "}
              · CVaR: <strong>{fmt(portfolio.cvar)}</strong>
            </>
          )}{" "}
          · {portfolio.assets.length} assets · {portfolio.n_scenarios.toLocaleString()} scenarios
        </p>
        <Allocation portfolio={portfolio} rewardLabel={rewardLabel} />
      </section>

      {portfolio.frontier.length > 0 && (
        <section className="card">
          <h3>Efficient frontier</h3>
          <Frontier portfolio={portfolio} rewardLabel={rewardLabel} />
        </section>
      )}

      {portfolio.distribution.length > 0 && (
        <section className="card">
          <h3>Reward distribution (across scenarios)</h3>
          <Histogram portfolio={portfolio} rewardLabel={rewardLabel} />
        </section>
      )}
    </div>
  );
}

/** Horizontal weight bars, sorted high → low; hover a row for its details. */
function Allocation({ portfolio, rewardLabel }: Props & { rewardLabel: string }) {
  const { tip, wrapRef, show, hide } = useTip();
  const assets = [...portfolio.assets].sort((a, b) => b.weight - a.weight);
  const rowH = 24;
  const padL = 180;
  const width = 640;
  const barW = width - padL - 64;
  const maxW = Math.max(...assets.map((a) => a.weight), 1e-9);
  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg width={width} height={assets.length * rowH + 8} role="img" aria-label="allocation">
        {assets.map((a, i) => {
          const yy = i * rowH + 4;
          const w = (a.weight / maxW) * barW;
          const rows = [
            `weight: ${(a.weight * 100).toFixed(1)}%`,
            `expected ${rewardLabel}: ${fmt(a.expected_return)}`,
            `σ: ${fmt(a.std)}`,
            `switch capex: ${fmt(a.transition_capex)}`,
          ];
          return (
            <g
              key={a.asset_id}
              onMouseMove={(e) => show(e, rows, a.label)}
              onMouseLeave={hide}
            >
              <rect x={0} y={yy - 2} width={width} height={rowH} fill="transparent" />
              <text x={padL - 8} y={yy + 13} fontSize="11" fill={AXIS} textAnchor="end">
                {a.label.length > 26 ? `${a.label.slice(0, 25)}…` : a.label}
              </text>
              <rect x={padL} y={yy} width={Math.max(w, 0)} height={rowH - 8} fill={BRAND} rx={1} />
              <text x={padL + Math.max(w, 0) + 6} y={yy + 13} fontSize="11" fill={AXIS}>
                {(a.weight * 100).toFixed(1)}%
              </text>
            </g>
          );
        })}
      </svg>
      <ChartTip tip={tip} />
    </div>
  );
}

/** Frontier scatter: x = return, y = risk; chosen portfolio highlighted. */
function Frontier({ portfolio, rewardLabel }: Props & { rewardLabel: string }) {
  const { tip, wrapRef, show, hide } = useTip();
  const width = 640;
  const height = 300;
  const padL = 56;
  const padB = 36;
  const padT = 12;
  const plotW = width - padL - 16;
  const plotH = height - padB - padT;
  const pts = [...portfolio.frontier, { return: portfolio.chosen.return, risk: portfolio.chosen.risk }];
  const xs = pts.map((p) => p.return);
  const ys = pts.map((p) => p.risk);
  // Pad each axis to its own data range (not anchored at 0) so the frontier
  // curve is visible even when risk/return vary over a narrow band.
  const pad = (lo: number, hi: number) => {
    const m = (hi - lo) * 0.08 || Math.abs(hi) * 0.08 || 1;
    return [lo - m, hi + m] as const;
  };
  const [xMin, xMax] = pad(Math.min(...xs), Math.max(...xs));
  const [yMin, yMax] = pad(Math.min(...ys), Math.max(...ys));
  const xSpan = xMax - xMin || 1;
  const ySpan = yMax - yMin || 1;
  const x = (v: number) => padL + ((v - xMin) / xSpan) * plotW;
  const y = (v: number) => padT + plotH - ((v - yMin) / ySpan) * plotH;
  const path = portfolio.frontier
    .slice()
    .sort((a, b) => a.return - b.return)
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.return)},${y(p.risk)}`)
    .join(" ");

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg width={width} height={height} role="img" aria-label="efficient frontier">
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke={GRID} />
        <line x1={padL} y1={padT + plotH} x2={width - 16} y2={padT + plotH} stroke={GRID} />
        <path d={path} fill="none" stroke={BRAND} strokeWidth={1.5} />
        {portfolio.frontier.map((p, i) => (
          <circle
            key={i}
            cx={x(p.return)}
            cy={y(p.risk)}
            r={3}
            fill={BRAND}
            className="hoverable"
            onMouseMove={(e) => show(e, [`return: ${fmt(p.return)}`, `risk (σ): ${fmt(p.risk)}`], "frontier point")}
            onMouseLeave={hide}
          />
        ))}
        <circle
          cx={x(portfolio.chosen.return)}
          cy={y(portfolio.chosen.risk)}
          r={5}
          fill={ACCENT}
          className="hoverable"
          onMouseMove={(e) =>
            show(
              e,
              [`return: ${fmt(portfolio.chosen.return)}`, `risk (σ): ${fmt(portfolio.chosen.risk)}`],
              "chosen portfolio",
            )
          }
          onMouseLeave={hide}
        />
        <text x={x(portfolio.chosen.return) + 8} y={y(portfolio.chosen.risk) - 6} fontSize="10" fill={ACCENT}>
          chosen
        </text>
        <text x={6} y={padT + 8} fontSize="9" fill={AXIS}>
          {fmt(yMax)}
        </text>
        <text x={6} y={padT + plotH} fontSize="9" fill={AXIS}>
          {fmt(yMin)}
        </text>
        <text x={padL} y={height - 8} fontSize="9" fill={AXIS}>
          {fmt(xMin)}
        </text>
        <text x={width - 16} y={height - 8} fontSize="9" fill={AXIS} textAnchor="end">
          {fmt(xMax)}
        </text>
        <text x={padL + plotW / 2} y={height - 20} fontSize="10" fill={AXIS} textAnchor="middle">
          return ({rewardLabel}) →
        </text>
        <text
          x={14}
          y={padT + plotH / 2}
          fontSize="10"
          fill={AXIS}
          textAnchor="middle"
          transform={`rotate(-90 14 ${padT + plotH / 2})`}
        >
          risk (σ) →
        </text>
      </svg>
      <ChartTip tip={tip} />
    </div>
  );
}

/** Reward distribution histogram, marking the mean; hover a bar for its range. */
function Histogram({ portfolio, rewardLabel }: Props & { rewardLabel: string }) {
  const { tip, wrapRef, show, hide } = useTip();
  const data = portfolio.distribution;
  const width = 640;
  const height = 240;
  const padL = 40;
  const padB = 28;
  const padT = 10;
  const plotW = width - padL - 16;
  const plotH = height - padB - padT;
  const lo = Math.min(...data);
  const hi = Math.max(...data);
  const span = hi - lo || 1;
  const bins = 32;
  const counts = new Array(bins).fill(0) as number[];
  for (const v of data) {
    const b = Math.min(bins - 1, Math.floor(((v - lo) / span) * bins));
    counts[b] += 1;
  }
  const maxCount = Math.max(...counts, 1);
  const mean = data.reduce((s, v) => s + v, 0) / data.length;
  const x = (v: number) => padL + ((v - lo) / span) * plotW;
  const bw = plotW / bins;

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg width={width} height={height} role="img" aria-label="reward distribution">
        <line x1={padL} y1={padT + plotH} x2={width - 16} y2={padT + plotH} stroke={GRID} />
        {counts.map((c, i) => {
          const h = (c / maxCount) * plotH;
          const binLo = lo + (i / bins) * span;
          const binHi = lo + ((i + 1) / bins) * span;
          const pct = ((c / data.length) * 100).toFixed(1);
          return (
            <g
              key={i}
              onMouseMove={(e) => show(e, [`${c} scenarios (${pct}%)`], `${fmt(binLo)} … ${fmt(binHi)}`)}
              onMouseLeave={hide}
            >
              <rect x={padL + i * bw} y={padT} width={bw} height={plotH} fill="transparent" />
              <rect
                x={padL + i * bw + 0.5}
                y={padT + plotH - h}
                width={Math.max(bw - 1, 1)}
                height={h}
                fill={BRAND}
                opacity={0.8}
              />
            </g>
          );
        })}
        <line x1={x(mean)} y1={padT} x2={x(mean)} y2={padT + plotH} stroke={ACCENT} strokeWidth={1.5} />
        <text x={x(mean) + 4} y={padT + 10} fontSize="9" fill={ACCENT}>
          mean {fmt(mean)}
        </text>
        <text x={padL} y={height - 8} fontSize="9" fill={AXIS}>
          {fmt(lo)}
        </text>
        <text x={width - 16} y={height - 8} fontSize="9" fill={AXIS} textAnchor="end">
          {fmt(hi)}
        </text>
        <text x={padL + plotW / 2} y={height - 8} fontSize="10" fill={AXIS} textAnchor="middle">
          {rewardLabel} per scenario
        </text>
      </svg>
      <ChartTip tip={tip} />
    </div>
  );
}
