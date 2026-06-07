import { useState } from "react";
import { ChartTip, useTip } from "./charting";

interface Series {
  label: string;
  values: number[]; // aligned to `years`
}

interface Props {
  years: number[];
  series: Series[];
  height?: number;
  unit?: string;
}

const PALETTE = ["#0f766e", "#db2777", "#d97706", "#2563eb", "#7c3aed", "#0891b2", "#65a30d"];

/** Minimal multi-series line chart (SVG, no deps), interactive: hover shows a
 *  crosshair + a tooltip of every visible series' value at that year, and the
 *  legend toggles series on/off. X = years, Y = value. */
export function LineChart({ years, series, height = 240, unit }: Props) {
  const { tip, wrapRef, show, hide } = useTip();
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [hover, setHover] = useState<number | null>(null);

  const width = 640;
  const padL = 56;
  const padB = 28;
  const padT = 10;
  const plotW = width - padL - 12;
  const plotH = height - padB - padT;

  const visible = series.filter((s) => !hidden.has(s.label));
  const all = (visible.length ? visible : series).flatMap((s) => s.values);
  const max = Math.max(...all, 1);
  const min = Math.min(...all, 0);
  const span = max - min || 1;
  const x = (i: number) => padL + (years.length <= 1 ? plotW / 2 : (i / (years.length - 1)) * plotW);
  const y = (v: number) => padT + plotH - ((v - min) / span) * plotH;

  const colorOf = (label: string) => PALETTE[series.findIndex((s) => s.label === label) % PALETTE.length];
  const toggle = (label: string) =>
    setHidden((h) => {
      const next = new Set(h);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });

  const onMove = (e: React.MouseEvent) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect || years.length === 0) return;
    const px = e.clientX - rect.left;
    const frac = years.length <= 1 ? 0 : (px - padL) / plotW;
    const idx = Math.max(0, Math.min(years.length - 1, Math.round(frac * (years.length - 1))));
    setHover(idx);
    const rows = visible.map((s) => `${s.label}: ${(s.values[idx] ?? 0).toLocaleString()}`);
    show(e, rows.length ? rows : ["(no visible series)"], String(years[idx]));
  };
  const onLeave = () => {
    setHover(null);
    hide();
  };

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg width={width} height={height} role="img" aria-label="time series">
        <line x1={padL} y1={padT} x2={padL} y2={padT + plotH} stroke="#cbd5e1" />
        <line x1={padL} y1={padT + plotH} x2={width - 12} y2={padT + plotH} stroke="#cbd5e1" />
        <text x={6} y={padT + 8} fontSize="9" fill="#64748b">
          {max.toLocaleString()}
          {unit ? ` ${unit}` : ""}
        </text>
        <text x={6} y={padT + plotH} fontSize="9" fill="#64748b">
          {min.toLocaleString()}
        </text>
        {years.map((yr, i) => (
          <text key={yr} x={x(i)} y={height - 8} fontSize="9" fill="#64748b" textAnchor="middle">
            {yr}
          </text>
        ))}
        {hover != null && (
          <line x1={x(hover)} y1={padT} x2={x(hover)} y2={padT + plotH} stroke="#94a3b8" strokeDasharray="3 3" />
        )}
        {visible.map((s) => {
          const color = colorOf(s.label);
          const d = s.values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`).join(" ");
          return (
            <g key={s.label}>
              <path d={d} fill="none" stroke={color} strokeWidth={1.5} />
              {s.values.map((v, i) => (
                <circle key={i} cx={x(i)} cy={y(v)} r={hover === i ? 3.5 : 2} fill={color} />
              ))}
            </g>
          );
        })}
        {/* transparent capture layer for hover (drawn last so it's on top) */}
        <rect
          x={padL}
          y={padT}
          width={plotW}
          height={plotH}
          fill="transparent"
          onMouseMove={onMove}
          onMouseLeave={onLeave}
        />
      </svg>
      <ChartTip tip={tip} />
      <div className="legend">
        {series.map((s) => (
          <button
            key={s.label}
            className={`legend-item${hidden.has(s.label) ? " is-off" : ""}`}
            onClick={() => toggle(s.label)}
            title="click to show / hide"
          >
            <span className="swatch" style={{ background: colorOf(s.label) }} /> {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}
