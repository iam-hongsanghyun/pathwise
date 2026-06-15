export type View = "component" | "valuechain" | "analytics" | "settings";

const ENTRIES: { id: View; glyph: string; label: string }[] = [
  { id: "component", glyph: "C", label: "Component — build reusable components in libraries" },
  { id: "valuechain", glyph: "V", label: "Value chain — assemble the model (subgroups → companies → facilities)" },
  { id: "analytics", glyph: "A", label: "Analytics — results & charts" },
  { id: "settings", glyph: "S", label: "Settings — snapshots & scenario" },
];

interface Props {
  view: View;
  onChange: (v: View) => void;
}

/** Vertical glyph strip — the only view switcher (Ragnarok-style). Model is the
 *  single editing surface (process map + tree + tables + detail); Analytics
 *  shows results; Settings holds scenario/snapshots. */
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
