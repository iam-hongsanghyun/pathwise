import { useEffect, useMemo, useState } from "react";

import {
  listValueChains,
  loadValueChain,
  runValueChain,
  type ValueChainSpec,
  type VcIndexEntry,
  type VcRunResult,
} from "../lib/api/valuechain";

/** Value Chain view (L0) — the coupled-stage altitude.
 *
 *  Lists the value chains the backend serves, shows the selected chain's stages
 *  and coupling links (the DAG), runs the cascade, and overlays the per-stage
 *  results plus the trajectories that flowed between stages. Editing the DAG and
 *  drilling into a stage (company → process → facility) come in later slices.
 */
export function ValueChainView() {
  const [index, setIndex] = useState<VcIndexEntry[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [spec, setSpec] = useState<ValueChainSpec | null>(null);
  const [result, setResult] = useState<VcRunResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listValueChains()
      .then((entries) => {
        setIndex(entries);
        if (entries.length && !selected) setSelected(entries[0].id);
      })
      .catch(() => setIndex([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) return;
    setResult(null);
    setError(null);
    loadValueChain(selected).then(setSpec).catch(() => setSpec(null));
  }, [selected]);

  const run = async () => {
    if (!selected) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await runValueChain(selected));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  // Stage order as authored; links grouped by source for the arrow list.
  const stageLabel = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of spec?.stages ?? []) m.set(s.id, s.label || s.id);
    return m;
  }, [spec]);

  return (
    <div className="vc-view" style={{ display: "flex", height: "100%", minHeight: 0 }}>
      <aside className="vc-list" style={{ width: 220, borderRight: "1px solid var(--border)", overflow: "auto" }}>
        <div className="rail-head-row">
          <span className="rail-head">Value chains</span>
        </div>
        {index.length === 0 && <p className="muted" style={{ padding: 8 }}>no value chains</p>}
        {index.map((e) => (
          <button
            key={e.id}
            className={`rail-item${selected === e.id ? " is-active" : ""}`}
            title={e.description}
            onClick={() => setSelected(e.id)}
          >
            {e.label}
          </button>
        ))}
      </aside>

      <main style={{ flex: 1, minWidth: 0, overflow: "auto", padding: 16 }}>
        {!spec && <p className="muted">Select a value chain.</p>}
        {spec && (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
              <h2 style={{ margin: 0 }}>{spec.label || spec.id}</h2>
              <button className="primary" onClick={run} disabled={running}>
                {running ? "Running…" : "Run value chain"}
              </button>
              {result && (
                <span className="rail-count">
                  {result.status}
                  {result.iterations ? ` · ${result.iterations} iterations` : ""}
                </span>
              )}
            </div>
            {error && <p className="error" style={{ color: "var(--danger, #c00)" }}>{error}</p>}

            {/* Stages (upstream → downstream, left to right). */}
            <div style={{ display: "flex", gap: 8, alignItems: "stretch", flexWrap: "wrap", marginBottom: 16 }}>
              {spec.stages.map((s, i) => {
                const r = result?.stages[s.id];
                return (
                  <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div
                      className="vc-stage"
                      style={{
                        border: "1px solid var(--border)",
                        borderRadius: 6,
                        padding: "8px 12px",
                        minWidth: 140,
                        background: "var(--panel, #fff)",
                      }}
                    >
                      <div style={{ fontWeight: 600 }}>{s.label || s.id}</div>
                      <div className="muted" style={{ fontSize: "0.75rem" }}>
                        {[s.sector, s.region].filter(Boolean).join(" · ")}
                      </div>
                      {r && (
                        <div style={{ fontSize: "0.75rem", marginTop: 4 }}>
                          {r.status}
                          {r.objective != null && ` · ${Math.round(r.objective).toLocaleString()}`}
                        </div>
                      )}
                    </div>
                    {i < spec.stages.length - 1 && <span aria-hidden>→</span>}
                  </div>
                );
              })}
            </div>

            {/* Coupling links. */}
            <h3 style={{ marginBottom: 4 }}>Couplings</h3>
            <table className="data-table" style={{ width: "100%", maxWidth: 720 }}>
              <thead>
                <tr>
                  <th>from</th>
                  <th>to</th>
                  <th>commodity</th>
                  <th>signal</th>
                  <th>lag (yr)</th>
                </tr>
              </thead>
              <tbody>
                {spec.links.map((l, i) => (
                  <tr key={i} className={l.alternative_of ? "row-muted" : undefined}>
                    <td>{stageLabel.get(l.from_stage) ?? l.from_stage}</td>
                    <td>{stageLabel.get(l.to_stage) ?? l.to_stage}</td>
                    <td>{l.commodity}</td>
                    <td>
                      {(l.signals ?? ["price"]).join(", ")}
                      {l.feedback ? " + feedback" : ""}
                      {l.alternative_of ? " (alt)" : ""}
                    </td>
                    <td>{l.lag_years ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Trajectories that flowed between stages after a run. */}
            {result && result.couplings.length > 0 && (
              <>
                <h3 style={{ marginTop: 16, marginBottom: 4 }}>Flowed signals</h3>
                <table className="data-table" style={{ width: "100%", maxWidth: 720 }}>
                  <thead>
                    <tr>
                      <th>from → to</th>
                      <th>commodity</th>
                      <th>signal</th>
                      <th>by year</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.couplings.map((c, i) => (
                      <tr key={i}>
                        <td>
                          {(stageLabel.get(c.from_stage) ?? c.from_stage)} →{" "}
                          {stageLabel.get(c.to_stage) ?? c.to_stage}
                        </td>
                        <td>{c.commodity}</td>
                        <td>
                          {c.signal}
                          {c.impact ? ` (${c.impact})` : ""}
                        </td>
                        <td>
                          {c.by_year
                            .map((p) => `${p.year}: ${Math.round(p.value * 100) / 100}`)
                            .join("  ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}
