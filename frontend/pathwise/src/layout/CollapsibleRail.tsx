// A builder rail (left or right) that collapses to a slim strip and expands back —
// the one shared collapse code path for every tab. Formalises the pattern that the
// Network rail already used. The resize handle sits on the rail's INNER edge, so
// a left rail renders [aside][Resizer] and a right rail renders [Resizer][aside].

import type { ReactNode } from "react";
import { Resizer } from "./Resizer";

interface Props {
  side: "left" | "right";
  open: boolean;
  setOpen: (open: boolean) => void;
  width: number;
  setWidth: (w: number) => void;
  /** Title shown in the head row (omit for a rail whose body has its own heads). */
  title?: string;
  /** Action(s) on the right of the head row (e.g. a ＋ add button). */
  headAction?: ReactNode;
  /** The rail body. Wrapped in a scrolling area unless ``scroll={false}``. */
  children: ReactNode;
  foot?: ReactNode;
  /** Extra controls shown in the collapsed strip (e.g. the ＋ add button). */
  collapsedExtras?: ReactNode;
  /** Wrap children in `.rail-scroll` (default). Set false for a multi-section body. */
  scroll?: boolean;
  min?: number;
  max?: number;
}

export function CollapsibleRail({
  side,
  open,
  setOpen,
  width,
  setWidth,
  title,
  headAction,
  children,
  foot,
  collapsedExtras,
  scroll = true,
  min = 200,
  max = 440,
}: Props) {
  if (!open) {
    return (
      <div className={`rail-collapsed${side === "right" ? " is-right" : ""}`}>
        <button
          className="rail-collapse"
          title={`show ${title || "panel"}`}
          onClick={() => setOpen(true)}
        >
          {side === "right" ? "‹" : "›"}
        </button>
        {collapsedExtras}
      </div>
    );
  }
  const aside = (
    <aside
      className={`builder-rail${side === "right" ? " is-right" : ""}`}
      style={{ width, overflow: scroll ? undefined : "hidden" }}
    >
      <div className="rail-head-row">
        <button
          className="rail-collapse"
          title={`hide ${title || "panel"}`}
          onClick={() => setOpen(false)}
        >
          {side === "right" ? "›" : "‹"}
        </button>
        {title && <span className="rail-head">{title}</span>}
        {headAction}
      </div>
      {scroll ? <div className="rail-scroll">{children}</div> : children}
      {foot && <div className="rail-foot">{foot}</div>}
    </aside>
  );
  const resizer = <Resizer width={width} setWidth={setWidth} side={side} min={min} max={max} />;
  return side === "right" ? (
    <>
      {resizer}
      {aside}
    </>
  ) : (
    <>
      {aside}
      {resizer}
    </>
  );
}
