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
  const outputs = io.filter((r) => s(r.role) === "output").map((r) => s(r.target));
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
        <div><span className="muted">technology</span><br />{tech || "—"}</div>
        <div>
          <span className="muted">capacity</span><br />
          <input type="number" defaultValue={Number(machine.capacity) || 0} style={{ ...inp, width: 110 }} onBlur={(e) => onCapacity(Number(e.target.value) || 0)} />
        </div>
      </div>
      <p className="muted" style={{ fontSize: "0.75rem" }}>
        Core substance (the recipe, measures) is edited in the Component tab. Here you wire how its
        streams are satisfied.
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
      <h3 style={{ fontSize: "0.85rem", margin: "12px 0 6px" }}>Outputs</h3>
      <div className="muted" style={{ fontSize: "0.8rem" }}>{outputs.join(", ") || "—"}</div>
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
