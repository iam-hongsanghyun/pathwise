// Market & Policy — the institutional layer over the physical network.
// Author the economic/regulatory environment: supply/offtake POOLS (flow
// markets), EMISSIONS TRADING (ETS: a free allowance + buy/sell of the deficit/
// surplus), and a blanket CARBON PRICE (a tax on every tonne of an impact). All
// scope-aware (system → region → company → node) so regional policy differs by
// place — the engine of the "balloon effect". Emission caps stay in Optimisation
// (a physical limit on the solve). No engine change: these are the existing
// `markets` / `impact_prices` sheets, just given an editor.

import { useMemo } from "react";
import { SearchSelect } from "../features/controls/SearchSelect";
import { TemporalValue, type TemporalVal } from "../features/controls/TemporalValue";
import { flowUnit, impactUnit, modelCurrency } from "../lib/caps";
import { impactIds, scopeOptions } from "../lib/scope";
import type { Row, Workbook } from "../types";

const s = (v: unknown): string => (v == null ? "" : String(v));
const numOrNull = (v: unknown): number | null => (v == null || v === "" ? null : Number(v));
let _ctr = 0;
const genId = (p: string): string => `${p}_${Date.now().toString(36)}${(_ctr++).toString(36)}`;

function flowIds(wb: Workbook): string[] {
  const out = new Set<string>();
  for (const c of wb.flows ?? []) out.add(s(c.flow_id));
  return [...out].filter(Boolean);
}

// ── Carbon price (impact_prices) ── reuse the per-year TemporalValue pattern ───
interface CPrice {
  impact: string;
  value: TemporalVal;
}

/** Collapse the per-(impact, year) `impact_prices` rows into one row per impact:
 *  a flat value when every model year shares it, else a {year: price} map. */
function gatherPrices(wb: Workbook, years: number[]): CPrice[] {
  const byImpact = new Map<string, Record<string, number>>();
  for (const r of wb.impact_prices ?? []) {
    const iid = s(r.impact_id);
    const y = Number(r.year);
    const p = Number(r.price);
    if (!iid || !Number.isFinite(y) || !Number.isFinite(p)) continue;
    const m = byImpact.get(iid) ?? {};
    m[String(y)] = p;
    byImpact.set(iid, m);
  }
  return [...byImpact].map(([impact, m]) => {
    const vals = Object.values(m);
    const flat = vals.length > 0 && vals.every((v) => v === vals[0]);
    const coversAll = years.length > 0 && years.every((y) => String(y) in m);
    const value: TemporalVal = flat && (coversAll || vals.length === 1) ? vals[0] : m;
    return { impact, value };
  });
}

/** Inverse: a flat price → one row per model year; a trajectory → its year rows. */
function scatterPrices(rows: CPrice[], years: number[]): Row[] {
  const out: Row[] = [];
  for (const { impact, value } of rows) {
    if (!impact) continue;
    if (typeof value === "number") {
      for (const y of years) out.push({ impact_id: impact, year: y, price: value });
    } else {
      for (const [y, p] of Object.entries(value)) out.push({ impact_id: impact, year: Number(y), price: p });
    }
  }
  return out;
}

export function MarketPolicyView({
  workbook,
  setWorkbook,
}: {
  workbook: Workbook;
  setWorkbook: (wb: Workbook) => void;
}) {
  const scopes = useMemo(() => scopeOptions(workbook), [workbook]);
  const flows = useMemo(() => flowIds(workbook), [workbook]);
  const impacts = useMemo(() => impactIds(workbook), [workbook]);
  const years = useMemo(
    () => (workbook.periods ?? []).map((r) => Number(r.year)).filter(Number.isFinite),
    [workbook],
  );
  const baseYear = years.length ? Math.min(...years) : 2025;
  const currency = modelCurrency(workbook);

  const isImpact = (target: string) => impacts.includes(target);
  const unitOf = (target: string) => (isImpact(target) ? impactUnit(workbook, target) : flowUnit(workbook, target));
  const targetOptions = [
    ...flows.map((c) => ({ value: c, label: `${c} · flow` })),
    ...impacts.map((i) => ({ value: i, label: `${i} · impact (ETS)` })),
  ];

  // ── Markets (one row per market on the `markets` sheet) ──────────────────────
  const markets = (workbook.markets ?? []) as Row[];
  const setMarkets = (rows: Row[]) => setWorkbook({ ...workbook, markets: rows });
  const patchMarket = (i: number, p: Partial<Row>) =>
    setMarkets(markets.map((r, j) => (j === i ? ({ ...r, ...p } as Row) : r)));
  const addMarket = () =>
    setMarkets([
      ...markets,
      { market_id: genId("mkt"), target: flows[0] ?? impacts[0] ?? "", company: "all" },
    ]);
  const delMarket = (i: number) => setMarkets(markets.filter((_, j) => j !== i));

  // ── Carbon price (impact_prices) ────────────────────────────────────────────
  const cprices = useMemo(() => gatherPrices(workbook, years), [workbook, years]);
  const commitPrices = (rows: CPrice[]) =>
    setWorkbook({ ...workbook, impact_prices: scatterPrices(rows, years) });
  const patchPrice = (i: number, p: Partial<CPrice>) =>
    commitPrices(cprices.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const addPrice = () => commitPrices([...cprices, { impact: impacts[0] ?? "", value: 0 }]);
  const delPrice = (i: number) => commitPrices(cprices.filter((_, j) => j !== i));

  const cell: React.CSSProperties = { padding: "2px 4px" };
  const numStyle = { width: 84 } as const;

  return (
    <div className="body-row">
      <main className="main-area" style={{ overflow: "auto", padding: "16px 22px", maxWidth: 1040 }}>
        <div className="eyebrow">market &amp; policy</div>
        <h2 className="view-title">Market &amp; Policy</h2>
        <p className="view-lead">
          The institutional layer: where flows are bought/sold (pools), emissions are traded (ETS),
          and carbon is priced — each scoped to a region/company/node, so policy can differ by place.
          Emission caps live in Optimisation.
        </p>

        {/* Markets */}
        <section style={{ marginBottom: 24 }}>
          <h3 className="section-title" style={{ marginBottom: 2 }}>Markets &amp; ETS</h3>
          <p className="muted" style={{ fontSize: ".74rem", margin: "0 0 8px" }}>
            A <b>flow</b> target is a supply/offtake pool (buy at <i>price</i>, sell at <i>sell</i>).
            An <b>impact</b> target is an ETS: a free <i>allocation</i> per year, with the deficit
            bought / surplus sold at <i>price</i>. Allocation 0 + a price = a scoped carbon charge.
            Prices are in {currency} per target unit.
          </p>
          <button className="ghost" style={{ marginBottom: 8 }} onClick={addMarket}>＋ add market</button>
          {markets.length === 0 ? (
            <p className="muted" style={{ fontSize: ".78rem" }}>No markets yet — ＋ add one.</p>
          ) : (
            <table className="grid" style={{ width: "100%", fontSize: ".76rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                  <th>target</th>
                  <th>scope</th>
                  <th>buy price</th>
                  <th>sell price</th>
                  <th>max buy</th>
                  <th>max sell</th>
                  <th>allocation (ETS)</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {markets.map((r, i) => {
                  const target = s(r.target);
                  const ets = isImpact(target);
                  const u = unitOf(target);
                  return (
                    <tr key={i}>
                      <td style={{ ...cell, minWidth: 150 }}>
                        <SearchSelect value={target} onChange={(v) => patchMarket(i, { target: v })} options={targetOptions} />
                      </td>
                      <td style={{ ...cell, minWidth: 130 }}>
                        <SearchSelect value={s(r.company) || "all"} onChange={(v) => patchMarket(i, { company: v })} options={scopes} />
                      </td>
                      <td style={cell} title={`${currency}/${u}`}>
                        <input type="number" style={numStyle} value={s(r.price)} onChange={(e) => patchMarket(i, { price: numOrNull(e.target.value) })} />
                      </td>
                      <td style={cell} title={`${currency}/${u}`}>
                        <input type="number" style={numStyle} value={s(r.sell_price)} onChange={(e) => patchMarket(i, { sell_price: numOrNull(e.target.value) })} />
                      </td>
                      <td style={cell} title={`${u}/yr`}>
                        <input type="number" style={numStyle} value={s(r.max_buy)} onChange={(e) => patchMarket(i, { max_buy: numOrNull(e.target.value) })} />
                      </td>
                      <td style={cell} title={`${u}/yr`}>
                        <input type="number" style={numStyle} value={s(r.max_sell)} onChange={(e) => patchMarket(i, { max_sell: numOrNull(e.target.value) })} />
                      </td>
                      <td style={cell} title={ets ? `${u}/yr free allowance` : "ETS only"}>
                        <input type="number" style={numStyle} disabled={!ets} value={ets ? s(r.allocation) : ""}
                          onChange={(e) => patchMarket(i, { allocation: numOrNull(e.target.value) })} />
                      </td>
                      <td><button className="ghost" title="remove" onClick={() => delMarket(i)}>✕</button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>

        {/* Carbon price */}
        <section style={{ marginBottom: 24 }}>
          <h3 className="section-title" style={{ marginBottom: 2 }}>Carbon price (tax on all emissions)</h3>
          <p className="muted" style={{ fontSize: ".74rem", margin: "0 0 8px" }}>
            A blanket price on every unit of an impact (a carbon/pollutant tax), applied model-wide —
            distinct from an ETS, which only charges the deficit against an allocation. For
            region-specific pricing use an ETS market above with allocation 0.
          </p>
          <button className="ghost" style={{ marginBottom: 8 }} onClick={addPrice} disabled={!impacts.length}>
            ＋ add carbon price
          </button>
          {cprices.length === 0 ? (
            <p className="muted" style={{ fontSize: ".78rem" }}>No carbon price — ＋ add one (or use a scoped ETS above).</p>
          ) : (
            <table className="grid" style={{ width: "100%", maxWidth: 560, fontSize: ".76rem" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                  <th>impact</th>
                  <th>price</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {cprices.map((r, i) => (
                  <tr key={i}>
                    <td style={{ ...cell, minWidth: 150 }}>
                      <SearchSelect value={r.impact} onChange={(v) => patchPrice(i, { impact: v })}
                        options={impacts.map((o) => ({ value: o }))} />
                    </td>
                    <td style={cell}>
                      <TemporalValue
                        value={r.value}
                        onChange={(v) => patchPrice(i, { value: v ?? 0 })}
                        label={`carbon price · ${r.impact}`}
                        unit={`${currency}/${impactUnit(workbook, r.impact)}`}
                        perYear={false}
                        baseYear={baseYear}
                        periods={years}
                      />
                    </td>
                    <td><button className="ghost" title="remove" onClick={() => delPrice(i)}>✕</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </main>
    </div>
  );
}
