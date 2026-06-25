// AccordionSidebar — a single left sidebar that collapses to a slim strip and,
// when open, renders a vertical stack of independently-collapsible sections.
// Each section has a clickable header (chevron + title + optional headAction)
// and, when open, its body. Multiple sections may be open simultaneously.
// Open sections' bodies share the remaining vertical space (flex: 1 1 0;
// min-height: 0; overflow: auto) unless the section opts out with grow:false.

import { useState, type ReactNode } from "react";
import { Resizer } from "./Resizer";

export interface AccordionSection {
  id: string;
  title: string;
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

  // Count how many open sections want to grow so we can distribute flex space.
  const openGrowing = sections.filter((s) => sectionOpen[s.id] !== false && s.grow !== false).length;

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

        {sections.map((sec) => {
          const isOpen = sectionOpen[sec.id] !== false;
          const grows = isOpen && sec.grow !== false;
          return (
            <div
              key={sec.id}
              className="acc-section"
              style={{
                display: "flex",
                flexDirection: "column",
                flex: grows ? "1 1 0" : "0 0 auto",
                minHeight: 0,
                borderTop: "1px solid var(--border)",
              }}
            >
              {/* Section header — behaves like .rail-head-row.is-divided */}
              <button
                className="acc-head"
                onClick={() => toggleSection(sec.id)}
                title={`${isOpen ? "collapse" : "expand"} ${sec.title}`}
              >
                <span className="acc-chevron">{isOpen ? "▾" : "▸"}</span>
                <span className="rail-head" style={{ flex: 1, padding: 0 }}>{sec.title}</span>
                {sec.headAction && (
                  <span
                    className="acc-head-action"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {sec.headAction}
                  </span>
                )}
              </button>

              {/* Section body — only rendered when open */}
              {isOpen && (
                <div
                  className="acc-body"
                  style={{
                    flex: grows && openGrowing > 0 ? "1 1 0" : "0 0 auto",
                    minHeight: 0,
                    overflow: "auto",
                  }}
                >
                  {sec.body}
                </div>
              )}
            </div>
          );
        })}
      </aside>
      <Resizer width={width} setWidth={setWidth} side="left" min={min} max={max} />
    </>
  );
}
