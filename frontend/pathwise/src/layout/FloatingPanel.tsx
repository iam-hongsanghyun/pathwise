// A draggable, resizable floating panel — drag its header to move it, drag the
// bottom-right grip to resize. Used by the Value Chain to show a clicked item's
// inspector over the canvas instead of a fixed right rail.

import { useRef, useState } from "react";

interface Props {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  width?: number;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function FloatingPanel({ title, onClose, children, width = 340 }: Props) {
  const [pos, setPos] = useState<{ x: number; y: number }>(() => ({
    x: Math.max(window.innerWidth - width - 36, 80),
    y: 96,
  }));
  // Width is explicit from the start; height stays auto (content-driven, capped by
  // CSS max-height) until the user resizes, then it becomes explicit too.
  const [size, setSize] = useState<{ w: number; h: number | null }>({ w: width, h: null });
  const panelRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ ox: number; oy: number } | null>(null);
  const resz = useRef<{ ox: number; oy: number; w: number; h: number } | null>(null);

  function onDown(e: React.MouseEvent) {
    if ((e.target as HTMLElement).closest("button, .float-panel-resize")) return;
    drag.current = { ox: e.clientX - pos.x, oy: e.clientY - pos.y };
    const move = (ev: MouseEvent) => {
      if (!drag.current) return;
      setPos({
        x: Math.min(Math.max(ev.clientX - drag.current.ox, 0), window.innerWidth - 80),
        y: Math.min(Math.max(ev.clientY - drag.current.oy, 0), window.innerHeight - 40),
      });
    };
    const up = () => {
      drag.current = null;
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  function onResizeDown(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    const startH = size.h ?? panelRef.current?.offsetHeight ?? 400;
    resz.current = { ox: e.clientX, oy: e.clientY, w: size.w, h: startH };
    const move = (ev: MouseEvent) => {
      if (!resz.current) return;
      setSize({
        w: clamp(resz.current.w + (ev.clientX - resz.current.ox), 240, window.innerWidth - pos.x - 8),
        h: clamp(resz.current.h + (ev.clientY - resz.current.oy), 140, window.innerHeight - pos.y - 8),
      });
    };
    const up = () => {
      resz.current = null;
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  return (
    <div
      ref={panelRef}
      className="float-panel"
      style={{ left: pos.x, top: pos.y, width: size.w, height: size.h ?? undefined, maxHeight: size.h != null ? "none" : undefined }}
    >
      <div className="float-panel-head" onMouseDown={onDown}>
        <span className="float-panel-title">{title}</span>
        <button className="float-panel-close" onClick={onClose} title="close">
          ✕
        </button>
      </div>
      <div className="float-panel-body">{children}</div>
      <div className="float-panel-resize" onMouseDown={onResizeDown} title="drag to resize" />
    </div>
  );
}
