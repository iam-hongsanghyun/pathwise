import { applyMacc } from "../../lib/graph";
import type { Workbook } from "../../types";
import { SearchableSelect } from "../controls/SearchableSelect";
import { MaccDesigner } from "./MaccDesigner";

const s = (v: unknown) => (v == null ? "" : String(v));

interface Props {
  workbook: Workbook;
  macc: string;
  onChange: (wb: Workbook) => void;
}

/** Editor for ONE MACC: the bundle of measures it contains (reusable across
 *  MACCs), where it is deployed (facilities / technologies — each facility
 *  adopts independently), and its abatement-cost chart. Individual measures
 *  have no chart of their own — the curve belongs to the MACC. */
export function MaccPanel({ workbook, macc, onChange }: Props) {
  const members = (workbook.maccs ?? [])
    .filter((r) => s(r.macc) === macc)
    .map((r) => s(r.measure_id));
  const links = (workbook.macc_links ?? [])
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => s(r.macc) === macc);
  const addable = (workbook.measures ?? [])
    .map((r) => s(r.measure_id))
    .filter((m) => m && !members.includes(m));
  const facs = (workbook.processes ?? []).map((r) => s(r.process_id)).filter(Boolean);
  const techs = (workbook.technologies ?? []).map((r) => s(r.technology_id)).filter(Boolean);

  const addMember = (mid: string) =>
    mid &&
    onChange({ ...workbook, maccs: [...(workbook.maccs ?? []), { macc, measure_id: mid }] });
  const dropMember = (mid: string) =>
    onChange({
      ...workbook,
      maccs: (workbook.maccs ?? []).filter((r) => !(s(r.macc) === macc && s(r.measure_id) === mid)),
    });
  const dropLink = (idx: number) =>
    onChange({
      ...workbook,
      macc_links: (workbook.macc_links ?? []).filter((_, i) => i !== idx),
    });

  return (
    <div className="macc-panel">
      <div className="macc-side">
        <div className="rail-count">MEASURES IN THIS MACC (reusable across MACCs)</div>
        {members.map((m) => (
          <div className="io-line" key={m}>
            <span className="io-name">{m}</span>
            <span className="io-meta" />
            <span />
            <button className="ghost" onClick={() => dropMember(m)} title="remove from this MACC">
              ✕
            </button>
          </div>
        ))}
        <SearchableSelect
          value=""
          options={addable}
          onChange={addMember}
          placeholder="+ add a measure…"
          hint="add a measure first (Measures group)"
        />
        <div className="rail-count" style={{ marginTop: 12 }}>
          DEPLOYED ON (each facility adopts independently)
        </div>
        {links.map(({ r, i }) => (
          <div className="io-line" key={i}>
            <span className="io-name">{s(r.facility) || s(r.technology)}</span>
            <span className="io-meta">{s(r.facility) ? "facility" : "technology"}</span>
            <span />
            <button className="ghost" onClick={() => dropLink(i)} title="remove deployment">
              ✕
            </button>
          </div>
        ))}
        <SearchableSelect
          value=""
          options={facs}
          onChange={(v) => v && onChange(applyMacc(workbook, macc, { facility: v }))}
          placeholder="+ deploy on a facility…"
          hint="add a facility first"
        />
        <SearchableSelect
          value=""
          options={techs}
          onChange={(v) => v && onChange(applyMacc(workbook, macc, { technology: v }))}
          placeholder="+ …or on a technology (all its facilities)"
          hint="add a technology first"
        />
        {!members.length && (
          <p className="muted">An empty MACC — add measures above to build its curve.</p>
        )}
        {members.length > 0 && !links.length && (
          <p className="muted">Not deployed yet — the measures stay inert until linked.</p>
        )}
      </div>
      <div className="macc-chart">
        <MaccDesigner workbook={workbook} macc={macc} />
      </div>
    </div>
  );
}
