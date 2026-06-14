export type View = "model" | "valuechain" | "chain" | "analytics" | "settings";

const ENTRIES: { id: View; glyph: string; label: string }[] = [
  { id: "model", glyph: "M", label: "Model — process map + all editing" },
  { id: "valuechain", glyph: "V", label: "Value chain — coupled stages across sectors/regions" },
  { id: "chain", glyph: "C", label: "Chain — group/component topology" },
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
