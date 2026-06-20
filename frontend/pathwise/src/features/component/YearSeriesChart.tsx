// A compact editable time-series chart: a line over the horizon (x = year), where
// clicking a point opens an inline input AT that point to type the exact value
// (and remove it). "＋ year" adds a point prefilled with the scalar fallback. Empty
// = the scalar value applies every year. Edits flow back through onChange.

import { useEffect, useRef, useState } from "react";
import type { ByYear } from "../../lib/api/components";

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
const fmt = (x: number) => (Number.isInteger(x) ? String(x) : x.toFixed(2));

export function YearSeriesChart({
  values,
  fallback,
  label,
  onChange,
}: {
  values: ByYear;
  fallback: number;
  label: string;
  onChange: (v: ByYear) => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(300);
  const [editing, setEditing] = useState<number | null>(null);
  const H = 132;
  const padL = 10;
  const padR = 10;
  const padT = 16;
  const padB = 22;

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth || 300));
    ro.observe(el);
    setW(el.clientWidth || 300);
    return () => ro.disconnect();
  }, []);

  const years = Object.keys(values)
    .map(Number)
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  const pts = years.map((y) => ({ y, v: values[String(y)] }));
  const minY = years[0] ?? 2025;
  const maxY = years[years.length - 1] ?? minY;
  const vmax = Math.max(fallback, 1, ...pts.map((p) => p.v));
  const vmin = Math.min(0, ...pts.map((p) => p.v));
  const X = (yr: number) =>
    years.length < 2 ? padL + (w - padL - padR) / 2 : padL + ((yr - minY) / (maxY - minY)) * (w - padL - padR);
  const Y = (v: number) => padT + (1 - (v - vmin) / ((vmax - vmin) || 1)) * (H - padT - padB);

  const setVal = (yr: number, raw: string) => {
    const next: ByYear = { ...values };
    if (raw.trim() === "") delete next[String(yr)];
    else next[String(yr)] = Number(raw) || 0;
    onChange(next);
  };
  const addYear = () => {
    const last = years[years.length - 1];
    const yr = last ? last + 5 : 2030;
    onChange({ ...values, [String(yr)]: fallback });
    setEditing(yr);
  };
  const removeYear = (yr: number) => {
    const next: ByYear = { ...values };
    delete next[String(yr)];
    onChange(next);
    setEditing(null);
  };

  const editV = editing != null ? values[String(editing)] : undefined;

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
        <strong style={{ fontSize: "0.8rem" }}>{label}</strong>
        <button className="ghost" onClick={addYear}>＋ year</button>
        {years.length === 0 && (
          <span className="muted" style={{ fontSize: "0.72rem" }}>
            scalar ({fmt(fallback)}) applies every year — add a point to vary it
          </span>
        )}
      </div>
      <div ref={wrapRef} style={{ position: "relative", width: "100%" }}>
        {years.length > 0 && (
          <svg width={w} height={H} style={{ display: "block" }}>
            <line x1={padL} y1={H - padB} x2={w - padR} y2={H - padB} stroke="var(--border)" />
            {pts.length > 1 && (
              <polyline
                fill="none"
                stroke="var(--brand)"
                strokeWidth={1.6}
                points={pts.map((p) => `${X(p.y)},${Y(p.v)}`).join(" ")}
              />
            )}
            {pts.map((p) => (
              <g key={p.y} style={{ cursor: "pointer" }} onClick={() => setEditing(editing === p.y ? null : p.y)}>
                <circle
                  cx={X(p.y)}
                  cy={Y(p.v)}
                  r={editing === p.y ? 5.5 : 4}
                  fill={editing === p.y ? "var(--brand-strong)" : "var(--brand)"}
                  stroke="var(--surface)"
                  strokeWidth={1.5}
                />
                {editing !== p.y && (
                  <text x={X(p.y)} y={Y(p.v) - 8} textAnchor="middle" fontSize={9} fill="var(--text)">
                    {fmt(p.v)}
                  </text>
                )}
                <text x={X(p.y)} y={H - padB + 12} textAnchor="middle" fontSize={9} fill="var(--muted)">
                  {p.y}
                </text>
              </g>
            ))}
          </svg>
        )}
        {editing != null && editV !== undefined && (
          <div
            style={{
              position: "absolute",
              left: clamp(X(editing) - 32, 0, Math.max(0, w - 96)),
              top: clamp(Y(editV) - 30, 0, H - 26),
              display: "flex",
              gap: 2,
              alignItems: "center",
              background: "var(--surface)",
              borderRadius: 4,
              boxShadow: "var(--shadow)",
              padding: 1,
            }}
          >
            {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
            <input
              autoFocus
              type="number"
              value={editV}
              onChange={(e) => setVal(editing, e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === "Escape") setEditing(null);
              }}
              style={{ width: 64, padding: "2px 4px", border: "1px solid var(--brand)", borderRadius: 4, font: "inherit", fontSize: "0.72rem" }}
            />
            <button className="ghost" title="remove this year" onClick={() => removeYear(editing)} style={{ padding: "0 2px" }}>
              ✕
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
