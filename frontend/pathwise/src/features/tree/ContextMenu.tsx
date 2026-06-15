// A small fixed-position right-click menu. Closes on outside click / Escape /
// scroll. Reuses the existing `.context-menu` CSS (with inline fallbacks).

import { useEffect, useRef } from "react";
import type { TreeAction } from "./types";

interface Props {
  x: number;
  y: number;
  actions: TreeAction[];
  onAction: (id: string) => void;
  onClose: () => void;
}

export function ContextMenu({ x, y, actions, onAction, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent && e.key !== "Escape") return;
      if (e.type === "mousedown" && ref.current?.contains(e.target as Node)) return;
      onClose();
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    window.addEventListener("scroll", onClose, true);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
      window.removeEventListener("scroll", onClose, true);
    };
  }, [onClose]);

  if (actions.length === 0) return null;
  return (
    <div
      ref={ref}
      className="context-menu"
      style={{
        position: "fixed",
        left: x,
        top: y,
        zIndex: 1000,
        minWidth: 160,
        background: "var(--surface)",
        border: "1px solid var(--border-strong)",
        borderRadius: "var(--radius-button)",
        boxShadow: "0 6px 24px rgba(0,0,0,0.12)",
        padding: "4px 0",
        fontSize: "0.82rem",
      }}
    >
      {actions.map((a) => (
        <div key={a.id}>
          {a.separatorBefore && (
            <div style={{ borderTop: "1px solid var(--border)", margin: "4px 0" }} />
          )}
          <button
            type="button"
            className={`context-menu-item${a.danger ? " danger" : ""}`}
            onClick={() => {
              onAction(a.id);
              onClose();
            }}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              border: "none",
              background: "transparent",
              padding: "5px 14px",
              cursor: "pointer",
              color: a.danger ? "var(--danger)" : "var(--text)",
              font: "inherit",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "var(--brand-fill)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
          >
            {a.label}
          </button>
        </div>
      ))}
    </div>
  );
}
