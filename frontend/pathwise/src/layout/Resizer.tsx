interface Props {
  width: number;
  setWidth: (w: number) => void;
  side: "left" | "right";
  min?: number;
  max?: number;
}

/** A draggable divider that resizes an adjacent rail. */
export function Resizer({ width, setWidth, side, min = 160, max = 520 }: Props) {
  const onMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = width;
    const move = (ev: MouseEvent) => {
      const delta = ev.clientX - startX;
      const w = side === "left" ? startW + delta : startW - delta;
      setWidth(Math.min(max, Math.max(min, w)));
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };
  return <div className="resizer" onMouseDown={onMouseDown} role="separator" aria-orientation="vertical" />;
}
