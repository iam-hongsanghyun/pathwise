// Side panels for the Value-Chain tab: machine inspector (required streams +
// how each is satisfied), ports/purchasing, demand targets, and the per-level
// cascade result summary. Presentational; the host mutates the workbook.

import { useMemo } from "react";
import { SearchableSelect } from "../controls/SearchableSelect";
import type { Workbook } from "../../types";

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
  const io = (wb.io ?? []).filter((r) => s(r.technology_id) === tech);
  const inputs = io.filter((r) => s(r.role) === "input").map((r) => s(r.target));
  const scope = useMemo(() => new Set(chain(wb, machineId)), [wb, machineId]);

  const satisfaction = (c: string): { how: string; ok: boolean } => {
    const byConn = (wb.connections ?? []).some(
      (x) => s(x.commodity_id) === c && scope.has(s(x.to_node)),
    );
    if (byConn) return { how: "incoming connection", ok: true };
    const buy = (wb.markets ?? []).find(
      (x) => s(x.target) === c && s(x.price) !== "" && scope.has(s(x.company)),
    );
    if (buy) return { how: `purchased (${s(buy.company)})`, ok: true };
    const commodity = (wb.commodities ?? []).find((x) => s(x.commodity_id) === c);
    if (commodity && (commodity.purchasable === true || s(commodity.price) !== ""))
      return { how: "purchasable from market", ok: true };
    return { how: "unsatisfied", ok: false };
  };

  if (!machine)
    return <p className="muted" style={{ padding: 16 }}>Machine not found.</p>;

  return (
    <div style={{ padding: "16px 20px", overflow: "auto" }}>
      <div className="eyebrow">machine</div>
      <h2 style={{ margin: "4px 0 12px" }}>{machineId.split("/").pop()}</h2>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 16, fontSize: "0.82rem" }}>
        <div>
          <span className="muted">technology</span><br />{tech || "—"}
          <div className="muted" style={{ fontSize: "0.7rem" }}>recipe &amp; measures → Component tab</div>
        </div>
        <div>
          <span className="muted">capacity</span><br />
          <input type="number" defaultValue={Number(machine.capacity) || 0} style={{ ...inp, width: 110 }} onBlur={(e) => onCapacity(Number(e.target.value) || 0)} />
        </div>
      </div>
      <p className="muted" style={{ fontSize: "0.75rem" }}>
        The value chain is about <b>wiring</b>: the recipe and measures are defined in the Component
        tab — here you check how each required input stream is satisfied (connection or purchase).
      </p>
      <h3 style={{ fontSize: "0.85rem", margin: "12px 0 6px" }}>Required input streams</h3>
      <table className="grid" style={{ fontSize: "0.78rem", width: "100%" }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--muted)" }}><th>stream</th><th>satisfied by</th></tr>
        </thead>
        <tbody>
          {inputs.map((c) => {
            const sat = satisfaction(c);
            return (
              <tr key={c}>
                <td>{c}</td>
                <td style={{ color: sat.ok ? "var(--text)" : "var(--danger)" }}>{sat.how}</td>
              </tr>
            );
          })}
          {inputs.length === 0 && <tr><td colSpan={2} className="muted">no inputs</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

// ── Flow context: what feeds a node, and what it feeds ────────────────────────
// Reads the raw `connections` (which may be wired at any level — e.g. a
// country→country link), and shows every connection touching the selected node
// OR an ancestor of it, so even a lone machine displays its upstream/downstream.
// When one input commodity has MORE THAN ONE source, those sources are the
// **alternatives** the optimiser chooses between.
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
            <span style={{ color: "var(--brand)", fontWeight: 600 }}> · {srcs.length} alternatives</span>
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
  stages: Record<string, { objective?: number | null; status?: string }>;
  couplings: { from_stage: string; to_stage: string; commodity: string; signal: string }[];
  iterations: number;
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
