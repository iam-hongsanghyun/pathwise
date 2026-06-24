export type View =
  | "project"
  | "component"
  | "facility"
  | "valuechain"
  | "market"
  | "fleet"
  | "targets"
  | "analytics"
  | "settings";

interface Entry {
  id: View;
  label: string;
  icon: JSX.Element;
}

const I = {
  // shared svg props keep the strip visually consistent
  project: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  ),
  component: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2 3 7v10l9 5 9-5V7z" />
      <path d="m3 7 9 5 9-5" />
      <path d="M12 12v10" />
    </svg>
  ),
  facility: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 21h18" />
      <path d="M5 21V8l5-3v16" />
      <path d="M10 21V11l9 4v6" />
      <path d="M13.5 17h2M13.5 19.5h2" />
    </svg>
  ),
  valuechain: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="5" cy="6" r="2.4" />
      <circle cx="5" cy="18" r="2.4" />
      <circle cx="19" cy="12" r="2.4" />
      <path d="M7.3 6.8 16.7 11M7.3 17.2 16.7 13" />
    </svg>
  ),
  market: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v18" />
      <path d="M5 7h14" />
      <path d="M5 7 3 12a3 3 0 0 0 6 0z" />
      <path d="M19 7l2 5a3 3 0 0 1-6 0z" />
      <path d="M8 21h8" />
    </svg>
  ),
  fleet: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 4 3 6.5v13.5l6-2.5 6 2.5 6-2.5V3l-6 2.5z" />
      <path d="M9 4v13.5M15 6.5V20" />
    </svg>
  ),
  targets: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 1v3M12 20v3M1 12h3M20 12h3" />
    </svg>
  ),
  analytics: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3v18h18" />
      <path d="M7 14l3.5-4 3 2.5L21 6" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  ),
};

// Component / Value-chain / Targets / Analytics live at the top; Settings is
// pinned to the bottom of the strip (separated by a flex spacer).
const TOP: Entry[] = [
  { id: "project", label: "Project — name, import/export the whole project (components + facilities + value chain)", icon: I.project },
  { id: "component", label: "Library — shared, reusable building blocks (base catalogue)", icon: I.component },
  { id: "facility", label: "Facility — real-world facilities: capacity, owners & build years", icon: I.facility },
  { id: "valuechain", label: "Value chain — assemble the model (subgroups → companies → facilities)", icon: I.valuechain },
  { id: "fleet", label: "Fleet — transport fleets, ports & routes on a map", icon: I.fleet },
  { id: "market", label: "Market & Policy — supply pools, ETS, carbon price (the institutional layer)", icon: I.market },
  { id: "targets", label: "Targets & constraints — production targets, caps and budgets by scope", icon: I.targets },
  { id: "analytics", label: "Analytics — results & charts", icon: I.analytics },
];
const BOTTOM: Entry = { id: "settings", label: "Settings — scenario, economics & design", icon: I.settings };

interface Props {
  view: View;
  onChange: (v: View) => void;
}

/** Vertical glyph strip — the only view switcher. v2: SVG icons + a wordmark,
 *  themable via the --chrome* tokens. */
export function ActivityBar({ view, onChange }: Props) {
  const btn = (e: Entry) => (
    <button
      key={e.id}
      className={`activity-bar-btn${view === e.id ? " is-active" : ""}`}
      onClick={() => onChange(e.id)}
      title={e.label}
      aria-label={e.label}
      aria-current={view === e.id ? "page" : undefined}
    >
      {e.icon}
    </button>
  );

  return (
    <nav className="activity-bar" aria-label="Views">
      <div className="activity-bar-brand">pathwise</div>
      {TOP.map(btn)}
      <span className="activity-spacer" />
      {btn(BOTTOM)}
    </nav>
  );
}
