import { useState } from "react";
import { applyMacc, type MaccLinkKind } from "../../lib/graph";
import { emptyHint, isFreeName, optionsFor, refTargets, type RefTarget } from "../../lib/references";
import type { Cell, Selection, Workbook } from "../../types";
import { CreateComponentModal } from "../controls/CreateComponentModal";
import { InfoTip } from "../controls/InfoTip";
import { SearchableSelect } from "../controls/SearchableSelect";

type SchemaMap = Record<
  string,
  {
    label?: string;
    columns?: Record<string, { label?: string; type?: string; required?: boolean; desc?: string }>;
  }
>;

interface Props {
  workbook: Workbook;
  selected: Selection;
  schema: SchemaMap;
  onChange: (wb: Workbook) => void;
  onClose: () => void;
  floating?: boolean;
}

function coerce(value: string): Cell {
  if (value === "") return null;
  if (value === "true") return true;
  if (value === "false") return false;
  const n = Number(value);
  return Number.isNaN(n) || value.trim() === "" ? value : n;
}

/** A commodity owns its emission factors: consuming `factor` per unit becomes
 *  real emission at the facility (emission = consumption × factor). Edited here
 *  as a commodity attribute (stored in the commodity_impacts sheet). */
function EmissionFactors({
  workbook,
  commodity,
  onChange,
}: {
  workbook: Workbook;
  commodity: string;
  onChange: (wb: Workbook) => void;
}) {
  const rows = workbook.commodity_impacts ?? [];
  const impacts = (workbook.impacts ?? []).map((r) => String(r.impact_id ?? "")).filter(Boolean);
  const mine = rows
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => String(r.commodity_id ?? "") === commodity);

  const setFactor = (idx: number, val: string) =>
    onChange({
      ...workbook,
      commodity_impacts: rows.map((r, i) =>
        i === idx ? { ...r, factor: val === "" ? null : Number(val) } : r,
      ),
    });
  const setImpact = (idx: number, val: string) =>
    onChange({
      ...workbook,
      commodity_impacts: rows.map((r, i) => (i === idx ? { ...r, impact_id: val } : r)),
    });
  const add = () =>
    onChange({
      ...workbook,
      commodity_impacts: [...rows, { commodity_id: commodity, impact_id: impacts[0] ?? "", factor: 0 }],
    });
  const del = (idx: number) =>
    onChange({ ...workbook, commodity_impacts: rows.filter((_, i) => i !== idx) });

  return (
    <div className="emission-factors">
      <div className="rail-count" style={{ marginTop: 8 }}>EMISSION FACTORS (per unit consumed)</div>
      {mine.map(({ r, i }) => (
        <div key={i} className="ef-row">
          <select value={String(r.impact_id ?? "")} onChange={(e) => setImpact(i, e.target.value)}>
            <option value="">—</option>
            {impacts.map((imp) => (
              <option key={imp} value={imp}>
                {imp}
              </option>
            ))}
          </select>
          <input
            value={r.factor == null ? "" : String(r.factor)}
            onChange={(e) => setFactor(i, e.target.value)}
          />
          <button className="ghost" onClick={() => del(i)} title="remove">
            ✕
          </button>
        </div>
      ))}
      <button className="ghost" onClick={add}>
        + factor
      </button>
    </div>
  );
}

/** A technology owns its I/O: inputs (streams it consumes), outputs (what it
 *  makes), and impacts (direct emissions). Edited here as part of the technology
 *  — there is no separate I/O table. Stored in the `io` sheet. */
const num = (v: Cell) => (v == null || v === "" ? "" : String(v));

/** Centered popup to edit one input stream's intensity + blend bounds. */
function InputModal({
  row,
  streams,
  onSet,
  onClose,
}: {
  row: Record<string, Cell>;
  streams: string[];
  onSet: (patch: Record<string, Cell>) => void;
  onClose: () => void;
}) {
  const blended = row.group != null && row.group !== "";
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="detail-head">
          <strong>Edit input</strong>
          <button className="ghost" onClick={onClose} title="close">
            ✕
          </button>
        </div>
        <label className="inspector-field">
          <span>Fuel / stream</span>
          <select value={String(row.target ?? "")} onChange={(e) => onSet({ target: e.target.value })}>
            <option value="">—</option>
            {streams.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
        <label className="inspector-field">
          <span>Intensity (input ÷ output, per unit throughput)</span>
          <input
            value={num(row.coefficient)}
            onChange={(e) => onSet({ coefficient: e.target.value === "" ? null : Number(e.target.value) })}
          />
        </label>
        <label className="inspector-field">
          <span>Type</span>
          <select
            value={blended ? "blend" : "fixed"}
            onChange={(e) =>
              onSet(
                e.target.value === "blend"
                  ? { group: "blend" }
                  : { group: null, share_min: null, share_max: null },
              )
            }
          >
            <option value="fixed">Fixed input (always consumed)</option>
            <option value="blend">Blended (share of a fuel mix)</option>
          </select>
        </label>
        {blended && (
          <>
            <label className="inspector-field">
              <span>Blend group (same name = mixed together)</span>
              <input value={String(row.group ?? "")} onChange={(e) => onSet({ group: e.target.value || null })} />
            </label>
            <div className="modal-two-col">
              <label className="inspector-field">
                <span>Min share (0–1)</span>
                <input
                  value={num(row.share_min)}
                  placeholder="0"
                  onChange={(e) => onSet({ share_min: e.target.value === "" ? null : Number(e.target.value) })}
                />
              </label>
              <label className="inspector-field">
                <span>Max share (0–1)</span>
                <input
                  value={num(row.share_max)}
                  placeholder="1"
                  onChange={(e) => onSet({ share_max: e.target.value === "" ? null : Number(e.target.value) })}
                />
              </label>
            </div>
            <p className="muted">
              Min = max → fixed share; min only → at least; max only → at most. Sum across the group
              is the total fuel, so the others fill the rest.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function TechnologyIO({
  workbook,
  technology,
  onChange,
}: {
  workbook: Workbook;
  technology: string;
  onChange: (wb: Workbook) => void;
}) {
  const [editing, setEditing] = useState<number | null>(null);
  const io = workbook.io ?? [];
  const streams = (workbook.commodities ?? []).map((r) => String(r.commodity_id ?? "")).filter(Boolean);
  const impacts = (workbook.impacts ?? []).map((r) => String(r.impact_id ?? "")).filter(Boolean);
  const mine = io.map((r, i) => ({ r, i })).filter(({ r }) => String(r.technology_id ?? "") === technology);

  const set = (idx: number, key: string, val: Cell) =>
    onChange({ ...workbook, io: io.map((r, i) => (i === idx ? { ...r, [key]: val } : r)) });
  const setMany = (idx: number, patch: Record<string, Cell>) =>
    onChange({ ...workbook, io: io.map((r, i) => (i === idx ? { ...r, ...patch } : r)) });
  const del = (idx: number) => onChange({ ...workbook, io: io.filter((_, i) => i !== idx) });
  const addInput = () => {
    const next = [...io, { technology_id: technology, target: "", role: "input", coefficient: 1 }];
    onChange({ ...workbook, io: next });
    setEditing(next.length - 1);
  };
  const add = (role: "output" | "impact") =>
    onChange({
      ...workbook,
      io: [...io, { technology_id: technology, target: "", role, coefficient: role === "impact" ? 0 : 1 }],
    });

  const blendLabel = (r: Record<string, Cell>) => {
    if (r.group == null || r.group === "") return `fixed ${num(r.coefficient) || 0}`;
    const lo = num(r.share_min) || "0";
    const hi = num(r.share_max) === "" ? "1" : num(r.share_max);
    return `blend ${lo}–${hi}`;
  };

  // Inline editor for outputs / direct impacts (a stream + a coefficient).
  const SimpleSection = ({ role, label }: { role: "output" | "impact"; label: string }) => {
    const opts = role === "impact" ? impacts : streams;
    return (
      <>
        <div className="rail-count" style={{ marginTop: 6 }}>{label}</div>
        {mine
          .filter(({ r }) => String(r.role ?? "input") === role)
          .map(({ r, i }) => (
            <div key={i} className="ef-row">
              <select value={String(r.target ?? "")} onChange={(e) => set(i, "target", e.target.value)}>
                <option value="">—</option>
                {opts.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
              <input
                value={num(r.coefficient)}
                onChange={(e) => set(i, "coefficient", e.target.value === "" ? null : Number(e.target.value))}
              />
              <button className="ghost" onClick={() => del(i)} title="remove">
                ✕
              </button>
            </div>
          ))}
      </>
    );
  };

  return (
    <div className="emission-factors">
      <div className="rail-count" style={{ marginTop: 8 }}>TECHNOLOGY I/O (per unit throughput)</div>
      <div className="rail-count" style={{ marginTop: 6 }}>inputs (fuels / feedstocks)</div>
      {mine
        .filter(({ r }) => String(r.role ?? "input") === "input")
        .map(({ r, i }) => (
          <div key={i} className="io-line">
            <span className="io-name">{String(r.target) || "—"}</span>
            <span className="io-meta">{blendLabel(r)}</span>
            <button className="ghost" onClick={() => setEditing(i)}>edit</button>
            <button className="ghost" onClick={() => del(i)} title="remove">✕</button>
          </div>
        ))}
      <button className="ghost" onClick={addInput}>+ fuel / input</button>
      <SimpleSection role="output" label="outputs (produces)" />
      <SimpleSection role="impact" label="direct impacts (emits)" />
      <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
        <button className="ghost" onClick={() => add("output")}>+ output</button>
        <button className="ghost" onClick={() => add("impact")}>+ impact</button>
      </div>
      {editing != null && io[editing] && (
        <InputModal
          row={io[editing]}
          streams={streams}
          onSet={(patch) => setMany(editing, patch)}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

/** Which macc_links column a deployment from this sheet's detail panel fills. */
const MACC_TARGET_COL: Record<string, MaccLinkKind> = {
  processes: "facility",
  technologies: "technology",
  commodities: "commodity",
  storage: "storage",
};

/** Deploy a MACC from the component's side: facilities, technologies, streams
 *  and stores each list the MACCs deployed on them and can add one — the
 *  mirror of the MACC panel's "deployed on" editor (same macc_links rows). */
function MaccDeployments({
  workbook,
  sheet,
  id,
  onChange,
}: {
  workbook: Workbook;
  sheet: string;
  id: string;
  onChange: (wb: Workbook) => void;
}) {
  const col = MACC_TARGET_COL[sheet];
  const links = (workbook.macc_links ?? [])
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => String(r[col] ?? "") === id);
  const names = [
    ...new Set(
      [...(workbook.maccs ?? []), ...(workbook.macc_links ?? [])]
        .map((r) => String(r.macc ?? ""))
        .filter(Boolean),
    ),
  ].sort();
  const here = new Set(links.map(({ r }) => String(r.macc ?? "")));
  const addable = names.filter((n) => !here.has(n));
  const remove = (idx: number) =>
    onChange({ ...workbook, macc_links: (workbook.macc_links ?? []).filter((_, i) => i !== idx) });

  return (
    <div className="emission-factors">
      <div className="rail-count" style={{ marginTop: 8 }}>
        MACC DEPLOYMENT
      </div>
      {links.map(({ r, i }) => (
        <div className="io-line" key={i}>
          <span className="io-name">{String(r.macc ?? "")}</span>
          <span className="io-meta">MACC</span>
          <span />
          <button className="ghost" onClick={() => remove(i)} title="remove deployment">
            ✕
          </button>
        </div>
      ))}
      <SearchableSelect
        value=""
        options={addable}
        onChange={(v) => v && onChange(applyMacc(workbook, v, { [col]: id }))}
        placeholder="+ deploy a MACC here..."
        hint="build a MACC first (MACC rail)"
      />
    </div>
  );
}

/** A measure owns its own cost blocks; keep them with the measure inspector so
 *  the user edits one retrofit object instead of hunting through a raw table. */
function MeasureBlocks({
  workbook,
  measure,
  onChange,
}: {
  workbook: Workbook;
  measure: string;
  onChange: (wb: Workbook) => void;
}) {
  const rows = workbook.measure_blocks ?? [];
  const mine = rows
    .map((r, i) => ({ r, i }))
    .filter(({ r }) => String(r.measure_id ?? "") === measure);
  const numeric = (value: string) => (value === "" ? null : Number(value));
  const set = (idx: number, key: string, val: Cell) =>
    onChange({ ...workbook, measure_blocks: rows.map((r, i) => (i === idx ? { ...r, [key]: val } : r)) });
  const del = (idx: number) =>
    onChange({ ...workbook, measure_blocks: rows.filter((_, i) => i !== idx) });
  const add = () => {
    const nextBlock =
      mine.reduce((highest, { r }) => Math.max(highest, Number(r.block ?? -1)), -1) + 1;
    onChange({
      ...workbook,
      measure_blocks: [
        ...rows,
        { measure_id: measure, block: nextBlock, reduction: 0.1, capex: 0 },
      ],
    });
  };

  return (
    <div className="measure-blocks">
      <div className="rail-count" style={{ marginTop: 8 }}>
        COST BLOCKS
      </div>
      <div className="measure-block-head">
        <span>block</span>
        <span>reduction</span>
        <span>capex</span>
        <span />
      </div>
      {mine.map(({ r, i }) => (
        <div key={i} className="measure-block-row">
          <input value={num(r.block)} onChange={(e) => set(i, "block", numeric(e.target.value))} />
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={num(r.reduction)}
            onChange={(e) => set(i, "reduction", numeric(e.target.value))}
          />
          <input
            type="number"
            value={num(r.capex)}
            onChange={(e) => set(i, "capex", numeric(e.target.value))}
          />
          <button className="ghost" onClick={() => del(i)} title="remove">
            ✕
          </button>
        </div>
      ))}
      <button className="ghost" onClick={add}>
        + block
      </button>
    </div>
  );
}

/** Detail editor for one entity — rendered in the main panel (Data) or as a
 *  floating card on the canvas (Model). Replaces the old right-rail inspector. */
export function DetailPanel({ workbook, selected, schema, onChange, onClose, floating }: Props) {
  const [creating, setCreating] = useState<{ c: string; name: string; targets: RefTarget[] } | null>(
    null,
  );
  const rows = workbook[selected.sheet] ?? [];
  const idx = rows.findIndex((r) => String(r[selected.idCol] ?? "") === selected.id);
  const row = idx >= 0 ? rows[idx] : undefined;
  const colMeta = (schema[selected.sheet]?.columns ?? {}) as Record<
    string,
    { label?: string; required?: boolean; desc?: string; type?: string }
  >;
  const cols = Object.keys(colMeta);
  const merged = [...new Set([...cols, ...(row ? Object.keys(row) : [])])];
  // Required fields first (bold black), optional after (grey) — schema order.
  const allCols = [
    ...merged.filter((c) => colMeta[c]?.required),
    ...merged.filter((c) => !colMeta[c]?.required),
  ];
  const labelOf = (c: string) => colMeta[c]?.label ?? c;
  const isRequired = (c: string) => Boolean(colMeta[c]?.required);
  const descOf = (c: string) => colMeta[c]?.desc;

  const edit = (col: string, value: string) =>
    onChange({
      ...workbook,
      [selected.sheet]: rows.map((r, i) => (i === idx ? { ...r, [col]: coerce(value) } : r)),
    });

  // Promote a static attribute to a wide temporal table column for this item.
  const makeTemporal = (col: string) => {
    const tsheet = `${selected.sheet}_t__${col}`;
    const years = [...new Set((workbook.periods ?? []).map((r) => Number(r.year)))].sort((a, b) => a - b);
    const byYear = new Map((workbook[tsheet] ?? []).map((r) => [Number(r.year), r]));
    const base = row && typeof row[col] === "number" ? (row[col] as number) : 0;
    const trows = years.map((y) => {
      const ex = byYear.get(y) ?? { year: y };
      return { ...ex, [selected.id]: (ex[selected.id] as number) ?? base };
    });
    onChange({ ...workbook, [tsheet]: trows });
  };
  // Any numeric attribute can be promoted to a per-year time series — no
  // hardcoded whitelist (the `<sheet>_t__<attr>` table is created on demand).
  const numericType = (col: string) => {
    const t = schema[selected.sheet]?.columns?.[col]?.type;
    return t === "number" || t === "integer";
  };
  const canTemporal = (col: string) =>
    col !== selected.idCol &&
    col !== "year" &&
    (numericType(col) || (row != null && typeof row[col] === "number"));
  const remove = () => {
    onChange({ ...workbook, [selected.sheet]: rows.filter((_, i) => i !== idx) });
    onClose();
  };

  return (
    <div className={`detail-panel${floating ? " floating" : ""}`}>
      <div className="detail-head">
        <div>
          <strong>{selected.id}</strong> <span className="rail-count">{selected.sheet}</span>
        </div>
        <button className="ghost" onClick={onClose} title="close">
          ✕
        </button>
      </div>
      {row ? (
        <div className="inspector-form">
          {allCols.map((c) => {
            const opts = c === selected.idCol ? null : optionsFor(workbook, selected.sheet, c, row);
            const value = row[c] == null ? "" : String(row[c]);
            return (
              <label
                key={c}
                className={`inspector-field ${isRequired(c) ? "field-required" : "field-optional"}`}
              >
                <span>
                  {labelOf(c)}
                  {descOf(c) ? (
                    <InfoTip tip={`${descOf(c)} ${isRequired(c) ? "(required)" : "(optional)"}`} />
                  ) : null}
                  {canTemporal(c) && (
                    <button
                      className="make-temporal"
                      title="make this value vary by year (temporal)"
                      onClick={(e) => {
                        e.preventDefault();
                        makeTemporal(c);
                      }}
                    >
                      ⟳ temporal
                    </button>
                  )}
                </span>
                {opts ? (
                  <SearchableSelect
                    value={value}
                    options={opts}
                    broken={
                      !isFreeName(selected.sheet, c) && value !== "" && !opts.includes(value)
                    }
                    hint={emptyHint(selected.sheet, c)}
                    onChange={(v) => edit(c, v)}
                    onCreate={(() => {
                      if (isFreeName(selected.sheet, c)) return (name: string) => edit(c, name);
                      const targets = row ? refTargets(selected.sheet, c, row) : [];
                      return targets.length
                        ? (name: string) => setCreating({ c, name, targets })
                        : undefined;
                    })()}
                  />
                ) : (
                  <input value={value} onChange={(e) => edit(c, e.target.value)} />
                )}
              </label>
            );
          })}
          {creating && row && (
            <CreateComponentModal
              name={creating.name}
              targets={creating.targets}
              schema={schema}
              workbook={workbook}
              onSave={(tsheet, newRow) => {
                onChange({
                  ...workbook,
                  [tsheet]: [...(workbook[tsheet] ?? []), newRow],
                  [selected.sheet]: rows.map((r, i) =>
                    i === idx ? { ...r, [creating.c]: creating.name } : r,
                  ),
                });
                setCreating(null);
              }}
              onCancel={() => {
                edit(creating.c, creating.name);
                setCreating(null);
              }}
            />
          )}
          {selected.sheet === "commodities" && (
            <EmissionFactors workbook={workbook} commodity={selected.id} onChange={onChange} />
          )}
          {selected.sheet === "technologies" && (
            <TechnologyIO workbook={workbook} technology={selected.id} onChange={onChange} />
          )}
          {selected.sheet === "measures" && (
            <MeasureBlocks workbook={workbook} measure={selected.id} onChange={onChange} />
          )}
          {selected.sheet in MACC_TARGET_COL && (
            <MaccDeployments
              workbook={workbook}
              sheet={selected.sheet}
              id={selected.id}
              onChange={onChange}
            />
          )}
          <button className="ghost" onClick={remove}>
            Delete
          </button>
        </div>
      ) : (
        <div className="muted" style={{ padding: "8px 0" }}>
          Row not found.
        </div>
      )}
    </div>
  );
}
