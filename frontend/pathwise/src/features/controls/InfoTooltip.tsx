// A small (i) info icon that reveals an explanation + unit on hover/focus.
// The pop is portaled to <body> with position:fixed so it is never clipped by a
// scroll container (e.g. a tab's overflow:auto main area) and always paints on top.

import { useRef, useState } from "react";
import { createPortal } from "react-dom";

export function InfoTooltip({ text, unit }: { text: string; unit?: string }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const ref = useRef<HTMLSpanElement>(null);
  if (!text && !unit) return null;

  const show = () => {
    const r = ref.current?.getBoundingClientRect();
    if (r) setPos({ top: r.bottom + 6, left: Math.max(8, Math.min(r.left, window.innerWidth - 272)) });
    setOpen(true);
  };
  const hide = () => setOpen(false);

  return (
    <span
      ref={ref}
      className="info-icon"
      tabIndex={0}
      role="img"
      // No native `title`: it would render a SECOND browser tooltip overlapping the
      // custom .info-pop below. aria-label keeps the text for screen readers.
      aria-label={unit ? `${text} (unit: ${unit})` : text}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      ⓘ
      {open &&
        pos &&
        createPortal(
          <span
            className="info-pop"
            role="tooltip"
            style={{ position: "fixed", top: pos.top, left: pos.left, bottom: "auto", transform: "none", zIndex: 4000 }}
          >
            {text}
            {unit && (
              <span className="info-unit">
                unit: <code>{unit}</code>
              </span>
            )}
          </span>,
          document.body,
        )}
    </span>
  );
}
