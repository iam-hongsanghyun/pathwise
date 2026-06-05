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

/** Minimal multi-series line chart (SVG, no deps). X = years, Y = value. */
export function LineChart({ years, series, height = 240, unit }: Props) {
  const width = 640;
  const padL = 56;
  const padB = 28;
  const padT = 10;
  const plotW = width - padL - 12;
  const plotH = height - padB - padT;
  const all = series.flatMap((s) => s.values);
  const max = Math.max(...all, 1);
  const min = Math.min(...all, 0);
  const span = max - min || 1;
  const x = (i: number) => padL + (years.length <= 1 ? plotW / 2 : (i / (years.length - 1)) * plotW);
  const y = (v: number) => padT + plotH - ((v - min) / span) * plotH;

  return (
    <div>
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
        {series.map((s, si) => {
          const color = PALETTE[si % PALETTE.length];
          const d = s.values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`).join(" ");
          return (
            <g key={s.label}>
              <path d={d} fill="none" stroke={color} strokeWidth={1.5} />
              {s.values.map((v, i) => (
                <circle key={i} cx={x(i)} cy={y(v)} r={2} fill={color} />
              ))}
            </g>
          );
        })}
      </svg>
      <div className="legend">
        {series.map((s, si) => (
          <span key={s.label} className="legend-item">
            <span className="swatch" style={{ background: PALETTE[si % PALETTE.length] }} /> {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
