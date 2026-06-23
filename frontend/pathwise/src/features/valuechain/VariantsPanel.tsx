// Authoring of model-resident **variants** (simulate what-if scenarios) in the
// value chain. A variant is a named key; each row under it is a timed
// intervention — force a machine onto an alternative technology, change a
// commodity's price, or enable a measure, from a given year. Writes the
// `variants` + `variant_interventions` sheets the simulate backend reads (the
// optimiser ignores them). No API call — edits flow through the workbook like
// every other value-chain edit.

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
  { value: "measure", label: "Enable measure" },
];

export function VariantsPanel({
  workbook,
  setWorkbook,
  machineId,
}: {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
  /** Pre-fills a new `tech` intervention's target with the open machine. */
  machineId?: string;
}) {
  const variants = (workbook.variants ?? []) as Row[];
  const inter = (workbook.variant_interventions ?? []) as Row[];
  const machines = machineId
    ? [machineId, ...ids(workbook.machines, "machine_id").filter((m) => m !== machineId)]
    : ids(workbook.machines, "machine_id");
  const techs = ids(workbook.technologies, "technology_id");
  const commodities = ids(workbook.commodities, "commodity_id");
  const measures = ids(workbook.measures, "measure_id");
  const years = (workbook.periods ?? [])
    .map((r) => Number(r.year))
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  const firstYear = years[0] ?? 2025;

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
        target: machineId ?? machines[0] ?? "",
        value: techs[0] ?? "",
        forced_year: firstYear,
      },
    ]);
  const patch = (i: number, p: Row) => setInter(inter.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const remove = (i: number) => setInter(inter.filter((_, j) => j !== i));

  // Rows of the live variant, paired with their absolute index for editing.
  const rows = inter.map((r, i) => ({ r, i })).filter((x) => s(x.r.variant_id) === live);

  const targetList = (kind: string) =>
    kind === "tech" ? machines : kind === "stream" ? commodities : measures;

  const valueCell = (r: Row, i: number) => {
    const kind = s(r.kind);
    if (kind === "stream")
      return (
        <input
          type="number"
          className="field-input"
          style={{ width: 90 }}
          value={s(r.value)}
          onChange={(e) => patch(i, { value: e.target.value === "" ? 0 : Number(e.target.value) })}
          aria-label="price"
        />
      );
    const opts = kind === "tech" ? techs : [{ value: "on" }, { value: "off" }].map((o) => o.value);
    return (
      <SearchSelect
        value={s(r.value) || (kind === "measure" ? "on" : "")}
        onChange={(v) => patch(i, { value: v })}
        options={opts.map((o) => ({ value: o }))}
      />
    );
  };

  const cell: React.CSSProperties = { padding: "2px 3px" };

  return (
    <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12, marginTop: 4 }}>
      <h4 style={{ margin: "0 0 2px", fontSize: ".82rem" }}>Variants (what-if)</h4>
      <p className="muted" style={{ fontSize: ".72rem", margin: "0 0 8px" }}>
        Named what-ifs the <strong>Scenario simulator</strong> evaluates — force a switch (or price /
        measure change) from a year. The optimiser ignores these.
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
                      onChange={(v) =>
                        patch(i, { kind: v, target: targetList(v)[0] ?? "", value: v === "stream" ? 0 : v === "measure" ? "on" : techs[0] ?? "" })
                      }
                      options={KIND_OPTS}
                    />
                  </td>
                  <td style={cell}>
                    <SearchSelect
                      value={s(r.target)}
                      onChange={(v) => patch(i, { target: v })}
                      options={targetList(s(r.kind) || "tech").map((o) => ({ value: o }))}
                    />
                  </td>
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
