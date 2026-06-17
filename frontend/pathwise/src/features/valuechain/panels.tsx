// Side panels for the Value-Chain tab: machine inspector (required streams +
// how each is satisfied), ports/purchasing, demand targets, and the per-level
// cascade result summary. Presentational; the host mutates the workbook.

import { useMemo } from "react";
import { SearchableSelect } from "../controls/SearchableSelect";
import { SearchSelect } from "../controls/SearchSelect";
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
}: {
  wb: Workbook;
  machineId: string;
  onCapacity: (v: number) => void;
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

  const yFrom = techRow?.introduction_year, yTo = techRow?.phase_out_year;
  const avail = yFrom == null && yTo == null ? "always" : `${yFrom ?? "—"} → ${yTo ?? "—"}`;
  const th = { textAlign: "left", color: "var(--muted)", fontWeight: 500 } as React.CSSProperties;

  return (
    <div style={{ padding: "16px 20px", overflow: "auto" }}>
      <div className="eyebrow">machine · technology</div>
      <h2 style={{ margin: "4px 0 10px" }}>{machineId.split("/").pop()}</h2>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 12, fontSize: "0.82rem" }}>
        <div><span className="muted">technology</span><br />{tech || "—"}</div>
        <div>
          <span className="muted">capacity</span><br />
          <input type="number" defaultValue={Number(machine.capacity) || 0} style={{ ...inp, width: 100 }} onBlur={(e) => onCapacity(Number(e.target.value) || 0)} />
        </div>
        <div><span className="muted">available</span><br />{avail}</div>
      </div>

      <h3 style={{ fontSize: "0.85rem", margin: "10px 0 4px" }}>Inputs <span className="muted" style={{ fontWeight: 400 }}>(consumed)</span></h3>
      <table className="grid" style={{ fontSize: "0.78rem", width: "100%" }}>
        <thead><tr><th style={th}>stream</th><th style={th}>per unit</th><th style={th}>from</th></tr></thead>
        <tbody>
          {inputs.map((r) => {
            const c = s(r.target); const f = inFrom(c);
            return <tr key={c}><td>{c}</td><td>{s(r.coefficient)}</td><td style={{ color: f.ok ? "var(--text)" : "var(--danger)" }}>{f.text}</td></tr>;
          })}
          {inputs.length === 0 && <tr><td colSpan={3} className="muted">no inputs</td></tr>}
        </tbody>
      </table>

      <h3 style={{ fontSize: "0.85rem", margin: "12px 0 4px" }}>Outputs <span className="muted" style={{ fontWeight: 400 }}>(produced)</span></h3>
      <table className="grid" style={{ fontSize: "0.78rem", width: "100%" }}>
        <thead><tr><th style={th}>stream</th><th style={th}>per unit</th><th style={th}>to</th></tr></thead>
        <tbody>
          {outputs.map((r) => {
            const c = s(r.target);
            return <tr key={c}><td>{c}{r.is_product ? " ★" : ""}</td><td>{s(r.coefficient)}</td><td>{outTo(c, !!r.is_product)}</td></tr>;
          })}
          {outputs.length === 0 && <tr><td colSpan={3} className="muted">no outputs</td></tr>}
        </tbody>
      </table>

      {impacts.length > 0 && (
        <>
          <h3 style={{ fontSize: "0.85rem", margin: "12px 0 4px" }}>Impacts</h3>
          <div className="muted" style={{ fontSize: "0.78rem" }}>
            {impacts.map((r) => `${s(r.target)} ${s(r.coefficient)}`).join(" · ")}
          </div>
        </>
      )}
      <h3 style={{ fontSize: "0.85rem", margin: "12px 0 4px" }}>
        MACC <span className="muted" style={{ fontWeight: 400 }}>(measures — abate without switching technology)</span>
      </h3>
      <table className="grid" style={{ fontSize: "0.78rem", width: "100%" }}>
        <thead><tr><th style={th}>measure</th><th style={th}>type</th><th style={th}>applies to</th></tr></thead>
        <tbody>
          {[...appliedMeasures.entries()].map(([mid, scope]) => (
            <tr key={mid}>
              <td>{mid.split(" @ ")[0]}</td>
              <td className="muted">{measureType.get(mid) || "—"}</td>
              <td>{scope}</td>
            </tr>
          ))}
          {appliedMeasures.size === 0 && <tr><td colSpan={3} className="muted">no measures</td></tr>}
        </tbody>
      </table>

      <p className="muted" style={{ fontSize: "0.72rem", marginTop: 12 }}>
        Recipe &amp; measures are edited in the Component tab; ★ = a final product (can meet demand).
        A technology- or stream-scoped MACC is copied to every matching facility but
        each adopts it independently (isolated); transitions (technology switches) are
        shown separately under <em>Alternatives</em>.
      </p>
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
  const taken = new Set([baseline, ...alternatives]);
  const seen = new Set<string>();
  const fromTech = new Map<string, AvailableTechnology>();
  const opts: { value: string; label: string }[] = [];
  for (const a of available) {
    if (taken.has(a.technology) || seen.has(a.technology)) continue;
    seen.add(a.technology);
    fromTech.set(a.technology, a);
    opts.push({ value: a.technology, label: `${a.technology} · ${a.library}` });
  }
  return (
    <div className="rail-section">
      <div className="rail-head">Alternatives (optimiser may switch to)</div>
      {alternatives.length === 0 && (
        <div className="rail-empty" style={{ fontSize: "0.78rem" }}>
          none — the optimiser only runs {baseline || "the baseline"}.
        </div>
      )}
      {alternatives.map((a) => (
        <div key={a} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: "0.82rem", padding: "2px 0" }}>
          <span style={{ flex: 1 }}>{a}</span>
          <button className="ghost" title="remove alternative" onClick={() => onRemove(a)}>✕</button>
        </div>
      ))}
      <div style={{ marginTop: 6 }}>
        <SearchSelect
          value=""
          placeholder="add a technology…"
          options={opts}
          onChange={(v) => {
            const a = fromTech.get(v);
            if (a) onAdd(a.technology, a.library, a.scope);
          }}
        />
      </div>
    </div>
  );
}

// ── Ports / purchasing (markets scoped to a node) ─────────────────────────────
export function PortsPanel({
  wb,
  nodeId,
  commodities,
  onAdd,
  onRemove,
}: {
  wb: Workbook;
  nodeId: string;
  commodities: string[];
  onAdd: (commodity: string, kind: "buy" | "sell") => void;
  onRemove: (rowIndex: number) => void;
}) {
  const rows = (wb.markets ?? [])
    .map((r, idx) => ({ idx, r }))
    .filter(({ r }) => s(r.company) === nodeId);
  return (
    <div className="rail-section">
      <div className="rail-head">Purchasing (this node)</div>
      {rows.map(({ idx, r }) => (
        <div key={idx} style={{ display: "flex", gap: 4, padding: "2px 8px", alignItems: "center", fontSize: "0.74rem" }}>
          <span style={{ flex: 1 }}>
            {s(r.price) !== "" ? "buy" : "sell"} <b>{s(r.target)}</b>{" "}
            <span className="muted">@ {s(r.price) || s(r.sell_price) || "—"}</span>
          </span>
          <button className="ghost" onClick={() => onRemove(idx)}>✕</button>
        </div>
      ))}
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

/** Right-rail editor for a source stream (a raw material bought externally):
 *  purchase price, annual purchase cap, availability window. Writes the
 *  `commodities` ("Streams") sheet row. */
export function SourceStreamInspector({
  wb,
  commodityId,
  consumerLabels,
  onChange,
}: {
  wb: Workbook;
  commodityId: string;
  consumerLabels: string[];
  onChange: (wb: Workbook) => void;
}) {
  const rows = wb.commodities ?? [];
  const idx = rows.findIndex((r) => String(r.commodity_id) === commodityId);
  const row: Record<string, Cell> = idx >= 0 ? rows[idx] : { commodity_id: commodityId };
  const set = (patch: Record<string, Cell>) => {
    const next =
      idx >= 0 ? rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)) : [...rows, { ...row, ...patch }];
    onChange({ ...wb, commodities: next });
  };
  const numVal = (k: string) => {
    const v = row[k];
    return v == null || v === "" ? "" : String(v);
  };
  const onNum = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    set({ [k]: e.target.value === "" ? null : Number(e.target.value) });
  const fld: React.CSSProperties = {
    width: "100%",
    padding: "4px 6px",
    border: "1px solid var(--border-strong)",
    borderRadius: 4,
    font: "inherit",
  };
  const lbl: React.CSSProperties = { display: "block", marginBottom: 10, fontSize: "0.8rem" };
  return (
    <div style={{ padding: 16 }}>
      <div style={{ fontSize: "0.7rem", color: "var(--warn-text)", letterSpacing: "0.04em" }}>SOURCE STREAM</div>
      <h2 style={{ margin: "2px 0 4px" }}>{commodityId}</h2>
      <p className="muted" style={{ fontSize: "0.76rem", marginTop: 0 }}>
        A raw material consumed by the chain but produced by none — bought externally.
      </p>
      <label style={lbl}>
        Purchase price (/unit)
        <input style={fld} type="number" value={numVal("price")} onChange={onNum("price")} />
      </label>
      <label style={lbl}>
        Max purchase (/yr) <span className="muted">— blank = unlimited</span>
        <input style={fld} type="number" value={numVal("max_purchase")} onChange={onNum("max_purchase")} placeholder="∞" />
      </label>
      <label style={lbl}>
        Available from (yr)
        <input style={fld} type="number" value={numVal("available_from")} onChange={onNum("available_from")} placeholder="any" />
      </label>
      <label style={lbl}>
        Available until (yr)
        <input style={fld} type="number" value={numVal("available_to")} onChange={onNum("available_to")} placeholder="any" />
      </label>
      <div style={{ marginTop: 12, fontSize: "0.78rem" }}>
        <b>Feeds {consumerLabels.length} facilit{consumerLabels.length === 1 ? "y" : "ies"}</b>
        {consumerLabels.length > 0 && (
          <div className="muted" style={{ marginTop: 4 }}>{consumerLabels.slice(0, 12).join(", ")}</div>
        )}
      </div>
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
