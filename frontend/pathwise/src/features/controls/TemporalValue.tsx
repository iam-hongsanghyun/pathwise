// A value that is STATIC (one number, applied to every year) or TEMPORAL (a value
// that varies over the horizon). The temporal editor is anchor-based: you set a few
// (year, value) anchors, a horizon range, and a fill rule (Linear ramp or Step
// hold) — the editor materialises that onto the model's run periods on save, so the
// stored rows are exactly what the engine sees (it treats per-year rows as exact).
// Re-opening compresses the dense rows back to the minimal anchor set and detects
// whether the shape was linear or step, so editing stays clean.
//
// Used for the Optimisation constraints and the asset output / input bounds.

import { useMemo, useState } from "react";
import type { ByYear } from "../../lib/api/components";

/** A bound value: a scalar (all years) or a {year: value} map. */
export type TemporalVal = number | ByYear;

type Mode = "linear" | "step";
type Pt = { year: number; value: number };
type Draft = { year: string; value: string };

const EPS = 1e-6;
const fmt = (x: number): string => (Number.isInteger(x) ? x.toLocaleString() : x.toFixed(2));
const isTemporal = (v: TemporalVal | null): v is ByYear => v != null && typeof v !== "number";
const round = (x: number): number => Math.round(x * 1e6) / 1e6;

const toPts = (b: ByYear): Pt[] =>
  Object.entries(b)
    .map(([y, v]) => ({ year: Number(y), value: Number(v) }))
    .filter((p) => Number.isFinite(p.year) && Number.isFinite(p.value))
    .sort((a, c) => a.year - c.year);

/** Value at year `y` given sorted anchors, flat-held before the first / after the
 *  last anchor. Linear interpolates between anchors; step holds the lower anchor. */
function valueAt(anchors: Pt[], y: number, mode: Mode): number {
  if (!anchors.length) return 0;
  if (y <= anchors[0].year) return anchors[0].value;
  const last = anchors[anchors.length - 1];
  if (y >= last.year) return last.value;
  for (let i = 0; i < anchors.length - 1; i++) {
    const lo = anchors[i];
    const hi = anchors[i + 1];
    if (y >= lo.year && y <= hi.year) {
      if (y === lo.year) return lo.value;
      if (y === hi.year) return hi.value;
      if (mode === "step") return lo.value;
      return lo.value + ((hi.value - lo.value) * (y - lo.year)) / (hi.year - lo.year);
    }
  }
  return last.value;
}

/** Materialise anchors onto the run periods within [from, to] → dense {year: value}. */
function materialize(anchors: Pt[], periods: number[], from: number, to: number, mode: Mode): ByYear {
  const out: ByYear = {};
  for (const y of periods) if (y >= from && y <= to) out[String(y)] = round(valueAt(anchors, y, mode));
  return out;
}

/** Drop interior anchors a straight line through their neighbours already predicts. */
function linearCompress(pts: Pt[]): Pt[] {
  if (pts.length <= 2) return pts;
  const keep: Pt[] = [pts[0]];
  for (let i = 1; i < pts.length - 1; i++) {
    const a = pts[i - 1];
    const b = pts[i];
    const c = pts[i + 1];
    const predicted = a.value + ((c.value - a.value) * (b.year - a.year)) / (c.year - a.year);
    if (Math.abs(b.value - predicted) > EPS) keep.push(b);
  }
  keep.push(pts[pts.length - 1]);
  return keep;
}

/** Drop anchors whose value repeats the one before (a staircase keeps its risers). */
function stepCompress(pts: Pt[]): Pt[] {
  if (pts.length <= 1) return pts;
  const keep: Pt[] = [pts[0]];
  for (let i = 1; i < pts.length; i++) if (Math.abs(pts[i].value - pts[i - 1].value) > EPS) keep.push(pts[i]);
  return keep;
}

/** Does re-expanding `anchors` over the stored years reproduce the stored values? */
function reproduces(anchors: Pt[], stored: Pt[], mode: Mode): boolean {
  return stored.every((p) => Math.abs(valueAt(anchors, p.year, mode) - p.value) < 1e-4);
}

export function TemporalValue({
  value,
  onChange,
  label,
  unit,
  perYear = true,
  baseYear,
  periods,
  placeholder = "set…",
  variant = "button",
}: {
  value: TemporalVal | null;
  onChange: (v: TemporalVal | null) => void;
  label: string;
  unit?: string;
  /** Append "/yr" to the unit. True for flows (t/yr, currency/yr); set false for
   *  a rate that is already per-unit, e.g. a price (currency/t). */
  perYear?: boolean;
  baseYear: number;
  /** The model's run periods (years). The fill is materialised onto these. */
  periods?: number[];
  placeholder?: string;
  /** "button" = a bordered box; "text" = inline clickable value/trend (no box). */
  variant?: "button" | "text";
}) {
  const [open, setOpen] = useState(false);
  const per = perYear ? "/yr" : "";
  const text =
    value == null
      ? placeholder
      : isTemporal(value)
        ? `↗ ${Object.keys(value).length} yr`
        : fmt(value);
  return (
    <>
      <button className={`temporal-btn${variant === "text" ? " is-text" : ""}`} title="edit value — static or by-year" onClick={() => setOpen(true)}>
        <span>{text}</span>
        {unit && value != null ? <span className="muted"> {unit}{per}</span> : null}
      </button>
      {open && (
        <Editor
          initial={value}
          label={label}
          unit={unit}
          perYear={perYear}
          baseYear={baseYear}
          periods={periods}
          onCancel={() => setOpen(false)}
          onSave={(v) => {
            onChange(v);
            setOpen(false);
          }}
        />
      )}
    </>
  );
}

function Editor({
  initial,
  label,
  unit,
  perYear = true,
  baseYear,
  periods,
  onSave,
  onCancel,
}: {
  initial: TemporalVal | null;
  label: string;
  unit?: string;
  perYear?: boolean;
  baseYear: number;
  periods?: number[];
  onSave: (v: TemporalVal | null) => void;
  onCancel: () => void;
}) {
  const per = perYear ? "/yr" : "";
  // The model periods, sorted & de-duped; falls back to a single base year.
  const modelYears = useMemo(() => {
    const ys = Array.from(new Set((periods ?? []).filter(Number.isFinite))).sort((a, b) => a - b);
    return ys.length ? ys : [baseYear];
  }, [periods, baseYear]);
  const firstYear = modelYears[0];
  const lastYear = modelYears[modelYears.length - 1];

  // Reconstruct the editing state from the stored value.
  const seed = useMemo(() => reconstruct(initial, baseYear, firstYear, lastYear), [initial]); // eslint-disable-line react-hooks/exhaustive-deps

  const [mode, setMode] = useState<"static" | "temporal">(seed.kind);
  const [staticV, setStaticV] = useState<string>(seed.staticV);
  const [fill, setFill] = useState<Mode>(seed.fill);
  const [from, setFrom] = useState<string>(String(seed.from));
  const [to, setTo] = useState<string>(String(seed.to));
  const [drafts, setDrafts] = useState<Draft[]>(seed.anchors);

  const fromN = Number(from);
  const toN = Number(to);
  const rangeOk = Number.isFinite(fromN) && Number.isFinite(toN) && fromN <= toN;

  // Valid anchors (parse + sort), and the materialised curve for the preview.
  const anchors = useMemo<Pt[]>(
    () =>
      drafts
        .filter((d) => d.year.trim() !== "" && d.value.trim() !== "")
        .map((d) => ({ year: Number(d.year), value: Number(d.value) }))
        .filter((p) => Number.isFinite(p.year) && Number.isFinite(p.value))
        .sort((a, b) => a.year - b.year),
    [drafts],
  );
  const dense = useMemo<ByYear>(
    () => (rangeOk ? materialize(anchors, withinRange(modelYears, fromN, toN), fromN, toN, fill) : {}),
    [anchors, modelYears, fromN, toN, fill, rangeOk],
  );

  function addYear() {
    const used = new Set(drafts.map((d) => Number(d.year)));
    const next = drafts.length
      ? nextUnused([...modelYears, lastYear + 5], used, Number(drafts[drafts.length - 1].year))
      : firstYear;
    const lastV = drafts.length ? drafts[drafts.length - 1].value : staticV || "0";
    setDrafts([...drafts, { year: String(next), value: lastV }]);
  }
  const setDraft = (i: number, patch: Partial<Draft>) =>
    setDrafts(drafts.map((d, j) => (j === i ? { ...d, ...patch } : d)));
  const removeDraft = (i: number) => setDrafts(drafts.filter((_, j) => j !== i));

  function save() {
    if (mode === "static") {
      onSave(staticV.trim() === "" ? null : Number(staticV) || 0);
      return;
    }
    onSave(Object.keys(dense).length ? dense : null);
  }

  return (
    <div className="modal-scrim" onClick={onCancel}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 460 }}>
        <div className="eyebrow">value</div>
        <h3 style={{ margin: "2px 0 4px" }}>{label}</h3>
        <p className="muted" style={{ fontSize: "0.74rem", margin: "0 0 12px" }}>
          One value for the whole horizon, or a trajectory: set a few year anchors and a fill rule —
          it's expanded onto the run years on save.
        </p>
        <div className="seg" style={{ flex: "none", marginBottom: 12 }}>
          <button className={mode === "static" ? "is-active" : ""} onClick={() => setMode("static")}>Static</button>
          <button className={mode === "temporal" ? "is-active" : ""} onClick={() => setMode("temporal")}>By year</button>
        </div>

        {mode === "static" ? (
          <label className="field-row">
            {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
            <input
              className="field-input"
              type="number"
              autoFocus
              placeholder="value"
              value={staticV}
              onChange={(e) => setStaticV(e.target.value)}
              style={{ width: 150 }}
            />
            {unit ? <span className="muted">{unit}{per}</span> : null}
          </label>
        ) : (
          <>
            <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
              <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: "0.78rem" }}>
                <span className="muted">horizon</span>
                <input className="field-input" type="number" value={from} onChange={(e) => setFrom(e.target.value)} style={{ width: 68 }} />
                <span className="muted">→</span>
                <input className="field-input" type="number" value={to} onChange={(e) => setTo(e.target.value)} style={{ width: 68 }} />
              </label>
              <div className="seg" style={{ flex: "none" }}>
                <button className={fill === "linear" ? "is-active" : ""} onClick={() => setFill("linear")} title="straight-line ramp between anchors">Linear</button>
                <button className={fill === "step" ? "is-active" : ""} onClick={() => setFill("step")} title="hold each anchor's value until the next">Step</button>
              </div>
            </div>

            <PreviewChart dense={dense} anchors={anchors} from={fromN} to={toN} unit={unit} perYear={perYear} />

            <div style={{ marginTop: 10 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                <strong style={{ fontSize: "0.78rem" }}>anchors {unit ? <span className="muted">({unit}{per})</span> : null}</strong>
                <button className="ghost" onClick={addYear}>＋ add year</button>
              </div>
              {drafts.length === 0 ? (
                <p className="muted" style={{ fontSize: "0.72rem", margin: "4px 0" }}>
                  No anchors yet — add a year to start a trajectory.
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 168, overflowY: "auto" }}>
                  {drafts.map((d, i) => (
                    <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <input
                        className="field-input"
                        type="number"
                        value={d.year}
                        placeholder="year"
                        onChange={(e) => setDraft(i, { year: e.target.value })}
                        style={{ width: 80 }}
                      />
                      <input
                        className="field-input"
                        type="number"
                        value={d.value}
                        placeholder="value"
                        onChange={(e) => setDraft(i, { value: e.target.value })}
                        style={{ width: 110 }}
                      />
                      <button className="ghost" title="remove this anchor" onClick={() => removeDraft(i)} style={{ padding: "0 6px" }}>✕</button>
                    </div>
                  ))}
                </div>
              )}
              {!rangeOk && (
                <p style={{ color: "var(--danger, #c0392b)", fontSize: "0.72rem", margin: "6px 0 0" }}>
                  Set a horizon where start ≤ end.
                </p>
              )}
            </div>
          </>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 14 }}>
          <button className="ghost" onClick={onCancel}>cancel</button>
          <button className="run-button" onClick={save} disabled={mode === "temporal" && !rangeOk}>save</button>
        </div>
      </div>
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────────

/** Years in `periods` within [from, to]; if none, every integer year in range. */
function withinRange(periods: number[], from: number, to: number): number[] {
  const inside = periods.filter((y) => y >= from && y <= to);
  if (inside.length) return inside;
  const out: number[] = [];
  for (let y = Math.ceil(from); y <= Math.floor(to); y++) out.push(y);
  return out.length ? out : [from];
}

/** First candidate year not already used (so ＋ add year never collides). */
function nextUnused(candidates: number[], used: Set<number>, after: number): number {
  for (const y of candidates.filter((c) => c > after).sort((a, b) => a - b)) if (!used.has(y)) return y;
  let y = after + 1;
  while (used.has(y)) y++;
  return y;
}

/** Rebuild the editor state from a stored value: static number, or a temporal map
 *  compressed back to anchors with linear/step detection. */
function reconstruct(
  initial: TemporalVal | null,
  baseYear: number,
  firstYear: number,
  lastYear: number,
): { kind: "static" | "temporal"; staticV: string; fill: Mode; from: number; to: number; anchors: Draft[] } {
  if (!isTemporal(initial)) {
    return {
      kind: "static",
      staticV: initial == null ? "" : String(initial),
      fill: "linear",
      from: firstYear,
      to: lastYear,
      anchors: initial == null ? [] : [{ year: String(baseYear), value: String(initial) }],
    };
  }
  const pts = toPts(initial);
  const from = pts.length ? pts[0].year : firstYear;
  const to = pts.length ? pts[pts.length - 1].year : lastYear;
  const lin = linearCompress(pts);
  const step = stepCompress(pts);
  let fill: Mode = "linear";
  let anchors = lin;
  if (reproduces(lin, pts, "linear")) {
    fill = "linear";
    anchors = lin;
  } else if (reproduces(step, pts, "step")) {
    fill = "step";
    anchors = step;
  } else {
    fill = "linear";
    anchors = pts; // irregular — keep every point so it round-trips exactly
  }
  return {
    kind: "temporal",
    staticV: pts.length ? String(pts[0].value) : "",
    fill,
    from,
    to,
    anchors: anchors.map((p) => ({ year: String(p.year), value: String(p.value) })),
  };
}

/** A small read-only preview of the materialised curve with anchors marked. */
function PreviewChart({
  dense,
  anchors,
  from,
  to,
  unit,
  perYear = true,
}: {
  dense: ByYear;
  anchors: Pt[];
  from: number;
  to: number;
  unit?: string;
  perYear?: boolean;
}) {
  const W = 412;
  const H = 116;
  const padL = 8;
  const padR = 8;
  const padT = 14;
  const padB = 20;
  const pts = toPts(dense);
  const hasRange = Number.isFinite(from) && Number.isFinite(to) && to >= from;
  const allV = [...pts.map((p) => p.value), ...anchors.map((a) => a.value)];
  const vmax = Math.max(1, ...allV);
  const vmin = Math.min(0, ...allV);
  const X = (yr: number) =>
    to === from ? padL + (W - padL - padR) / 2 : padL + ((yr - from) / (to - from)) * (W - padL - padR);
  const Y = (v: number) => padT + (1 - (v - vmin) / (vmax - vmin || 1)) * (H - padT - padB);

  if (!hasRange || !pts.length) {
    return (
      <div style={{ height: H, display: "flex", alignItems: "center", justifyContent: "center", border: "1px solid var(--border)", borderRadius: 6 }}>
        <span className="muted" style={{ fontSize: "0.72rem" }}>add an anchor to preview the trajectory</span>
      </div>
    );
  }
  const anchorYears = new Set(anchors.map((a) => a.year));
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: "block", border: "1px solid var(--border)", borderRadius: 6 }}>
      <line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB} stroke="var(--border)" />
      {pts.length > 1 && (
        <polyline fill="none" stroke="var(--brand)" strokeWidth={1.6} points={pts.map((p) => `${X(p.year)},${Y(p.value)}`).join(" ")} />
      )}
      {pts.map((p) => {
        const isAnchor = anchorYears.has(p.year);
        return (
          <g key={p.year}>
            <circle cx={X(p.year)} cy={Y(p.value)} r={isAnchor ? 4 : 2.4} fill={isAnchor ? "var(--brand-strong)" : "var(--brand)"} stroke="var(--surface)" strokeWidth={1.2} />
            {isAnchor && (
              <text x={X(p.year)} y={Y(p.value) - 7} textAnchor="middle" fontSize={9} fill="var(--text)">{fmt(p.value)}</text>
            )}
          </g>
        );
      })}
      <text x={padL} y={H - 6} fontSize={9} fill="var(--muted)">{from}</text>
      <text x={W - padR} y={H - 6} textAnchor="end" fontSize={9} fill="var(--muted)">{to}</text>
      {unit && <text x={W / 2} y={H - 6} textAnchor="middle" fontSize={9} fill="var(--muted)">{unit}{perYear ? "/yr" : ""}</text>}
    </svg>
  );
}
