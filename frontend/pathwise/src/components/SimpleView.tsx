import type { Selection, Workbook } from "../types";

interface Props {
  workbook: Workbook;
  onSelect: (s: Selection) => void;
}

const s = (v: unknown) => (v == null ? "" : String(v));

/** A simple, structured alternative to the React-Flow canvas: a 3-column flow —
 *  inputs (energy streams / material commodities) → facilities (each with its
 *  candidate technologies) → outputs (products / by-products / impacts). Every
 *  section is size-adjustable (drag the bottom-right corner); items are
 *  clickable to edit. Links are implied by the left→right column order. */
export function SimpleView({ workbook, onSelect }: Props) {
  const commodities = workbook.commodities ?? [];
  const byKind = (kinds: string[]) =>
    commodities.filter((r) => kinds.includes(s(r.kind) || "material")).map((r) => s(r.commodity_id));
  const energy = byKind(["energy"]);
  const materials = byKind(["material", "indirect"]);
  const products = byKind(["product"]);
  const byproducts = byKind(["byproduct"]);
  const impacts = (workbook.impacts ?? []).map((r) => s(r.impact_id));

  // Candidate technologies per facility: baseline + one-step transition targets.
  const targets = new Map<string, string[]>();
  for (const t of workbook.transitions ?? []) {
    const from = s(t.from_technology);
    (targets.get(from) ?? targets.set(from, []).get(from)!).push(s(t.to_technology));
  }
  // Inputs / outputs of a technology (from the io table) → used to order
  // facilities upstream→downstream (a producer sits above its consumer).
  const ioOf = (tech: string, role: "input" | "output") =>
    (workbook.io ?? [])
      .filter((r) => s(r.technology_id) === tech && (s(r.role) || "input") === role)
      .map((r) => s(r.target));

  const facilities = (workbook.processes ?? []).map((p) => {
    const base = s(p.baseline_technology);
    return {
      id: s(p.process_id),
      company: s(p.company),
      techs: [base, ...(targets.get(base) ?? [])],
      inputs: ioOf(base, "input"),
      outputs: ioOf(base, "output"),
    };
  });

  // Order by flow depth: a facility that consumes another's product comes lower.
  const producers = new Map<string, Set<number>>(); // commodity → facility indices
  facilities.forEach((f, i) =>
    f.outputs.forEach((c) => producers.set(c, (producers.get(c) ?? new Set()).add(i))),
  );
  const depthCache = new Map<number, number>();
  const depth = (i: number, seen: Set<number> = new Set()): number => {
    if (depthCache.has(i)) return depthCache.get(i)!;
    if (seen.has(i)) return 0; // cycle guard
    seen.add(i);
    let d = 0;
    for (const c of facilities[i].inputs)
      for (const j of producers.get(c) ?? [])
        if (j !== i) d = Math.max(d, depth(j, seen) + 1);
    depthCache.set(i, d);
    return d;
  };
  const ordered = facilities.map((f, i) => ({ ...f, depth: depth(i) }));
  // One window per flow stage (depth): upstream stages on top, downstream below
  // (e.g. steel: iron-making → steel-making). Label by what the stage produces.
  const stages = [...new Set(ordered.map((f) => f.depth))]
    .sort((a, b) => a - b)
    .map((d) => {
      const facs = ordered.filter((f) => f.depth === d);
      const outs = [...new Set(facs.flatMap((f) => f.outputs))].filter(Boolean);
      return { depth: d, facs, outs };
    });

  const pill = (sheet: string, idCol: string, id: string, cls = "") =>
    id ? (
      <button key={id} className={`sv-pill ${cls}`} onClick={() => onSelect({ sheet, idCol, id })}>
        {id}
      </button>
    ) : null;

  const Section = ({
    title,
    children,
    full,
    stage,
  }: {
    title: string;
    children: React.ReactNode;
    full?: boolean;
    stage?: boolean;
  }) => (
    <div className={`sv-section${full ? " sv-section--full" : ""}${stage ? " sv-section--stage" : ""}`}>
      <div className="sv-head">{title}</div>
      <div className="sv-body">{children}</div>
    </div>
  );

  return (
    <div className="simple-view">
      {/* Column 1 — inputs: energy streams (top), material commodities (bottom) */}
      <div className="sv-col">
        <Section title="Streams (energy)">
          {energy.map((c) => pill("commodities", "commodity_id", c, "energy"))}
        </Section>
        <Section title="Commodities (material)">
          {materials.map((c) => pill("commodities", "commodity_id", c, "material"))}
        </Section>
      </div>

      {/* Column 2 — facilities, one window per flow stage (upstream → downstream) */}
      <div className="sv-col">
        {stages.map((sgroup) => (
          <Section
            key={sgroup.depth}
            title={sgroup.outs.length ? `Facilities → ${sgroup.outs.join(" / ")}` : "Facilities"}
            full={stages.length === 1}
            stage={stages.length > 1}
          >
            {sgroup.facs.map((f) => (
              <div key={f.id} className="sv-facility">
                <button className="sv-pill facility" onClick={() => onSelect({ sheet: "processes", idCol: "process_id", id: f.id })}>
                  {f.id}
                </button>
                {f.techs.filter(Boolean).map((t) => pill("technologies", "technology_id", t, "tech"))}
              </div>
            ))}
          </Section>
        ))}
      </div>

      {/* Column 3 — outputs: products / by-products / impacts */}
      <div className="sv-col">
        <Section title="Products">
          {products.map((c) => pill("commodities", "commodity_id", c, "product"))}
        </Section>
        <Section title="By-products">
          {byproducts.map((c) => pill("commodities", "commodity_id", c, "byproduct"))}
        </Section>
        <Section title="Impacts">
          {impacts.map((c) => pill("impacts", "impact_id", c, "impact"))}
        </Section>
      </div>
    </div>
  );
}
