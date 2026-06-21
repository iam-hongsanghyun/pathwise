// Side panels for the Value-Chain tab: machine inspector (required streams +
// how each is satisfied), ports/purchasing, demand targets, and the per-level
// cascade result summary. Presentational; the host mutates the workbook.

import { useMemo, useState } from "react";
import { SearchableSelect } from "../controls/SearchableSelect";
import { SearchSelect } from "../controls/SearchSelect";
import { TemporalValue, type TemporalVal } from "../controls/TemporalValue";
import {
  commodityUnit,
  maxConsumptionCap,
  maxOutputCap,
  minConsumptionCap,
  minOutputCap,
  setMaxConsumptionCap,
  setMaxOutputCap,
  setMinConsumptionCap,
  setMinOutputCap,
  supplyCap,
} from "../../lib/caps";
import type { AvailableTechnology } from "../../lib/api/components";
import type { Cell, RunResult, Workbook } from "../../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const inp: React.CSSProperties = {
  padding: "3px 6px",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-button)",
  background: "var(--surface)",
  font: "inherit",
  fontSize: "0.78rem",
};

/** Ancestor chain of a node id (self first) from the nodes sheet. */
function chain(wb: Workbook, nodeId: string): string[] {
  const parent = new Map((wb.nodes ?? []).map((r) => [s(r.node_id), s(r.parent_id)]));
  const out: string[] = [];
  let cur: string | undefined = nodeId;
  const seen = new Set<string>();
  while (cur && !seen.has(cur)) {
    out.push(cur);
    seen.add(cur);
    cur = parent.get(cur) || undefined;
  }
  return out;
}

// ── Machine inspector ─────────────────────────────────────────────────────────
// A single technology shows its full recipe — every input / output stream with
// its per-unit coefficient AND who provides / consumes it (the connected group,
// a purchase, or final demand) — plus impacts and the years it is available. This
// is the detailed view; groups get the lighter Flow context instead.
export function MachineInspector({
  wb,
  machineId,
  onCapacity,
  onWorkbookChange,
  baseYear = 2025,
  periods,
}: {
  wb: Workbook;
  machineId: string;
  onCapacity: (v: number) => void;
  /** Persist a new workbook (per-stream min/max edits flow through this). */
  onWorkbookChange?: (wb: Workbook) => void;
  /** Horizon start — seeds the temporal editor. */
  baseYear?: number;
  /** The model's run periods (years) — the temporal fill materialises onto these. */
  periods?: number[];
}) {
  const machine = (wb.machines ?? []).find((m) => s(m.machine_id) === machineId);
  const tech = s(machine?.baseline_technology);
  const techRow = (wb.technologies ?? []).find((t) => s(t.technology_id) === tech);
  const io = (wb.io ?? []).filter((r) => s(r.technology_id) === tech);
  const inputs = io.filter((r) => s(r.role) === "input");
  const outputs = io.filter((r) => s(r.role) === "output");
  const impacts = io.filter((r) => s(r.role) === "impact");

  // Measures (MACC) reaching THIS facility — directly (facility/technology) or via
  // a linked MACC set. A technology- or stream-scoped link is COPIED to every
  // matching facility, but each facility adopts it independently (isolated), which
  // the scope label below makes explicit.
  const inputStreams = new Set(inputs.map((r) => s(r.target)));
  const linkScope = new Map<string, string>(); // macc id → why it reaches this facility
  for (const ln of wb.macc_links ?? []) {
    const g = s(ln.macc);
    if (s(ln.facility) === machineId) linkScope.set(g, "this facility");
    else if (tech && s(ln.technology) === tech) linkScope.set(g, `every ${tech} · adopted independently`);
    else if (s(ln.commodity) && inputStreams.has(s(ln.commodity)))
      linkScope.set(g, `stream ${s(ln.commodity)} · adopted independently`);
  }
  const appliedMeasures = new Map<string, string>(); // measure id → scope label
  for (const m of wb.measures ?? []) {
    const mid = s(m.measure_id);
    if (s(m.facility) === machineId) appliedMeasures.set(mid, "this facility");
    else if (tech && s(m.technology) === tech) appliedMeasures.set(mid, `every ${tech} · adopted independently`);
  }
  for (const mm of wb.maccs ?? []) {
    const scope = linkScope.get(s(mm.macc));
    if (scope && !appliedMeasures.has(s(mm.measure_id))) appliedMeasures.set(s(mm.measure_id), scope);
  }
  const measureType = new Map((wb.measures ?? []).map((m) => [s(m.measure_id), s(m.type)]));
  const measureTarget = new Map((wb.measures ?? []).map((m) => [s(m.measure_id), s(m.target)]));
  const measureLabel = new Map((wb.measures ?? []).map((m) => [s(m.measure_id), s(m.label)]));
  // A measure id may be instance-scoped ("node/path · name") — show just the name.
  const measureName = (mid: string): string =>
    measureLabel.get(mid) || (mid.includes("·") ? mid.split("·").pop()!.trim() : mid.split("/").pop() || mid);
  const scope = useMemo(() => new Set(chain(wb, machineId)), [wb, machineId]);
  const labelOf = useMemo(
    () => new Map((wb.nodes ?? []).map((r) => [s(r.node_id), s(r.label) || s(r.node_id)])),
    [wb],
  );
  const lab = (id: string): string => labelOf.get(id) || id.split("/").pop() || id;

  // Connected counterpart group(s) for a stream: who sends it in / takes it out
  // (a connection wired at this node or any ancestor).
  const partners = (c: string, dir: "in" | "out"): string[] => {
    const near = dir === "in" ? "to_node" : "from_node";
    const far = dir === "in" ? "from_node" : "to_node";
    const g = (wb.connections ?? [])
      .filter((x) => s(x.commodity_id) === c && scope.has(s(x[near])) && !scope.has(s(x[far])))
      .map((x) => lab(s(x[far])));
    return [...new Set(g)];
  };
  const inFrom = (c: string): { text: string; ok: boolean } => {
    const src = partners(c, "in");
    if (src.length) return { text: `← ${src.join(", ")}`, ok: true };
    const buy = (wb.markets ?? []).find((x) => s(x.target) === c && s(x.price) !== "" && scope.has(s(x.company)));
    if (buy) return { text: `purchased · ${lab(s(buy.company))}`, ok: true };
    const commodity = (wb.commodities ?? []).find((x) => s(x.commodity_id) === c);
    if (commodity && (commodity.purchasable === true || s(commodity.price) !== ""))
      return { text: "purchased · market", ok: true };
    return { text: "unsatisfied", ok: false };
  };
  const outTo = (c: string, isProduct: boolean): string => {
    const snk = partners(c, "out");
    if (snk.length) return `→ ${snk.join(", ")}`;
    return isProduct ? "final product (demand)" : "—";
  };

  if (!machine) return <p className="muted" style={{ padding: 16 }}>Machine not found.</p>;

  // Units come from the streams (commodities sheet); throughput is measured in the
  // product output's unit. Each coefficient is "per unit of throughput".
  const unitOf = (cid: string): string =>
    s((wb.commodities ?? []).find((x) => s(x.commodity_id) === cid)?.unit) || "";
  const fmt = (v: unknown): string => {
    const n = Number(v);
    if (!Number.isFinite(n)) return s(v);
    return Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: 3 });
  };
  const product = outputs.find((r) => r.is_product) ?? outputs[0];
  const thru = unitOf(s(product?.target)) || "unit";

  // CO2 intensity per unit output: direct (tech impact rows) + indirect (purchased
  // inputs' carbon factors, when the model carries commodity_impacts). Omitted when
  // no CO2 impact is wired.
  const co2 = (wb.impacts ?? []).find((i) => /co2/i.test(s(i.impact_id)));
  const co2Id = s(co2?.impact_id);
  let co2Intensity: number | null = null;
  if (co2Id) {
    let v = 0;
    for (const r of impacts) if (s(r.target) === co2Id) v += Number(r.coefficient) || 0;
    for (const r of inputs) {
      const f = (wb.commodity_impacts ?? []).find(
        (x) => s(x.commodity_id) === s(r.target) && s(x.impact_id) === co2Id,
      );
      if (f) v += (Number(r.coefficient) || 0) * (Number(f.factor) || 0);
    }
    co2Intensity = v;
  }
  const otherImpacts = impacts.filter((r) => s(r.target) !== co2Id);

  const yFrom = techRow?.introduction_year, yTo = techRow?.phase_out_year;
  const avail = yFrom == null && yTo == null ? "always available" : `available ${yFrom ?? "—"} → ${yTo ?? "—"}`;

  const wireRow = (r: Record<string, Cell>, role: "IN" | "OUT") => {
    const c = s(r.target);
    const sub = role === "IN" ? inFrom(c) : { text: outTo(c, !!r.is_product), ok: true };
    const isOut = role === "OUT";
    const unit = commodityUnit(wb, c);
    // OUTPUT streams bound production (min/max_production); INPUT streams bound the
    // machine's intake (min/max_consumption): min = required offtake, max = max purchase.
    const minVal = isOut ? minOutputCap(wb, machineId, c) : minConsumptionCap(wb, machineId, c);
    const maxVal = isOut ? maxOutputCap(wb, machineId, c) : maxConsumptionCap(wb, machineId, c);
    const setMin = (v: TemporalVal | null) =>
      onWorkbookChange?.(isOut ? setMinOutputCap(wb, machineId, c, v) : setMinConsumptionCap(wb, machineId, c, v));
    const setMax = (v: TemporalVal | null) =>
      onWorkbookChange?.(isOut ? setMaxOutputCap(wb, machineId, c, v) : setMaxConsumptionCap(wb, machineId, c, v));
    return (
      <div className="mi-row" key={`${role}:${c}`}>
        <span className={`mi-badge ${isOut ? "mi-out" : ""}`}>{role}</span>
        <div className="mi-stream">
          <div className="mi-name">{c}{r.is_product ? " ★" : ""}</div>
          <div className="mi-sub" style={sub.ok === false ? { color: "var(--danger)" } : undefined}>{sub.text}</div>
          {onWorkbookChange && (
            <div className="mi-bounds">
              <span className="mi-bound-lbl">{isOut ? "min" : "min offtake"}</span>
              <TemporalValue value={minVal} onChange={setMin} unit={unit} baseYear={baseYear} periods={periods} placeholder={isOut ? "no floor" : "none"} label={`${c} · ${isOut ? "min output" : "required offtake"}`} />
              <span className="mi-bound-lbl">{isOut ? "max" : "max purchase"}</span>
              <TemporalValue value={maxVal} onChange={setMax} unit={unit} baseYear={baseYear} periods={periods} placeholder="no cap" label={`${c} · ${isOut ? "max output" : "max purchase"}`} />
            </div>
          )}
        </div>
        <div className="mi-val">{fmt(r.coefficient)} <span className="mi-unit">{unitOf(c)}</span></div>
      </div>
    );
  };

  return (
    <div className="mi" style={{ padding: "16px 20px", overflow: "auto" }}>
      <div className="eyebrow">machine</div>
      <h2 className="mi-title">{s(machine.label) || machineId.split("/").pop()}</h2>
      <div className="mi-chips">
        {tech && <span className="mi-chip">runs {tech}</span>}
        <span className="mi-avail">{avail}</span>
      </div>

      <div className="mi-section-head"><span>recipe — wiring</span><span className="muted">per {thru} output</span></div>
      <div>
        {inputs.map((r) => wireRow(r, "IN"))}
        {outputs.map((r) => wireRow(r, "OUT"))}
        {io.length === 0 && <div className="muted" style={{ padding: "8px 0", fontSize: "0.8rem" }}>no recipe</div>}
      </div>

      {/* Machine-level: capacity + CO₂ intensity. Per-stream min/max live on the
          recipe rows above (output → production bounds, input → intake bounds). */}
      <div className="mi-section-head"><span>capacity</span><span className="muted">the machine's own limit</span></div>
      <div className="mi-cards">
        <div className="mi-card">
          <div className="mi-card-label">capacity</div>
          <div className="mi-card-val">
            <input type="number" min={0} defaultValue={Number(machine.capacity) || 0} className="mi-cap-input" onBlur={(e) => onCapacity(Number(e.target.value) || 0)} />
            <span className="mi-unit">{thru}/yr</span>
          </div>
        </div>
        {co2Intensity != null && (
          <div className="mi-card">
            <div className="mi-card-label">CO₂ intensity</div>
            <div className="mi-card-val"><b>{fmt(co2Intensity)}</b> <span className="mi-unit">{s(co2?.unit)}/{thru}</span></div>
          </div>
        )}
      </div>

      <p className="muted mi-note">Recipe coefficients are edited in the Component tab. Per-stream min/max are limits on this machine's flows (min offtake = required purchase). ★ = a final product (can meet demand).</p>

      {otherImpacts.length > 0 && (
        <div className="mi-block">
          <div className="mi-section-head"><span>other impacts</span></div>
          <div className="muted" style={{ fontSize: "0.78rem" }}>
            {otherImpacts.map((r) => `${s(r.target)} ${fmt(r.coefficient)}`).join(" · ")}
          </div>
        </div>
      )}

      {appliedMeasures.size > 0 && (
        <div className="mi-block">
          <div className="mi-section-head"><span>measures (MACC)</span></div>
          {[...appliedMeasures.keys()].map((mid) => {
            const t = measureTarget.get(mid);
            const verb = measureType.get(mid) === "energy_efficiency" ? "saves" : "cuts";
            return (
              <div className="mi-measure" key={mid}>
                <span className="mi-measure-name">{measureName(mid)}</span>
                <span className="mi-sub">{t ? `${verb} ${t}` : measureType.get(mid) || ""}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Flow context: what feeds a node, and what it feeds ────────────────────────
// Reads the raw `connections` (which may be wired at any level — e.g. a
// country→country link), and shows every connection touching the selected node
// OR an ancestor of it, so even a lone machine displays its upstream/downstream.
// When one input commodity has MORE THAN ONE supplier, it lists them as N
// "sources" (distinct from the alternative-technologies feature).
export function FlowContext({ wb, nodeId }: { wb: Workbook; nodeId: string }) {
  const anc = useMemo(() => new Set(chain(wb, nodeId)), [wb, nodeId]);
  const labelOf = useMemo(
    () => new Map((wb.nodes ?? []).map((r) => [s(r.node_id), s(r.label) || s(r.node_id)])),
    [wb],
  );
  const lab = (id: string): string => labelOf.get(id) || id.split("/").pop() || id;

  // What this node's SUBTREE actually produces / consumes — so a country-level
  // connection is attributed to a node only for commodities it really handles
  // (the iron-ore mine produces iron_ore, not the hydrogen its sibling makes).
  const { produces, consumes } = useMemo(() => {
    const childrenOf = new Map<string, string[]>();
    for (const r of wb.nodes ?? []) {
      const p = s(r.parent_id);
      if (p) (childrenOf.get(p) ?? childrenOf.set(p, []).get(p)!).push(s(r.node_id));
    }
    const subtree = new Set<string>([nodeId]);
    const stack = [nodeId];
    while (stack.length) for (const ch of childrenOf.get(stack.pop()!) ?? []) if (!subtree.has(ch)) { subtree.add(ch); stack.push(ch); }
    const techOf = new Map((wb.machines ?? []).map((m) => [s(m.machine_id), s(m.baseline_technology)]));
    const techs = new Set([...subtree].map((id) => techOf.get(id)).filter(Boolean));
    const prod = new Set<string>(), cons = new Set<string>();
    for (const r of wb.io ?? []) {
      if (!techs.has(s(r.technology_id))) continue;
      const role = s(r.role), tgt = s(r.target);
      if (role === "output") prod.add(tgt);
      else if (role === "input") cons.add(tgt);
    }
    return { produces: prod, consumes: cons };
  }, [wb, nodeId]);

  const inByComm = new Map<string, Set<string>>(); // commodity → source nodes (before)
  const outByComm = new Map<string, Set<string>>(); // commodity → target nodes (next)
  for (const c of wb.connections ?? []) {
    const f = s(c.from_node), t = s(c.to_node), cm = s(c.commodity_id);
    if (!cm) continue;
    if (anc.has(t) && !anc.has(f) && consumes.has(cm)) (inByComm.get(cm) ?? inByComm.set(cm, new Set()).get(cm)!).add(f);
    if (anc.has(f) && !anc.has(t) && produces.has(cm)) (outByComm.get(cm) ?? outByComm.set(cm, new Set()).get(cm)!).add(t);
  }
  if (inByComm.size === 0 && outByComm.size === 0)
    return <div className="rail-empty" style={{ fontSize: "0.78rem" }}>Not wired to other nodes yet — right-click → Connect.</div>;

  const lane = (title: string, arrow: string, m: Map<string, Set<string>>) =>
    [...m.entries()].map(([cm, nodes]) => {
      const srcs = [...nodes];
      return (
        <div key={`${title}:${cm}`} style={{ fontSize: "0.78rem", padding: "2px 0" }}>
          <span className="muted">{arrow} {cm}:</span>{" "}
          {srcs.map((n) => lab(n)).join(", ")}
          {title === "in" && srcs.length > 1 && (
            <span style={{ color: "var(--brand)", fontWeight: 600 }}> · {srcs.length} sources</span>
          )}
        </div>
      );
    });

  return (
    <div className="rail-section">
      <div className="rail-head">Flow context</div>
      {inByComm.size > 0 && <div style={{ marginBottom: 4 }}><div className="muted" style={{ fontSize: "0.72rem" }}>feeds in (before)</div>{lane("in", "←", inByComm)}</div>}
      {outByComm.size > 0 && <div><div className="muted" style={{ fontSize: "0.72rem" }}>feeds out (next)</div>{lane("out", "→", outByComm)}</div>}
    </div>
  );
}

// ── Alternatives: technologies the optimiser may switch this machine to ───────
// Pure value-chain choice (not baked into the Component library). The list is the
// transitions out of the machine's baseline technology; the picker draws from the
// pool of all library technologies.
export function Alternatives({
  baseline,
  alternatives,
  available,
  onAdd,
  onRemove,
}: {
  baseline: string;
  alternatives: string[];
  available: AvailableTechnology[];
  onAdd: (technology: string, library: string, scope: "base" | "session") => void;
  onRemove: (technology: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const taken = new Set([baseline, ...alternatives]);
  const seen = new Set<string>();
  const fromTech = new Map<string, AvailableTechnology>();
  const libOf = new Map<string, string>();
  const opts: { value: string; label: string }[] = [];
  for (const a of available) {
    if (!libOf.has(a.technology)) libOf.set(a.technology, a.library);
    if (taken.has(a.technology) || seen.has(a.technology)) continue;
    seen.add(a.technology);
    fromTech.set(a.technology, a);
    opts.push({ value: a.technology, label: `${a.technology} · ${a.library}` });
  }
  const swap = (
    <svg className="mi-alt-icon" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 4 3 8l4 4" /><path d="M3 8h13" /><path d="m17 20 4-4-4-4" /><path d="M21 16H8" />
    </svg>
  );
  return (
    <div className="mi-section">
      <div className="mi-section-head">
        <span>alternatives</span>
        <button className="mi-add" onClick={() => setAdding((v) => !v)}>+ add…</button>
      </div>
      <p className="muted mi-note" style={{ marginTop: 0 }}>Technologies the optimiser may switch this machine to.</p>
      {alternatives.length === 0 && !adding && (
        <div className="rail-empty" style={{ fontSize: "0.78rem" }}>none — the optimiser only runs {baseline || "the baseline"}.</div>
      )}
      {alternatives.map((a) => (
        <div className="mi-alt" key={a}>
          {swap}
          <span className="mi-alt-name">{a}</span>
          <span className="mi-alt-lib">{libOf.get(a) || ""}</span>
          <button className="mi-alt-x" title="remove alternative" onClick={() => onRemove(a)}>✕</button>
        </div>
      ))}
      {adding && (
        <div style={{ marginTop: 8 }}>
          <SearchSelect
            value=""
            placeholder="add a technology…"
            options={opts}
            onChange={(v) => {
              const a = fromTech.get(v);
              if (a) { onAdd(a.technology, a.library, a.scope); setAdding(false); }
            }}
          />
        </div>
      )}
    </div>
  );
}

// ── Ports / purchasing (markets scoped to a node) ─────────────────────────────
export function PortsPanel({
  wb,
  nodeId,
  commodities,
  onAdd,
  onPrice,
  onRemove,
}: {
  wb: Workbook;
  nodeId: string;
  commodities: string[];
  onAdd: (commodity: string, kind: "buy" | "sell") => void;
  onPrice: (rowIndex: number, field: "price" | "sell_price", value: number) => void;
  onRemove: (rowIndex: number) => void;
}) {
  const rows = (wb.markets ?? [])
    .map((r, idx) => ({ idx, r }))
    .filter(({ r }) => s(r.company) === nodeId);
  return (
    <div className="rail-section">
      <div className="rail-head">Purchasing (this node)</div>
      {rows.map(({ idx, r }) => {
        // Classify by which price KEY is present (not its value), so clearing a
        // buy price to 0 doesn't silently reclassify the row as a sell.
        const isBuy = "price" in r;
        const field: "price" | "sell_price" = isBuy ? "price" : "sell_price";
        return (
          <div key={idx} style={{ display: "flex", gap: 4, padding: "2px 8px", alignItems: "center", fontSize: "0.74rem" }}>
            <span style={{ flex: 1 }}>
              {isBuy ? "buy" : "sell"} <b>{s(r.target)}</b>
            </span>
            <span className="muted">@</span>
            <input
              type="number"
              min={0}
              value={Number(r[field]) || 0}
              onChange={(e) => onPrice(idx, field, Number(e.target.value) || 0)}
              style={{ ...inp, width: 72 }}
              title={isBuy ? "purchase price per unit" : "sale price per unit"}
            />
            <button className="ghost" onClick={() => onRemove(idx)}>✕</button>
          </div>
        );
      })}
      <PortAdder commodities={commodities} onAdd={onAdd} />
    </div>
  );
}

function PortAdder({ commodities, onAdd }: { commodities: string[]; onAdd: (c: string, k: "buy" | "sell") => void }) {
  return (
    <div style={{ display: "flex", gap: 4, padding: "4px 8px", alignItems: "center" }}>
      <div style={{ flex: 1 }}>
        <SearchableSelect value="" options={commodities} onChange={(c) => c && onAdd(c, "buy")} placeholder="buy stream…" />
      </div>
      <div style={{ flex: 1 }}>
        <SearchableSelect value="" options={commodities} onChange={(c) => c && onAdd(c, "sell")} placeholder="sell stream…" />
      </div>
    </div>
  );
}

// ── Cascade (per-level) result summary ────────────────────────────────────────
export interface CascadeResult {
  status: string;
  // Each stage is a full run result — keep all of it (per-year technology,
  // throughput, transitions, flows) so the result can be drawn on the map.
  stages: Record<string, RunResult>;
  couplings: { from_stage: string; to_stage: string; commodity: string; signal: string }[];
  iterations: number;
}

// ── Per-year result overlay (drawn on the process map) ────────────────────────

/** What a single year's result looks like, resolved per node / edge id. */
export interface YearOverlay {
  /** Active technology of a machine that year (``undefined`` if it isn't running). */
  tech: (id: string) => string | undefined;
  /** If the machine switched technology that year, the technology it switched to. */
  transitionedTo: (id: string) => string | undefined;
  /** Throughput of a machine that year. */
  throughput: (id: string) => number | undefined;
  /** Flow along a ``from → to`` link for a commodity that year. */
  flow: (from: string, to: string, commodity: string) => number | undefined;
  /** External purchase of a commodity by a facility that year (a source stream). */
  buy: (id: string, commodity: string) => number | undefined;
}

function _resultsOf(r: RunResult | CascadeResult): RunResult[] {
  return "stages" in r ? Object.values(r.stages) : [r];
}

/** Index a run / cascade result by ``(node, year)`` so the map can read any year.

    Works for both a joint solve (one result) and a cascade (one per stage); the
    process ids in the result are the machine-node ids on the map. */
export function buildOverlay(r: RunResult | CascadeResult): {
  years: number[];
  at: (year: number) => YearOverlay;
} {
  const tech = new Map<string, Map<number, string>>();
  const tput = new Map<string, Map<number, number>>();
  const trans = new Map<string, Map<number, string>>();
  const flow = new Map<string, Map<number, number>>();
  const buy = new Map<string, Map<number, number>>();
  const years = new Set<number>();
  const set = (m: Map<string, Map<number, string>>, k: string, y: number, v: string) => {
    (m.get(k) ?? m.set(k, new Map()).get(k)!).set(y, v);
    years.add(y);
  };
  const add = (m: Map<string, Map<number, number>>, k: string, y: number, v: number) => {
    const inner = m.get(k) ?? m.set(k, new Map()).get(k)!;
    inner.set(y, (inner.get(y) ?? 0) + v);
    years.add(y);
  };
  for (const res of _resultsOf(r)) {
    const out = res?.outputs;
    if (!out) continue;
    for (const t of out.technology ?? []) set(tech, t.process, t.period, t.technology);
    for (const x of out.throughput ?? []) add(tput, x.process, x.period, x.value);
    for (const tr of out.transitions ?? []) set(trans, tr.process, tr.period, tr.to_technology);
    for (const f of out.flows ?? []) add(flow, `${f.from}|${f.to}|${f.commodity}`, f.period, f.value);
    for (const tr of out.trade ?? []) if (tr.kind === "buy") add(buy, `${tr.process}|${tr.commodity}`, tr.period, tr.value);
  }
  const at = (year: number): YearOverlay => ({
    tech: (id) => tech.get(id)?.get(year),
    transitionedTo: (id) => trans.get(id)?.get(year),
    throughput: (id) => tput.get(id)?.get(year),
    flow: (from, to, commodity) => flow.get(`${from}|${to}|${commodity}`)?.get(year),
    buy: (id, commodity) => buy.get(`${id}|${commodity}`)?.get(year),
  });
  return { years: [...years].sort((a, b) => a - b), at };
}

/** Right-rail READ-ONLY summary of a source stream (a raw material bought
 *  externally). Streams are components — defined and priced in the Component
 *  view (the "Streams" sheet); the value-chain map only shows their use here. */
export function SourceStreamInspector({
  wb,
  commodityId,
  consumerLabels,
  onSupplyCap,
  baseYear = 2025,
  periods,
}: {
  wb: Workbook;
  commodityId: string;
  consumerLabels: string[];
  /** Set / clear (null) this stream's annual supply cap — static or by-year. */
  onSupplyCap?: (v: TemporalVal | null) => void;
  baseYear?: number;
  periods?: number[];
}) {
  const row = (wb.commodities ?? []).find((r) => String(r.commodity_id) === commodityId) ?? {};
  const g = (k: string): string | null => {
    const v = (row as Record<string, Cell>)[k];
    return v == null || v === "" ? null : String(v);
  };
  const unit = g("unit") || "";
  const kv = (label: string, value: string, suffix?: string) => (
    <div className="mi-kv">
      <span>{label}</span>
      <span className="mi-val">{value}{suffix ? <span className="mi-unit"> {suffix}</span> : null}</span>
    </div>
  );
  return (
    <div className="mi" style={{ padding: "16px 20px" }}>
      <div className="eyebrow" style={{ color: "var(--warn-text)" }}>source stream</div>
      <h2 className="mi-title">{commodityId}</h2>
      <p className="muted mi-note" style={{ marginTop: 0 }}>
        A raw material consumed by the chain but produced by none — bought externally.
        {unit ? ` Measured in ${unit}.` : ""}
      </p>
      <div className="mi-section-head"><span>purchasing</span></div>
      {kv("purchase price", g("price") ?? "—", unit ? `/${unit}` : undefined)}
      {onSupplyCap ? (
        <div className="mi-kv">
          <span>max supply / yr</span>
          <span className="mi-val">
            <TemporalValue
              value={supplyCap(wb, commodityId)}
              onChange={onSupplyCap}
              unit={unit || undefined}
              baseYear={baseYear}
              periods={periods}
              placeholder="no cap"
              label={`${commodityId} · max supply`}
            />
          </span>
        </div>
      ) : (
        kv("max supply / yr", g("max_purchase") ?? "∞", unit || undefined)
      )}
      {kv("available from", g("available_from") ?? "any")}
      {kv("available until", g("available_to") ?? "any")}
      <p className="muted mi-note">
        The supply cap is a hard ceiling on this stream's annual supply. Price &amp;
        availability are edited in the <b>Component</b> view (its Streams sheet).
      </p>
      <div className="mi-section-head">
        <span>feeds {consumerLabels.length} facilit{consumerLabels.length === 1 ? "y" : "ies"}</span>
      </div>
      {consumerLabels.length > 0 && (
        <div className="muted" style={{ fontSize: "0.8rem" }}>{consumerLabels.slice(0, 12).join(", ")}</div>
      )}
    </div>
  );
}

/** A slider that scrubs through the result years (the "chain over time" control). */
export function ResultYearBar({
  years,
  year,
  onYear,
}: {
  years: number[];
  year: number;
  onYear: (y: number) => void;
}) {
  if (years.length === 0) return null;
  const idx = Math.max(0, years.indexOf(year));
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "5px 14px",
        borderBottom: "1px solid var(--border)",
        fontSize: "0.78rem",
        background: "var(--surface)",
      }}
    >
      <span className="muted">year</span>
      <button
        className="ghost"
        disabled={idx <= 0}
        onClick={() => onYear(years[idx - 1])}
        title="previous year"
      >
        ◂
      </button>
      <input
        type="range"
        min={0}
        max={years.length - 1}
        step={1}
        value={idx}
        onChange={(e) => onYear(years[Number(e.target.value)])}
        style={{ flex: 1, maxWidth: 320 }}
        aria-label="result year"
      />
      <button
        className="ghost"
        disabled={idx >= years.length - 1}
        onClick={() => onYear(years[idx + 1])}
        title="next year"
      >
        ▸
      </button>
      <b style={{ minWidth: 40, textAlign: "right" }}>{year}</b>
      <span className="muted">· active technology &amp; flows shown on the map</span>
    </div>
  );
}

export function CascadeSummary({ cascade, label }: { cascade: CascadeResult; label: (id: string) => string }) {
  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: "8px 14px", maxHeight: 220, overflow: "auto" }}>
      <b>Per-level result</b> <span className="muted">· {cascade.status} · {cascade.iterations} iteration(s)</span>
      <table className="grid" style={{ fontSize: "0.76rem", marginTop: 4 }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--muted)" }}><th>stage</th><th>status</th><th>objective</th></tr>
        </thead>
        <tbody>
          {Object.entries(cascade.stages).map(([id, r]) => (
            <tr key={id}>
              <td>{label(id)}</td>
              <td>{r.status ?? "—"}</td>
              <td>{r.objective != null ? Math.round(r.objective).toLocaleString() : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {cascade.couplings.length > 0 && (
        <div className="muted" style={{ marginTop: 4, fontSize: "0.74rem" }}>
          couplings: {cascade.couplings.map((c) => `${label(c.from_stage)}→${label(c.to_stage)} (${c.commodity}/${c.signal})`).join(", ")}
        </div>
      )}
    </div>
  );
}
