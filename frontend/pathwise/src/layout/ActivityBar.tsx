export type View = "designer" | "tables" | "macc" | "results" | "settings";

const ENTRIES: { id: View; glyph: string; label: string }[] = [
  { id: "designer", glyph: "F", label: "Facility designer" },
  { id: "tables", glyph: "D", label: "Data tables" },
  { id: "macc", glyph: "M", label: "MACC" },
  { id: "results", glyph: "R", label: "Results" },
  { id: "settings", glyph: "S", label: "Settings" },
];

interface Props {
  view: View;
  onChange: (v: View) => void;
}

/** Vertical glyph strip — the only view switcher (Ragnarok-style). */
export function ActivityBar({ view, onChange }: Props) {
  return (
    <nav className="activity-bar" aria-label="Views">
      <div className="activity-bar-brand">pathwise</div>
      {ENTRIES.map((e) => (
        <button
          key={e.id}
          className={`activity-bar-btn${view === e.id ? " is-active" : ""}`}
          onClick={() => onChange(e.id)}
          title={e.label}
          aria-label={e.label}
          aria-current={view === e.id ? "page" : undefined}
        >
          {e.glyph}
        </button>
      ))}
    </nav>
  );
}
