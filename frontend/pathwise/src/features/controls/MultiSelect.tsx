// A searchable multi-select dropdown (checkbox list). Used to pick which units
// (items at the chosen level) to optimise. Operates on an explicit Set of ids;
// "all selected" is just every id checked.

import { useEffect, useMemo, useRef, useState } from "react";

interface Props {
  options: { id: string; label: string }[];
  selected: Set<string>;
  onChange: (s: Set<string>) => void;
  /** Shown before the summary, e.g. "units". */
  label?: string;
  disabled?: boolean;
}

export function MultiSelect({ options, selected, onChange, label, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const shown = useMemo(
    () => options.filter((o) => o.label.toLowerCase().includes(q.toLowerCase())),
    [options, q],
  );
  const all = options.length > 0 && selected.size === options.length;
  const summary = options.length === 0 ? "—" : all ? `all (${options.length})` : `${selected.size} of ${options.length}`;

  const toggle = (id: string) => {
    const s = new Set(selected);
    if (s.has(id)) s.delete(id);
    else s.add(id);
    onChange(s);
  };

  return (
    <div className="combo" ref={wrap} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        className="ghost"
        disabled={disabled || options.length === 0}
        onClick={() => setOpen((o) => !o)}
        style={{ ...box, minWidth: 120, textAlign: "left" }}
        title="which units to optimise"
      >
        {label ? `${label}: ` : ""}
        {summary} ▾
      </button>
      {open && (
        <div
          className="combo-list"
          style={{
            position: "absolute",
            zIndex: 1000,
            marginTop: 2,
            minWidth: 220,
            maxHeight: 280,
            overflow: "auto",
            background: "var(--surface)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--radius-button)",
            boxShadow: "0 6px 24px rgba(0,0,0,0.12)",
            padding: 6,
          }}
        >
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="search units…" style={{ ...box, width: "100%", marginBottom: 6 }} />
          <div style={{ display: "flex", gap: 8, marginBottom: 6, fontSize: "0.74rem" }}>
            <button type="button" className="ghost" onClick={() => onChange(new Set(options.map((o) => o.id)))}>all</button>
            <button type="button" className="ghost" onClick={() => onChange(new Set())}>none</button>
          </div>
          {shown.map((o) => (
            <label key={o.id} style={{ display: "flex", gap: 6, alignItems: "center", padding: "2px 0", fontSize: "0.82rem", cursor: "pointer" }}>
              <input type="checkbox" checked={selected.has(o.id)} onChange={() => toggle(o.id)} />
              {o.label}
            </label>
          ))}
          {shown.length === 0 && <div className="rail-empty" style={{ fontSize: "0.74rem" }}>no matches</div>}
        </div>
      )}
    </div>
  );
}

const box: React.CSSProperties = {
  padding: "3px 6px",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-button)",
  background: "var(--surface)",
  font: "inherit",
  fontSize: "0.78rem",
};
