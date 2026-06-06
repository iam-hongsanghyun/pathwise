import { useState } from "react";
import type { Selection, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  onSelect: (s: Selection) => void;
}

const s = (v: unknown) => (v == null ? "" : String(v));
const uniq = (a: string[]) => [...new Set(a.filter(Boolean))];

/** Process-route flow chart (horizontal): stages left→right (e.g. iron-making →
 *  steel-making → product), connected by the intermediate commodity. Each stage
 *  shows its technologies — baseline ● (current) and alternatives ○ (can switch
 *  to). Toggle between an aggregated stage box and per-facility boxes. */
export function FlowView({ workbook, onSelect }: Props) {
  const [perFacility, setPerFacility] = useState(false);

  const io = workbook.io ?? [];
  const ioOf = (tech: string, role: "input" | "output") =>
    io.filter((r) => s(r.technology_id) === tech && (s(r.role) || "input") === role).map((r) => s(r.target));
  const baseOf = (p: Record<string, unknown>) => s(p.baseline_technology);

  const targets = new Map<string, string[]>();
  for (const t of workbook.transitions ?? [])
    targets.set(s(t.from_technology), [...(targets.get(s(t.from_technology)) ?? []), s(t.to_technology)]);
  const altsOf = (base: string) => uniq(targets.get(base) ?? []).filter((t) => t !== base);

  const procs = (workbook.processes ?? []).map((p) => ({
    id: s(p.process_id),
    base: baseOf(p),
    inputs: ioOf(baseOf(p), "input"),
    outputs: ioOf(baseOf(p), "output"),
  }));

  // Flow depth: a facility consuming another's product is downstream.
  const producers = new Map<string, Set<number>>();
  procs.forEach((p, i) => p.outputs.forEach((c) => producers.set(c, (producers.get(c) ?? new Set()).add(i))));
  const cache = new Map<number, number>();
  const depth = (i: number, seen = new Set<number>()): number => {
    if (cache.has(i)) return cache.get(i)!;
    if (seen.has(i)) return 0;
    seen.add(i);
    let d = 0;
    for (const c of procs[i].inputs) for (const j of producers.get(c) ?? []) if (j !== i) d = Math.max(d, depth(j, seen) + 1);
    cache.set(i, d);
    return d;
  };

  const levels = uniq(procs.map((_, i) => String(depth(i)))).map(Number).sort((a, b) => a - b);
  const producedAnywhere = new Set(procs.flatMap((p) => p.outputs));
  const stages = levels.map((d) => {
    const facs = procs.filter((_, i) => depth(i) === d);
    const baseTechs = uniq(facs.map((f) => f.base));
    const alts = uniq(baseTechs.flatMap(altsOf));
    const inputs = uniq(facs.flatMap((f) => f.inputs));
    const outputs = uniq(facs.flatMap((f) => f.outputs));
    return {
      d,
      facs,
      baseTechs,
      alts,
      feeds: inputs.filter((c) => !producedAnywhere.has(c)), // external (raw) inputs only
      outputs,
    };
  });

  const products = new Set(
    (workbook.commodities ?? []).filter((r) => s(r.kind) === "product").map((r) => s(r.commodity_id)),
  );

  const tech = (t: string, base: boolean) => (
    <button
      key={t}
      className={`flow-tech ${base ? "base" : "alt"}`}
      onClick={() => onSelect({ sheet: "technologies", idCol: "technology_id", id: t })}
      title={base ? `${t} — current (baseline)` : `${t} — alternative (can switch to)`}
    >
      {base ? "● " : "○ "}
      {t}
    </button>
  );

  return (
    <div className="flow-view">
      <div className="flow-toolbar">
        <span className="view-toggle">
          <button className={`tab${perFacility ? "" : " active"}`} onClick={() => setPerFacility(false)}>
            Aggregated by stage
          </button>
          <button className={`tab${perFacility ? " active" : ""}`} onClick={() => setPerFacility(true)}>
            Per facility
          </button>
        </span>
        <span className="muted"> ● current technology · ○ alternative (the optimiser may switch to it)</span>
      </div>
      <div className="flow-stages">
        {stages.map((st, k) => (
          <div className="flow-row" key={st.d}>
            <div className="flow-stage">
              <div className="flow-stage-head">
                Stage {st.d + 1}
                {st.outputs.length ? ` → ${st.outputs.join(" / ")}` : ""}
              </div>
              {st.feeds.length > 0 && (
                <div className="flow-feeds">
                  {st.feeds.map((c) => (
                    <button
                      key={c}
                      className="flow-feed"
                      onClick={() => onSelect({ sheet: "commodities", idCol: "commodity_id", id: c })}
                    >
                      {c}
                    </button>
                  ))}
                </div>
              )}
              {perFacility ? (
                st.facs.map((f) => (
                  <div key={f.id} className="flow-fac">
                    <button
                      className="flow-fac-name"
                      onClick={() => onSelect({ sheet: "processes", idCol: "process_id", id: f.id })}
                    >
                      {f.id}
                    </button>
                    <div className="flow-techs">
                      {tech(f.base, true)}
                      {altsOf(f.base).map((t) => tech(t, false))}
                    </div>
                  </div>
                ))
              ) : (
                <div className="flow-techs">
                  {st.baseTechs.map((t) => tech(t, true))}
                  {st.alts.map((t) => tech(t, false))}
                </div>
              )}
            </div>
            {k < stages.length - 1 && (
              <div className="flow-arrow" title="flows to the next stage">
                →
                <span className="flow-arrow-label">{st.outputs.join(", ")}</span>
              </div>
            )}
          </div>
        ))}
        {products.size > 0 && (
          <div className="flow-row">
            <div className="flow-arrow">→</div>
            <div className="flow-product">
              {[...products].map((p) => (
                <button
                  key={p}
                  className="flow-feed product"
                  onClick={() => onSelect({ sheet: "commodities", idCol: "commodity_id", id: p })}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
