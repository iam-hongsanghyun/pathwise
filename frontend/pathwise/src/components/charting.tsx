import { type RefObject, useRef, useState } from "react";

/** Shared hover-tooltip plumbing for the hand-rolled SVG charts.
 *
 *  Charts wrap their `<svg>` in a `div.chart-wrap` (position: relative) and call
 *  `show(e, …)` from element mouse handlers; `<ChartTip>` renders an absolutely
 *  positioned HTML box at the cursor. No chart dependency — just React state. */
export interface TipState {
  left: number;
  top: number;
  title?: string;
  rows: string[];
}

export interface Tip {
  tip: TipState | null;
  wrapRef: RefObject<HTMLDivElement>;
  show: (e: { clientX: number; clientY: number }, rows: string[], title?: string) => void;
  hide: () => void;
}

export function useTip(): Tip {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<TipState | null>(null);
  const show = (e: { clientX: number; clientY: number }, rows: string[], title?: string) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTip({ left: e.clientX - rect.left, top: e.clientY - rect.top, rows, title });
  };
  return { tip, wrapRef, show, hide: () => setTip(null) };
}

export function ChartTip({ tip }: { tip: TipState | null }) {
  if (!tip) return null;
  return (
    <div className="chart-tip" style={{ left: tip.left, top: tip.top }}>
      {tip.title && <div className="chart-tip-title">{tip.title}</div>}
      {tip.rows.map((r, i) => (
        <div key={i}>{r}</div>
      ))}
    </div>
  );
}
