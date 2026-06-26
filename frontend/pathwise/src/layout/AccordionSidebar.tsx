// AccordionSidebar — a single left sidebar that collapses to a slim strip and,
// when open, renders a vertical stack of independently-collapsible sections.
// Each section has a clickable header (chevron + title + optional headAction)
// and, when open, its body. Multiple sections may be open simultaneously.
// Open sections' bodies share the remaining vertical space (flex: 1 1 0;
// min-height: 0; overflow: auto) unless the section opts out with grow:false.

import { Fragment, useState, type ReactNode } from "react";
import { InfoTooltip } from "../features/controls/InfoTooltip";
import { Resizer } from "./Resizer";

export interface AccordionSection {
  id: string;
  title: string;
  /** One-line explanation shown behind a (ⓘ) next to the title (keeps the body clean). */
  info?: string;
  /** Optional node rendered on the right side of the section header. */
  headAction?: ReactNode;
  body: ReactNode;
  /** Whether the section starts open. Default true. */
  defaultOpen?: boolean;
  /** Whether the body participates in the flex-grow layout. Default true.
   *  Set false for small, fixed-height bodies (e.g. a form or a short list). */
  grow?: boolean;
}

interface Props {
  side?: "left";
  open: boolean;
  setOpen: (open: boolean) => void;
  width: number;
  setWidth: (w: number) => void;
  min?: number;
  max?: number;
  /** Extra nodes shown in the collapsed strip (e.g. an ＋ add button). */
  collapsedExtras?: ReactNode;
  sections: AccordionSection[];
}

/** Single collapsible left sidebar with independently-collapsible accordion
 *  sections inside. The outer rail collapses to a slim strip (reuses the
 *  CollapsibleRail collapse-strip pattern); when open the sidebar contains a
 *  vertical stack of sections that share the available height. */
export function AccordionSidebar({
  open,
  setOpen,
  width,
  setWidth,
  min = 200,
  max = 440,
  collapsedExtras,
  sections,
}: Props) {
  // Each section tracks its own open/closed state independently.
  const [sectionOpen, setSectionOpen] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const s of sections) init[s.id] = s.defaultOpen !== false;
    return init;
  });

  const toggleSection = (id: string) =>
    setSectionOpen((prev) => ({ ...prev, [id]: !prev[id] }));

  // User-set heights (px) for sections resized via the dividers between them. A
  // section without an entry uses the default flex layout; the last OPEN section
  // always flex-grows to fill, so the rail stays full however the others are sized.
  const [heights, setHeights] = useState<Record<string, number>>({});
  const SECTION_MIN = 80; // matches the open-section min-height (5rem)
  const startResize = (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    const handle = e.currentTarget as HTMLElement;
    const sectionEl = handle.previousElementSibling as HTMLElement | null;
    const rail = handle.closest(".acc-sidebar") as HTMLElement | null;
    const start = sectionEl?.offsetHeight ?? 120;
    // Growing this section pushes the last (flex-grow) open section down; it may
    // only shrink to its floor, beyond which the rail would overflow the window and
    // the bottom section would slide out of view. Cap growth at that available room
    // (measured at drag start) so everything stays inside the rail.
    let room = Number.POSITIVE_INFINITY;
    if (rail && sectionEl) {
      const open = [...rail.querySelectorAll<HTMLElement>(".acc-section")].filter((s) =>
        s.querySelector(".acc-body"),
      );
      const last = open[open.length - 1];
      room = last && last !== sectionEl ? Math.max(0, last.offsetHeight - SECTION_MIN) : 0;
    }
    const maxH = start + room;
    const startY = e.clientY;
    const move = (ev: MouseEvent) =>
      setHeights((prev) => ({
        ...prev,
        [id]: Math.min(maxH, Math.max(SECTION_MIN, start + (ev.clientY - startY))),
      }));
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  if (!open) {
    return (
      <div className="rail-collapsed">
        <button className="rail-collapse" title="show panel" onClick={() => setOpen(true)}>
          ›
        </button>
        {collapsedExtras}
      </div>
    );
  }

  return (
    <>
      <aside
        className="builder-rail acc-sidebar"
        style={{ width, display: "flex", flexDirection: "column", overflow: "hidden" }}
      >
        {/* Rail-level collapse button */}
        <div className="rail-head-row">
          <button className="rail-collapse" title="hide panel" onClick={() => setOpen(false)}>
            ‹
          </button>
        </div>

        {(() => {
          const openIds = sections.filter((s) => sectionOpen[s.id] !== false).map((s) => s.id);
          const lastOpenId = openIds[openIds.length - 1];
          return sections.map((sec) => {
          const isOpen = sectionOpen[sec.id] !== false;
          const isLastOpen = sec.id === lastOpenId;
          const h = heights[sec.id];
          // A user-sized open section is fixed at its height; the last open section
          // always grows to fill; otherwise the default content/grow layout.
          const sized = isOpen && !isLastOpen && h != null;
          const grows = isOpen && (isLastOpen || (sec.grow !== false && h == null));
          return (
            <Fragment key={sec.id}>
            <div
              className="acc-section"
              style={{
                display: "flex",
                flexDirection: "column",
                // Basis = content (auto), not 0, so a short open section doesn't claim an
                // equal share of the rail; grow:true also fills free space. Both shrink
                // (min-height:0) so an over-tall section scrolls its own body instead of
                // pushing the whole rail.
                flex: sized ? "0 0 auto" : grows ? "1 1 auto" : "0 1 auto",
                height: sized ? h : undefined,
                // Floor ONLY when open, so a squeezed open section keeps its header + a
                // row or two and scrolls its own body. A CLOSED section is just its
                // header height (no 5rem gap between collapsed sections).
                minHeight: isOpen ? "5rem" : undefined,
                borderTop: "1px solid var(--border)",
              }}
            >
              {/* Section header — behaves like .rail-head-row.is-divided. A
                  <div role="button"> rather than a <button> so the optional
                  headAction (often itself a <button>) doesn't nest button-in-button. */}
              <div
                className="acc-head"
                role="button"
                tabIndex={0}
                onClick={() => toggleSection(sec.id)}
                onKeyDown={(e) => {
                  // Only the header itself toggles; ignore keys from the headAction.
                  if (e.target !== e.currentTarget) return;
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    toggleSection(sec.id);
                  }
                }}
                title={`${isOpen ? "collapse" : "expand"} ${sec.title}`}
              >
                <span className="acc-chevron">{isOpen ? "▾" : "▸"}</span>
                <span
                  className="rail-head"
                  style={{ width: "auto", padding: 0, display: "inline-flex", alignItems: "center", gap: 4 }}
                >
                  {sec.title}
                  {sec.info && (
                    <span style={{ display: "inline-flex" }} onClick={(e) => e.stopPropagation()}>
                      <InfoTooltip text={sec.info} />
                    </span>
                  )}
                </span>
                <span style={{ flex: 1 }} />
                {sec.headAction && (
                  <span
                    className="acc-head-action"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {sec.headAction}
                  </span>
                )}
              </div>

              {/* Section body — only rendered when open */}
              {isOpen && (
                <div
                  className="acc-body"
                  style={{
                    flex: "1 1 auto",
                    minHeight: 0,
                    overflow: "auto",
                  }}
                >
                  {sec.body}
                </div>
              )}
            </div>
            {/* Drag-to-resize divider between this open section and the next. The
                last open section flex-grows, so it has no handle. */}
            {isOpen && !isLastOpen && (
              <div
                className="acc-resizer"
                onMouseDown={(e) => startResize(e, sec.id)}
                role="separator"
                aria-orientation="horizontal"
                title="Drag to resize this section"
              />
            )}
            </Fragment>
          );
          });
        })()}
      </aside>
      <Resizer width={width} setWidth={setWidth} side="left" min={min} max={max} />
    </>
  );
}
