// Read-only "what does this technology actually do" preview: deploy N units of
// throughput → what it consumes, produces, and emits. Built from the tech's IO
// rows via summarizeRecipe; shared by the Component and Value-chain builders.

import { useState } from "react";
import { summarizeRecipe, type IoLike, type RecipeLine } from "./recipe";

const fmt = (x: number): string => (Number.isInteger(x) ? String(x) : x.toFixed(2));

export function RecipePreview({
  ioRows,
  defaultN = 100,
  unitOf,
}: {
  ioRows: ReadonlyArray<IoLike>;
  defaultN?: number;
  /** Resolves a stream's canonical unit — shown when a row declares no unit. */
  unitOf?: (stream: string) => string | undefined;
}) {
  const [n, setN] = useState(defaultN);
  const r = summarizeRecipe(ioRows, n);
  if (r.inputs.length + r.outputs.length + r.impacts.length === 0) return null;

  const lane = (label: string, arr: RecipeLine[], sign: string) =>
    arr.length > 0 && (
      <div style={{ fontSize: "0.74rem", padding: "1px 0", textTransform: "none", letterSpacing: 0 }}>
        <span className="muted">{label}:</span>{" "}
        {arr
          .map((l) => {
            const u = l.unit ?? unitOf?.(l.stream);
            return `${sign}${fmt(l.total)} ${u ? `${u}-` : ""}${l.stream}${l.isProduct ? " ★" : ""}`;
          })
          .join(", ")}
      </div>
    );

  return (
    <div className="rail-section">
      <div className="rail-head" style={{ display: "flex", alignItems: "center", gap: 6 }}>
        Recipe preview · deploy
        <input
          type="number"
          min={0}
          value={n}
          onChange={(e) => setN(Math.max(0, Number(e.target.value) || 0))}
          style={{ width: 64, padding: "2px 5px", border: "1px solid var(--border-strong)", borderRadius: "var(--radius-button)", font: "inherit", fontSize: "0.72rem" }}
        />
        units →
      </div>
      {lane("consumes", r.inputs, "−")}
      {lane("produces", r.outputs, "+")}
      {lane("emits", r.impacts, "")}
    </div>
  );
}
