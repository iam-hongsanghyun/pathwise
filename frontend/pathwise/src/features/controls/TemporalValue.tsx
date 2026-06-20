// A value that is STATIC (one number, applied to every year) or TEMPORAL (a value
// per year). Renders a compact button showing the value or "↗ N yr"; clicking opens
// an editor — a Static ↔ Temporal toggle, with the temporal mode an editable
// year line-chart (reused from the component view) — with save / cancel.
//
// Used for the Optimisation constraints and the machine output / input bounds.

import { useState } from "react";
import { YearSeriesChart } from "../component/YearSeriesChart";
import type { ByYear } from "../../lib/api/components";

/** A bound value: a scalar (all years) or a {year: value} map. */
export type TemporalVal = number | ByYear;

const fmt = (x: number): string => (Number.isInteger(x) ? x.toLocaleString() : x.toFixed(2));
const isTemporal = (v: TemporalVal | null): v is ByYear => v != null && typeof v !== "number";
const firstVal = (b: ByYear): number => {
  const ys = Object.keys(b).map(Number).filter(Number.isFinite).sort((a, c) => a - c);
  return ys.length ? b[String(ys[0])] : 0;
};

export function TemporalValue({
  value,
  onChange,
  label,
  unit,
  baseYear,
  placeholder = "set…",
}: {
  value: TemporalVal | null;
  onChange: (v: TemporalVal | null) => void;
  label: string;
  unit?: string;
  baseYear: number;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const text =
    value == null
      ? placeholder
      : isTemporal(value)
        ? `↗ ${Object.keys(value).length} yr`
        : fmt(value);
  return (
    <>
      <button className="temporal-btn" title="edit value — static or by-year" onClick={() => setOpen(true)}>
        <span>{text}</span>
        {unit && value != null ? <span className="muted"> {unit}/yr</span> : null}
      </button>
      {open && (
        <Editor
          initial={value}
          label={label}
          unit={unit}
          baseYear={baseYear}
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
  baseYear,
  onSave,
  onCancel,
}: {
  initial: TemporalVal | null;
  label: string;
  unit?: string;
  baseYear: number;
  onSave: (v: TemporalVal | null) => void;
  onCancel: () => void;
}) {
  const [mode, setMode] = useState<"static" | "temporal">(isTemporal(initial) ? "temporal" : "static");
  const [staticV, setStaticV] = useState<string>(
    initial == null ? "" : isTemporal(initial) ? String(firstVal(initial)) : String(initial),
  );
  const [byYear, setByYear] = useState<ByYear>(
    isTemporal(initial) ? { ...initial } : initial != null ? { [String(baseYear)]: initial } : {},
  );

  function save() {
    if (mode === "static") onSave(staticV.trim() === "" ? null : Number(staticV) || 0);
    else onSave(Object.keys(byYear).length ? byYear : null);
  }

  return (
    <div className="modal-scrim" onClick={onCancel}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="eyebrow">value</div>
        <h3 style={{ margin: "2px 0 4px" }}>{label}</h3>
        <p className="muted" style={{ fontSize: "0.74rem", margin: "0 0 12px" }}>
          One value for the whole horizon, or a value per year (click a point to edit, ＋ year to add).
        </p>
        <div className="seg" style={{ flex: "none", marginBottom: 12 }}>
          <button className={mode === "static" ? "is-active" : ""} onClick={() => setMode("static")}>Static</button>
          <button className={mode === "temporal" ? "is-active" : ""} onClick={() => setMode("temporal")}>Temporal</button>
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
            {unit ? <span className="muted">{unit}/yr</span> : null}
          </label>
        ) : (
          <YearSeriesChart
            values={byYear}
            fallback={Number(staticV) || 0}
            label={unit ? `value (${unit}/yr)` : "value / yr"}
            onChange={setByYear}
          />
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 14 }}>
          <button className="ghost" onClick={onCancel}>cancel</button>
          <button className="run-button" onClick={save}>save</button>
        </div>
      </div>
    </div>
  );
}
