// A small (i) info icon that reveals an explanation + unit on hover/focus.
// Used next to every Component-builder field so a non-expert user can learn what
// each input means and what units it is in.

import { useState } from "react";

export function InfoTooltip({ text, unit }: { text: string; unit?: string }) {
  const [open, setOpen] = useState(false);
  if (!text && !unit) return null;
  return (
    <span
      className="info-icon"
      tabIndex={0}
      role="img"
      aria-label={unit ? `${text} (unit: ${unit})` : text}
      title={unit ? `${text}\nunit: ${unit}` : text}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      ⓘ
      {open && (
        <span className="info-pop" role="tooltip">
          {text}
          {unit && (
            <span className="info-unit">
              unit: <code>{unit}</code>
            </span>
          )}
        </span>
      )}
    </span>
  );
}
