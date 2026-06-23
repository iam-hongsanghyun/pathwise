# Roadmap / TODO: making `simulate` a *proper* LCA

> Status: **roadmap** (not yet built). The `simulate` backend (shipped in #111–#116)
> gives a cradle-to-gate **CO₂ inventory + what-if simulator**. This file captures
> what is still needed to make it a proper, ISO 14040/44-style multi-impact LCA
> (LCI → LCIA → interpretation), and the decisions to settle before building.

## Where we are
A credible **single-impact (CO₂), boundary-limited** inventory: emissions by
value-chain stage, per functional unit, with cost/carbon; A-vs-B variant comparison;
carbon-price sweep; cap compliance; recycling via `lag_years`; a use phase that *can*
be authored. The engine is already multi-impact and tracks flows in commodity-scoped
units. That is the **LCI (inventory)** layer — the LCIA and interpretation layers are
thin or missing.

## Key decision — multi-gas GWP: pre-characterised vs runtime characterisation
Today an `io` row with `role="impact"` gives **one factor per (technology, impact)** —
i.e. the inventory of a flow per unit throughput.

- **Pre-characterised** (author the factor already as `CO2e`): a single `CO2e` impact
  is *sufficient for a GWP-only MVP*, but bakes in the GWP horizon at data-entry, gives
  no per-gas transparency, and does **not** generalise — a flow like SO₂ feeds *both*
  acidification and PM with different factors, so one baked number per (tech, category)
  duplicates data and breaks for multi-category flows.
- **Runtime characterisation (recommended):** keep `io` factors as the **inventory**,
  modelling each gas/flow as its own impact (`CO2`, `CH4`, `N2O`, …), then add a thin
  **characterisation table** (flow × category → factor) that aggregates to GWP / AP /
  EP / … . For GWP alone the table is ~3 numbers (CO₂=1, CH₄≈27, N₂O≈273). Reuses the
  existing per-impact engine; the only new data is the CF table.

→ **The `io` impact factor IS the LCI; the missing piece is the multiply-and-sum
characterisation step on top.**

## Roadmap (priority order)

1. **LCIA characterisation (biggest gap).** ✅ **ENGINE SHIPPED** — a `characterisation`
   sheet `(flow_impact_id, category_id, factor)` makes each impact **category** (e.g. GWP)
   a *derived impact*: the build links `emit[category] = Σ_flow CF·emit[flow]`, so the
   category rides in `ctx.emit` and pricing / caps / ETS / the simulate inventory all treat
   it like any other impact (verified: `tests/backends/test_characterisation.py` — GWP in
   the inventory, a priced GWP in the objective, a GWP cap). **Still to do:** ship a full
   method's factor set (EF 3.1 / ReCiPe — see #2's importer) and author the foreground
   elementary-flow `io` rows the method needs. Hook: `impacts` + `io` impact rows +
   `characterisation`.
2. **Background / upstream factors for purchased flows.** Cradle-to-gate factors for
   everything bought (grid electricity, fuels, ore, chemicals, transport) via the
   existing `commodity_impacts` mechanism, sourced from an LCI database — otherwise the
   inventory is truncated at the model boundary.
3. **Allocation rules for co-products & recycling.** Declare cut-off vs
   system-expansion / avoided-burden (and mass vs economic). Changes the recycling-loop
   and co-product numbers, so decide alongside #1/#2.
4. **Use & end-of-life first-class + phase rollup.** Promote use/EoL from
   "author-it-yourself" to standard, data-backed processes, and add the
   materials · manufacturing · use · end-of-life **phase** rollup (the deferred `phase`
   tag, proposal §4) for cradle-to-grave by default.
5. **Functional-unit rigor.** Explicit FU + reference flows (e.g. "1 vehicle, 200,000 km
   over 12 yr") instead of "largest demand".
6. **Uncertainty & data quality.** Monte-Carlo over factor distributions + a
   pedigree/data-quality flag → report ranges, not point values (reuse the portfolio
   backend's MC machinery).
7. **Interpretation outputs + validation.** Contribution/hotspot analysis by flow and by
   phase (beyond by-stage), sensitivity, an exportable LCA report (goal & scope / LCI /
   LCIA / interpretation / limitations), and calibration against EPDs / published LCAs.

## Decisions needed before building #1–#3
- **LCIA method** to target first: IPCC GWP (CO₂e only) · EF 3.1 · ReCiPe.
- **Background dataset** that is licensable to us: ecoinvent (standard, licensed) ·
  EXIOBASE / US EPA / others (open).
- **Allocation** default: cut-off vs system expansion (avoided burden).

## Recommended first step
#1 (characterisation: multi-gas CO₂e + one method) **with** #2 (background factors for
purchased flows) — mutually reinforcing, both reuse existing hooks (`impacts`,
`commodity_impacts`, `io`), and together they convert this from a carbon model into an
LCA. Settle the three decisions above first.
