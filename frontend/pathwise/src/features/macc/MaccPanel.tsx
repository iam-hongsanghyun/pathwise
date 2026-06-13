import { useMemo, useState } from "react";
import { MACC_LINK_KINDS, applyMacc, type MaccLinkKind } from "../../lib/graph";
import type { Row, Workbook } from "../../types";
import { SearchableSelect } from "../controls/SearchableSelect";
import { MaccChart, MaccMeasureTable, maccBars, type MaccBar } from "./MaccDesigner";

const s = (v: unknown) => (v == null ? "" : String(v));
type MaccTab = "description" | "table" | "chart";

const KIND_LABEL: Record<MaccLinkKind, string> = {
  facility: "facility",
  technology: "technology",
  commodity: "stream",
  storage: "store",
};

function allMaccNames(workbook: Workbook): string[] {
  return [
    ...new Set(
      [...(workbook.maccs ?? []), ...(workbook.macc_links ?? [])]
        .map((r) => s(r.macc))
        .filter(Boolean),
    ),
  ].sort();
}

function stats(data: MaccBar[]) {
  const usable = data.filter((b) => Number.isFinite(b.cost) && b.potential > 0);
  const potential = usable.reduce((sum, b) => sum + b.potential, 0);
  const weightedCost =
    potential > 0 ? usable.reduce((sum, b) => sum + b.cost * b.potential, 0) / potential : null;
  return {
    facilities: new Set(data.map((b) => b.machine)).size,
    potential,
    weightedCost,
  };
}

const fmt = (value: number | null, digits = 1) => (value == null ? "—" : value.toFixed(digits));

function SummaryMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="macc-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

/** The kind of target a macc_links row names (first filled column). */
const linkKind = (r: Row): MaccLinkKind | null =>
  MACC_LINK_KINDS.find((k) => s(r[k])) ?? null;

/** Right-rail panel for a selected MACC: where it is deployed. Lives beside
 *  the bottom dock (description/table/chart) the way other items keep their
 *  static values in the right rail. Writes the same macc_links rows as the
 *  component-side "MACC deployment" sections. */
export function MaccDeployRail({
  workbook,
  macc,
  onChange,
  onClose,
}: {
  workbook: Workbook;
  macc: string;
  onChange: (wb: Workbook) => void;
  onClose: () => void;
}) {
  const [deployKind, setDeployKind] = useState<MaccLinkKind>("facility");
  const links = (workbook.macc_links ?? [])
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => s(r.macc) === macc);
  const deployOptions: Record<MaccLinkKind, string[]> = {
    facility: (workbook.processes ?? []).map((r) => s(r.process_id)).filter(Boolean),
    technology: (workbook.technologies ?? []).map((r) => s(r.technology_id)).filter(Boolean),
    commodity: (workbook.commodities ?? []).map((r) => s(r.commodity_id)).filter(Boolean),
    storage: (workbook.storage ?? []).map((r) => s(r.storage_id)).filter(Boolean),
  };
  const dropLink = (idx: number) =>
    onChange({
      ...workbook,
      macc_links: (workbook.macc_links ?? []).filter((_, i) => i !== idx),
    });

  return (
    <div className="detail-panel">
      <div className="detail-head">
        <div>
          <strong>{macc}</strong> <span className="rail-count">MACC</span>
        </div>
        <button className="ghost" onClick={onClose} title="close">
          ✕
        </button>
      </div>
      <div className="rail-count" style={{ marginTop: 8 }}>
        DEPLOYED ON
      </div>
      {links.map(({ r, i }) => {
        const kind = linkKind(r);
        return (
          <div className="io-line" key={i}>
            <span className="io-name">{kind ? s(r[kind]) : "—"}</span>
            <span className="io-meta">{kind ? KIND_LABEL[kind] : "empty"}</span>
            <span />
            <button className="ghost" onClick={() => dropLink(i)} title="remove deployment">
              ✕
            </button>
          </div>
        );
      })}
      <div className="macc-deploy-row">
        <select
          value={deployKind}
          onChange={(e) => setDeployKind(e.target.value as MaccLinkKind)}
          title="what kind of component to deploy on"
        >
          {MACC_LINK_KINDS.map((k) => (
            <option key={k} value={k}>
              {KIND_LABEL[k]}
            </option>
          ))}
        </select>
        <SearchableSelect
          value=""
          options={deployOptions[deployKind]}
          onChange={(v) => v && onChange(applyMacc(workbook, macc, { [deployKind]: v }))}
          placeholder={`+ deploy on a ${KIND_LABEL[deployKind]}...`}
          hint={`add a ${KIND_LABEL[deployKind]} first`}
        />
      </div>
      <p className="muted">
        A technology deploys on every facility running it; a stream/store on every facility
        consuming it. Each facility adopts independently.
      </p>
    </div>
  );
}

/** Edit one measure's definition + cost blocks; save in place, or save the
 *  edited copy as a NEW catalogue measure that joins this MACC. */
function MeasureEditModal({
  workbook,
  measure,
  macc,
  onChange,
  onClose,
}: {
  workbook: Workbook;
  measure: string;
  macc: string;
  onChange: (wb: Workbook) => void;
  onClose: () => void;
}) {
  const mRow = (workbook.measures ?? []).find((r) => s(r.measure_id) === measure);
  const streams = (workbook.commodities ?? []).map((r) => s(r.commodity_id)).filter(Boolean);
  const impacts = (workbook.impacts ?? []).map((r) => s(r.impact_id)).filter(Boolean);
  const [draft, setDraft] = useState(() => ({
    name: measure,
    type: s(mRow?.type) || "energy_efficiency",
    target: s(mRow?.target),
    lifetime: s(mRow?.lifetime),
    blocks: (workbook.measure_blocks ?? [])
      .filter((r) => s(r.measure_id) === measure)
      .map((b) => ({ block: s(b.block), reduction: s(b.reduction), capex: s(b.capex) })),
  }));
  const targetOptions = draft.type === "energy_efficiency" ? streams : impacts;

  const setBlock = (idx: number, key: "block" | "reduction" | "capex", value: string) =>
    setDraft((d) => ({
      ...d,
      blocks: d.blocks.map((b, i) => (i === idx ? { ...b, [key]: value } : b)),
    }));
  const num = (v: string) => (v === "" ? null : Number(v));
  const builtBlocks = (mid: string): Row[] =>
    draft.blocks.map((b, i) => ({
      measure_id: mid,
      block: num(b.block) ?? i,
      reduction: num(b.reduction) ?? 0,
      capex: num(b.capex) ?? 0,
    }));

  const save = () => {
    onChange({
      ...workbook,
      measures: (workbook.measures ?? []).map((r) =>
        s(r.measure_id) === measure
          ? { ...r, type: draft.type, target: draft.target, lifetime: num(draft.lifetime) }
          : r,
      ),
      measure_blocks: [
        ...(workbook.measure_blocks ?? []).filter((r) => s(r.measure_id) !== measure),
        ...builtBlocks(measure),
      ],
    });
    onClose();
  };

  const saveAsNew = () => {
    const existing = new Set((workbook.measures ?? []).map((r) => s(r.measure_id)));
    let name = draft.name.trim();
    if (!name || existing.has(name)) {
      const base = name || measure;
      let i = 2;
      name = `${base} v${i}`;
      while (existing.has(name)) name = `${base} v${++i}`;
    }
    // Fill a blank membership placeholder if the MACC has one, else append.
    const maccRows = workbook.maccs ?? [];
    const blank = maccRows.findIndex((r) => s(r.macc) === macc && !s(r.measure_id));
    onChange({
      ...workbook,
      measures: [
        ...(workbook.measures ?? []),
        { measure_id: name, type: draft.type, target: draft.target, lifetime: num(draft.lifetime) },
      ],
      measure_blocks: [...(workbook.measure_blocks ?? []), ...builtBlocks(name)],
      maccs:
        blank >= 0
          ? maccRows.map((r, i) => (i === blank ? { ...r, measure_id: name } : r))
          : [...maccRows, { macc, measure_id: name }],
    });
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="detail-head">
          <strong>Edit measure — {measure}</strong>
          <button className="ghost" onClick={onClose} title="close">
            ✕
          </button>
        </div>
        <label className="inspector-field">
          <span>Name (change it to save as a new measure)</span>
          <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        </label>
        <div className="modal-two-col">
          <label className="inspector-field">
            <span>Type</span>
            <select
              value={draft.type}
              onChange={(e) => setDraft({ ...draft, type: e.target.value })}
            >
              <option value="energy_efficiency">energy_efficiency</option>
              <option value="emission_reduction">emission_reduction</option>
              <option value="environmental">environmental</option>
            </select>
          </label>
          <label className="inspector-field">
            <span>Target {draft.type === "energy_efficiency" ? "stream" : "impact"}</span>
            <select
              value={draft.target}
              onChange={(e) => setDraft({ ...draft, target: e.target.value })}
            >
              <option value="">—</option>
              {targetOptions.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="inspector-field">
          <span>Lifetime (yr)</span>
          <input
            value={draft.lifetime}
            onChange={(e) => setDraft({ ...draft, lifetime: e.target.value })}
          />
        </label>
        <div className="rail-count" style={{ marginTop: 8 }}>
          COST BLOCKS
        </div>
        <div className="measure-block-head">
          <span>block</span>
          <span>reduction</span>
          <span>capex</span>
          <span />
        </div>
        {draft.blocks.map((b, i) => (
          <div key={i} className="measure-block-row">
            <input value={b.block} onChange={(e) => setBlock(i, "block", e.target.value)} />
            <input value={b.reduction} onChange={(e) => setBlock(i, "reduction", e.target.value)} />
            <input value={b.capex} onChange={(e) => setBlock(i, "capex", e.target.value)} />
            <button
              className="ghost"
              onClick={() =>
                setDraft((d) => ({ ...d, blocks: d.blocks.filter((_, j) => j !== i) }))
              }
              title="remove block"
            >
              ✕
            </button>
          </div>
        ))}
        <button
          className="ghost"
          onClick={() =>
            setDraft((d) => ({
              ...d,
              blocks: [...d.blocks, { block: String(d.blocks.length), reduction: "0.1", capex: "0" }],
            }))
          }
        >
          + block
        </button>
        <div className="modal-actions">
          <button onClick={save}>Save changes</button>
          <button onClick={saveAsNew} title="keep the original and add the edited copy to this MACC">
            Save as new measure
          </button>
        </div>
      </div>
    </div>
  );
}

interface Props {
  workbook: Workbook;
  macc: string;
  onChange: (wb: Workbook) => void;
}

/** Editor for ONE MACC across three tabs: Description (what the MACC currently
 *  does), Table (pick which catalogue measures are included; edit /
 *  save-as-new), and the interactive MACC chart. Deployment lives in the right
 *  rail (MaccDeployRail). Individual measures have no chart of their own — the
 *  curve belongs to the MACC. */
export function MaccPanel({ workbook, macc, onChange }: Props) {
  const [tab, setTab] = useState<MaccTab>("description");
  const [editing, setEditing] = useState<string | null>(null);
  const members = (workbook.maccs ?? [])
    .filter((r) => s(r.macc) === macc)
    .map((r) => s(r.measure_id))
    .filter(Boolean);
  const links = (workbook.macc_links ?? [])
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => s(r.macc) === macc);
  const data = useMemo(() => maccBars(workbook, macc), [workbook, macc]);
  const summary = useMemo(() => stats(data), [data]);
  const catalogue = (workbook.measures ?? []).map((r) => s(r.measure_id)).filter(Boolean);
  // Members missing from the catalogue still show (red) so they can be removed.
  const pickable = [...new Set([...catalogue, ...members])];

  const addMember = (mid: string) => {
    if (!mid || members.includes(mid)) return;
    const rows = workbook.maccs ?? [];
    const blank = rows.findIndex((r) => s(r.macc) === macc && !s(r.measure_id));
    onChange({
      ...workbook,
      maccs:
        blank >= 0
          ? rows.map((r, i) => (i === blank ? { ...r, measure_id: mid } : r))
          : [...rows, { macc, measure_id: mid }],
    });
  };
  const dropMember = (mid: string) => {
    const rows = (workbook.maccs ?? []).filter(
      (r) => !(s(r.macc) === macc && s(r.measure_id) === mid),
    );
    onChange({
      ...workbook,
      maccs: rows.some((r) => s(r.macc) === macc) ? rows : [...rows, { macc, measure_id: null }],
    });
  };
  const blocksOf = (mid: string) =>
    (workbook.measure_blocks ?? []).filter((r) => s(r.measure_id) === mid);
  const measureRow = (mid: string) =>
    (workbook.measures ?? []).find((r) => s(r.measure_id) === mid);

  return (
    <div className="macc-panel">
      <div className="macc-tabs">
        {(["description", "table", "chart"] as const).map((view) => (
          <button
            key={view}
            className={`tab${tab === view ? " active" : ""}`}
            onClick={() => setTab(view)}
          >
            {view === "description" ? "Description" : view === "table" ? "Table" : "MACC chart"}
          </button>
        ))}
      </div>
      <div className="macc-content">
        {tab === "description" && (
          <>
            <div className="macc-summary-strip">
              <SummaryMetric label="Measures" value={members.length} />
              <SummaryMetric label="Deployments" value={links.length} />
              <SummaryMetric label="Facilities" value={summary.facilities} />
              <SummaryMetric label="Potential" value={fmt(summary.potential)} />
              <SummaryMetric label="Avg $/unit" value={fmt(summary.weightedCost)} />
            </div>
            <section className="macc-section">
              <div className="rail-count">WHAT THIS MACC CURRENTLY DOES</div>
              <MaccMeasureTable data={data} />
              <p className="muted">
                Deploy this MACC on a facility, technology, stream or store in the panel on the
                right; pick its measures in the Table tab.
              </p>
            </section>
          </>
        )}
        {tab === "table" && (
          <section className="macc-section">
            <div className="rail-count">MEASURES — tick to include in this MACC</div>
            {!pickable.length && <p className="muted">No measures in the catalogue yet.</p>}
            {pickable.length > 0 && (
              <div className="table-wrap">
                <table className="macc-picker">
                  <thead>
                    <tr>
                      <th />
                      <th>measure</th>
                      <th>type</th>
                      <th>target</th>
                      <th>blocks</th>
                      <th>Σ reduction</th>
                      <th>Σ capex</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {pickable.map((mid) => {
                      const row = measureRow(mid);
                      const blocks = blocksOf(mid);
                      const included = members.includes(mid);
                      const totalReduction = blocks.reduce((t, b) => t + Number(b.reduction ?? 0), 0);
                      const totalCapex = blocks.reduce((t, b) => t + Number(b.capex ?? 0), 0);
                      return (
                        <tr key={mid} className={row ? undefined : "row-broken"}>
                          <td>
                            <input
                              type="checkbox"
                              checked={included}
                              onChange={() => (included ? dropMember(mid) : addMember(mid))}
                              title={included ? "remove from this MACC" : "include in this MACC"}
                            />
                          </td>
                          <td>{mid}</td>
                          <td>{row ? s(row.type) || "energy_efficiency" : "missing measure"}</td>
                          <td>{row ? s(row.target) || "—" : "—"}</td>
                          <td>{blocks.length}</td>
                          <td>{totalReduction.toFixed(2)}</td>
                          <td>{totalCapex.toFixed(1)}</td>
                          <td>
                            {row && (
                              <button
                                className="ghost"
                                onClick={() => setEditing(mid)}
                                title="edit blocks / save as new measure"
                              >
                                edit
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <p className="muted">
              Editing changes the catalogue measure everywhere it is used; “Save as new measure”
              keeps the original and adds the edited copy to this MACC.
            </p>
          </section>
        )}
        {tab === "chart" && <MaccChart data={data} />}
      </div>
      {editing && (
        <MeasureEditModal
          workbook={workbook}
          measure={editing}
          macc={macc}
          onChange={onChange}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

export function MaccOverview({
  workbook,
  onSelect,
}: {
  workbook: Workbook;
  onSelect: (macc: string) => void;
}) {
  const names = allMaccNames(workbook);
  if (!names.length) return <p className="muted">No MACCs yet.</p>;

  const membersOf = (name: string) =>
    (workbook.maccs ?? [])
      .filter((r) => s(r.macc) === name)
      .map((r) => s(r.measure_id))
      .filter(Boolean);
  const linksOf = (name: string) =>
    (workbook.macc_links ?? []).filter((r) => s(r.macc) === name && linkKind(r));
  const linkLabel = (r: Row) => {
    const kind = linkKind(r);
    return kind ? s(r[kind]) : "";
  };

  return (
    <div className="macc-overview table-wrap">
      <table>
        <thead>
          <tr>
            <th>MACC</th>
            <th>measures included</th>
            <th>deployed on</th>
            <th>potential</th>
            <th>avg $/unit</th>
          </tr>
        </thead>
        <tbody>
          {names.map((name) => {
            const data = maccBars(workbook, name);
            const summary = stats(data);
            const members = membersOf(name);
            const links = linksOf(name);
            return (
              <tr key={name}>
                <td>
                  <button className="ghost macc-link" onClick={() => onSelect(name)}>
                    {name}
                  </button>
                </td>
                <td>{members.length ? members.join(", ") : "—"}</td>
                <td>{links.length ? links.map(linkLabel).join(", ") : "—"}</td>
                <td>{fmt(summary.potential)}</td>
                <td>{fmt(summary.weightedCost)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
