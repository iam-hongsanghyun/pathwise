import { useRef, useState } from "react";
import { createPortal } from "react-dom";

/** The (i) marker with its explanation popup. Rendered into document.body at a
 *  fixed position so it always sits on top — never clipped by table scroll
 *  areas, docks, or modals. */
export function InfoTip({ tip }: { tip: string }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const ref = useRef<HTMLSpanElement>(null);
  return (
    <span
      ref={ref}
      className="col-info"
      onMouseEnter={() => {
        const r = ref.current?.getBoundingClientRect();
        if (r) setPos({ x: Math.min(r.left, window.innerWidth - 270), y: r.bottom + 6 });
      }}
      onMouseLeave={() => setPos(null)}
    >
      {" "}
      ⓘ
      {pos &&
        createPortal(
          <div className="tip-popup" style={{ left: pos.x, top: pos.y }}>
            {tip}
          </div>,
          document.body,
        )}
    </span>
  );
}
