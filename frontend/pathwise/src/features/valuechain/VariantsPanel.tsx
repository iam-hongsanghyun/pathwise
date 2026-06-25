// Authoring of model-resident **variants** (simulate what-if scenarios) in the
// network. A variant is a named key; each row under it is a timed
// intervention — force a asset onto an alternative technology, change a
// flow's price, or enable a lever, from a given year. Writes the
// `variants` + `variant_interventions` sheets the simulate backend reads (the
// optimiser ignores them). No API call — edits flow through the workbook like
// every other network edit.

import { useState } from "react";
import { SearchSelect } from "../controls/SearchSelect";
import type { Row, Workbook } from "../../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const ids = (rows: Row[] | undefined, col: string): string[] =>
  [...new Set((rows ?? []).map((r) => s(r[col])).filter(Boolean))];
const slug = (x: string): string =>
  x.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "variant";

const KIND_OPTS = [
  { value: "tech", label: "Switch technology" },
  { value: "stream", label: "Change price" },
  { value: "lever", label: "Enable lever" },
  { value: "tech_cost", label: "Change tech cost" },
  { value: "io_coef", label: "Change I/O rate" },
  { value: "stream_cap", label: "Change flow cap" },
];

//: Kinds whose value is a plain number (the rest pick from a list).
const NUMERIC_KINDS = new Set(["stream", "tech_cost", "io_coef", "stream_cap"]);

//: The "field" sub-attribute each value-edit kind needs (else none).
const FIELD_OPTS: Record<string, string[]> = {
  tech_cost: ["capex", "opex"],
  stream_cap: ["max_purchase", "available_from", "available_to"],
};

export function VariantsPanel({
  workbook,
  setWorkbook,
  machineId,
}: {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  /** Pre-fills a new `tech` intervention's target with the open asset. */
  machineId?: string;
}) {
  const variants = (workbook.variants ?? []) as Row[];
  const inter = (workbook.variant_interventions ?? []) as Row[];
  const assets = machineId
    ? [machineId, ...ids(workbook.assets, "asset_id").filter((m) => m !== machineId)]
    : ids(workbook.assets, "asset_id");
  const flows = ids(workbook.flows, "flow_id");
  const levers = ids(workbook.levers, "lever_id");
  const technologies = ids(workbook.technologies, "technology_id");
  // Flows a technology actually uses (its io targets) — for io_coef.
  const ioOf = (tech: string): string[] =>
    [...new Set((workbook.io ?? []).filter((r) => s(r.technology_id) === tech).map((r) => s(r.target)).filter(Boolean))];
  const years = (workbook.periods ?? [])
    .map((r) => Number(r.year))
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  const firstYear = years[0] ?? 2025;

  // A tech intervention may only force an EXISTING alternative of the asset —
  // the transition targets defined for its baseline (added via "Add alternative…"
  // in the network / Facility first). Not the whole technology library.
  const baselineOf = (m: string): string =>
    s((workbook.assets ?? []).find((x) => s(x.asset_id) === m)?.baseline_technology);
  const altsFor = (m: string): string[] => {
    const base = baselineOf(m);
    return [
      ...new Set(
        (workbook.transitions ?? [])
          .filter((t) => s(t.from_technology) === base)
          .map((t) => s(t.to_technology))
          .filter(Boolean),
      ),
    ];
  };

  const [active, setActive] = useState<string>(s(variants[0]?.variant_id));
  const live = active && variants.some((v) => s(v.variant_id) === active) ? active : s(variants[0]?.variant_id);

  const setInter = (rows: Row[]) => setWorkbook({ ...workbook, variant_interventions: rows });
  const setVariants = (rows: Row[]) => setWorkbook({ ...workbook, variants: rows });

  const createVariant = (name: string) => {
    const id = slug(name);
    if (!variants.some((v) => s(v.variant_id) === id)) setVariants([...variants, { variant_id: id, label: name }]);
    setActive(id);
  };
  const deleteVariant = (id: string) => {
    setWorkbook({
      ...workbook,
      variants: variants.filter((v) => s(v.variant_id) !== id),
      variant_interventions: inter.filter((r) => s(r.variant_id) !== id),
    });
    setActive("");
  };

  const addRow = () =>
    setInter([
      ...inter,
      {
        variant_id: live,
        kind: "tech",
        target: machineId ?? assets[0] ?? "",
        value: altsFor(machineId ?? assets[0] ?? "")[0] ?? "",
        forced_year: firstYear,
      },
    ]);
  const patch = (i: number, p: Row) => setInter(inter.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const remove = (i: number) => setInter(inter.filter((_, j) => j !== i));

  // Rows of the live variant, paired with their absolute index for editing.
  const rows = inter.map((r, i) => ({ r, i })).filter((x) => s(x.r.variant_id) === live);

  const targetList = (kind: string): string[] => {
    if (kind === "tech") return assets;
    if (kind === "stream" || kind === "stream_cap") return flows;
    if (kind === "tech_cost" || kind === "io_coef") return technologies;
    return levers;
  };
  // The "field" sub-attribute options for a kind (io_coef uses the tech's io flows).
  const fieldList = (kind: string, target: string): string[] =>
    kind === "io_coef" ? ioOf(target) : (FIELD_OPTS[kind] ?? []);

  const fieldCell = (r: Row, i: number) => {
    const opts = fieldList(s(r.kind), s(r.target));
    if (opts.length === 0) return <span className="muted">—</span>;
    return (
      <SearchSelect
        value={s(r.field) || opts[0]}
        onChange={(v) => patch(i, { field: v })}
        options={opts.map((o) => ({ value: o }))}
      />
    );
  };

  // The starting value when a row's kind/target changes.
  const defaultValue = (kind: string, target: string): string | number =>
    kind === "tech" ? (altsFor(target)[0] ?? "") : kind === "lever" ? "on" : 0;

  const valueCell = (r: Row, i: number) => {
    const kind = s(r.kind);
    if (NUMERIC_KINDS.has(kind))
      return (
        <input
          type="number"
          className="field-input"
          style={{ width: 90 }}
          value={s(r.value)}
          onChange={(e) => patch(i, { value: e.target.value === "" ? 0 : Number(e.target.value) })}
          aria-label="value"
        />
      );
    if (kind === "tech") {
      const opts = altsFor(s(r.target));
      if (opts.length === 0)
        return (
          <span className="muted" style={{ fontSize: ".72rem" }} title="Add an alternative to this asset in the network first">
            add an alternative first
          </span>
        );
      return (
        <SearchSelect
          value={s(r.value)}
          onChange={(v) => patch(i, { value: v })}
          options={opts.map((o) => ({ value: o }))}
        />
      );
    }
    // lever
    return (
      <SearchSelect
        value={s(r.value) || "on"}
        onChange={(v) => patch(i, { value: v })}
        options={[{ value: "on" }, { value: "off" }]}
      />
    );
  };

  const cell: React.CSSProperties = { padding: "2px 3px" };

  return (
    <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12, marginTop: 4 }}>
      <h4 style={{ margin: "0 0 2px", fontSize: ".82rem" }}>Variants (what-if)</h4>
      <p className="muted" style={{ fontSize: ".72rem", margin: "0 0 8px" }}>
        Named what-ifs the <strong>Scenario simulator</strong> evaluates — force a switch (or price /
        lever change) from a year. The optimiser ignores these.
      </p>

      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 8 }}>
        <span className="muted" style={{ fontSize: ".74rem" }}>variant</span>
        <div style={{ minWidth: 150 }}>
          <SearchSelect
            value={live}
            onChange={setActive}
            onCreate={createVariant}
            options={variants.map((v) => ({ value: s(v.variant_id), label: s(v.label) || s(v.variant_id) }))}
            placeholder="select or type a new name…"
          />
        </div>
        {live && (
          <button className="ghost" title="delete this variant" onClick={() => deleteVariant(live)}>
            ✕
          </button>
        )}
      </div>

      {!live ? (
        <p className="muted" style={{ fontSize: ".74rem" }}>
          Type a name above to create the first variant.
        </p>
      ) : (
        <>
          <table className="grid" style={{ width: "100%", fontSize: ".74rem" }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                <th>do</th>
                <th>to</th>
                <th>field</th>
                <th>value</th>
                <th>from</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map(({ r, i }) => (
                <tr key={i}>
                  <td style={cell}>
                    <SearchSelect
                      value={s(r.kind) || "tech"}
                      onChange={(v) => {
                        const t = targetList(v)[0] ?? "";
                        patch(i, {
                          kind: v,
                          target: t,
                          field: fieldList(v, t)[0] ?? "",
                          value: defaultValue(v, t),
                        });
                      }}
                      options={KIND_OPTS}
                    />
                  </td>
                  <td style={cell}>
                    <SearchSelect
                      value={s(r.target)}
                      onChange={(v) =>
                        patch(i, {
                          target: v,
                          field: fieldList(s(r.kind), v)[0] ?? "",
                          value: defaultValue(s(r.kind) || "tech", v),
                        })
                      }
                      options={targetList(s(r.kind) || "tech").map((o) => ({ value: o }))}
                    />
                  </td>
                  <td style={cell}>{fieldCell(r, i)}</td>
                  <td style={cell}>{valueCell(r, i)}</td>
                  <td style={cell}>
                    <input
                      type="number"
                      className="field-input"
                      style={{ width: 64 }}
                      value={s(r.forced_year)}
                      onChange={(e) => patch(i, { forced_year: e.target.value === "" ? "" : Number(e.target.value) })}
                      placeholder={String(firstYear)}
                      aria-label="from year"
                    />
                  </td>
                  <td>
                    <button className="ghost" title="remove" onClick={() => remove(i)}>
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="ghost" style={{ fontSize: ".74rem", marginTop: 6 }} onClick={addRow}>
            ＋ add intervention
          </button>
        </>
      )}
    </div>
  );
}
