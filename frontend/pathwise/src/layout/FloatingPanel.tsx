// A draggable floating panel — drag its header to move it. Used by the Value
// Chain to show a clicked item's inspector over the canvas instead of a fixed
// right rail.

import { useRef, useState } from "react";

interface Props {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  width?: number;
}

export function FloatingPanel({ title, onClose, children, width = 340 }: Props) {
  const [pos, setPos] = useState<{ x: number; y: number }>(() => ({
    x: Math.max(window.innerWidth - width - 36, 80),
    y: 96,
  }));
  const drag = useRef<{ ox: number; oy: number } | null>(null);

  function onDown(e: React.MouseEvent) {
    if ((e.target as HTMLElement).closest("button")) return; // let the close button click
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

  return (
    <div className="float-panel" style={{ left: pos.x, top: pos.y, width }}>
      <div className="float-panel-head" onMouseDown={onDown}>
        <span className="float-panel-title">{title}</span>
        <button className="float-panel-close" onClick={onClose} title="close">
          ✕
        </button>
      </div>
      <div className="float-panel-body">{children}</div>
    </div>
  );
}
