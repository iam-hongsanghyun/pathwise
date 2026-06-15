// Breadcrumb navigation for the Chain Design view.
// Shows the current drill-down path as clickable crumbs; the last is
// non-clickable (current level). A synthetic "Top" root crumb is always shown.

import type { GroupNode } from "../lib/groupGraph";

interface Props {
  /** Ordered path from the root to the current group (may be empty at top). */
  path: GroupNode[];
  /** Called when the user clicks crumb at index `i` in `path`. Index -1 = Top. */
  onJump: (index: number) => void;
}

/** Horizontal breadcrumb strip for navigating the group hierarchy. */
export function Breadcrumb({ path, onJump }: Props) {
  return (
    <nav
      className="chain-breadcrumb"
      aria-label="Chain design navigation"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 0,
        padding: "6px 14px",
        borderBottom: "1px solid var(--border)",
        background: "var(--surface)",
        fontSize: "0.8rem",
        flexWrap: "wrap",
        flexShrink: 0,
      }}
    >
      {/* Root / Top crumb */}
      {path.length === 0 ? (
        <span
          aria-current="page"
          style={{ fontWeight: 600, color: "var(--text)" }}
        >
          Value chain
        </span>
      ) : (
        <button
          className="ghost"
          style={{
            padding: "1px 6px",
            fontSize: "0.8rem",
            border: "none",
            background: "transparent",
            color: "var(--brand)",
          }}
          onClick={() => onJump(-1)}
        >
          Value chain
        </button>
      )}

      {/* Path crumbs */}
      {path.map((nd, i) => {
        const isLast = i === path.length - 1;
        return (
          <span key={nd.id} style={{ display: "flex", alignItems: "center", gap: 0 }}>
            <span
              style={{
                color: "var(--muted)",
                padding: "0 4px",
                userSelect: "none",
              }}
              aria-hidden
            >
              /
            </span>
            {isLast ? (
              <span
                aria-current="page"
                style={{ fontWeight: 600, color: "var(--text)" }}
              >
                {nd.label}
              </span>
            ) : (
              <button
                className="ghost"
                style={{
                  padding: "1px 6px",
                  fontSize: "0.8rem",
                  border: "none",
                  background: "transparent",
                  color: "var(--brand)",
                }}
                onClick={() => onJump(i)}
              >
                {nd.label}
              </button>
            )}
          </span>
        );
      })}
    </nav>
  );
}
