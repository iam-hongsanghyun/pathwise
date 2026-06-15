// A searchable multi-select dropdown (checkbox list). Used to pick which units
// (items at the chosen level) to optimise. Operates on an explicit Set of ids;
// "all selected" is just every id checked. Self-contained styling (no .combo
// class, so the SearchableSelect input rules don't bleed onto the checkboxes).

import { useEffect, useMemo, useRef, useState } from "react";

interface Props {
  options: { id: string; label: string }[];
  selected: Set<string>;
  onChange: (s: Set<string>) => void;
  label?: string;
  disabled?: boolean;
}

const box: React.CSSProperties = {
  padding: "3px 8px",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-button)",
  background: "var(--surface)",
  font: "inherit",
  fontSize: "0.78rem",
};

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
  const summary = options.length === 0 ? "—" : all ? `all (${options.length})` : `${selected.size}/${options.length}`;

  const toggle = (id: string) => {
    const s = new Set(selected);
    if (s.has(id)) s.delete(id);
    else s.add(id);
    onChange(s);
  };

  return (
    <div ref={wrap} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        disabled={disabled || options.length === 0}
        onClick={() => setOpen((o) => !o)}
        style={{ ...box, minWidth: 110, textAlign: "left", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6 }}
        title="which units to optimise"
      >
        <span className="muted">{label ?? "units"}:</span> {summary} <span style={{ marginLeft: "auto", opacity: 0.6 }}>▾</span>
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            zIndex: 1000,
            marginTop: 2,
            width: 240,
            maxHeight: 300,
            overflow: "auto",
            background: "var(--surface)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--radius-button)",
            boxShadow: "0 6px 24px rgba(0,0,0,0.14)",
            padding: 8,
          }}
        >
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="search units…" style={{ ...box, width: "100%", boxSizing: "border-box", marginBottom: 8 }} />
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
            <button type="button" onClick={() => onChange(new Set(options.map((o) => o.id)))} style={{ ...box, padding: "2px 8px", cursor: "pointer" }}>all</button>
            <button type="button" onClick={() => onChange(new Set())} style={{ ...box, padding: "2px 8px", cursor: "pointer" }}>none</button>
          </div>
          {shown.map((o) => (
            <label key={o.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 2px", fontSize: "0.82rem", cursor: "pointer", borderRadius: 3 }}>
              <input type="checkbox" checked={selected.has(o.id)} onChange={() => toggle(o.id)} style={{ width: 14, height: 14, flexShrink: 0, margin: 0 }} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{o.label}</span>
            </label>
          ))}
          {shown.length === 0 && <div className="muted" style={{ fontSize: "0.74rem", padding: 4 }}>no matches</div>}
        </div>
      )}
    </div>
  );
}
