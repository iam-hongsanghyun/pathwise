interface Props {
  width: number;
  setWidth: (w: number) => void;
  /** Which edge: left/right resize width; top resizes the panel below (height). */
  side: "left" | "right" | "top";
  min?: number;
  max?: number;
}

/** A draggable divider. `left`/`right` resize an adjacent rail's width; `top`
 *  resizes the height of the panel beneath it (drag up to grow). */
export function Resizer({ width, setWidth, side, min = 160, max = 520 }: Props) {
  const vertical = side === "top";
  const onMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    const start = vertical ? e.clientY : e.clientX;
    const startW = width;
    const move = (ev: MouseEvent) => {
      const delta = (vertical ? ev.clientY : ev.clientX) - start;
      // left grows with +x; right and top (drag up) grow with −delta.
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
  return (
    <div
      className={vertical ? "resizer-h" : "resizer"}
      onMouseDown={onMouseDown}
      role="separator"
      aria-orientation={vertical ? "horizontal" : "vertical"}
    />
  );
}
