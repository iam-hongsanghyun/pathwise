# Roadmap / TODO: making `simulate` a *proper* LCA

> Status: **partly shipped.** The `simulate` backend (#111–#116) gave a cradle-to-gate
> **CO₂ inventory + what-if simulator**; the LCIA + impact-optimisation build on top of
> it (the 5-phase plan below) has now landed the **characterisation engine, impact-aware
> optimisation (ε-constraint caps · direct impact objective · cost-vs-impact frontier),
> lifecycle-phase rollup, Monte-Carlo factor uncertainty, an open-data LCIA/background
> importer, and the full frontend** for all of it. This file tracks both what shipped and
> what is still needed for an ISO 14040/44-grade multi-impact LCA.

## Shipped in the LCIA + impact-optimisation build
- **Characterisation engine** — a `characterisation` sheet `(flow_impact_id, category_id,
  factor)` makes each impact **category** (GWP, AP, …) a *derived impact*: the build links
  `emit[category] = Σ_flow CF·emit[flow]`, so categories ride in `ctx.emit` and pricing /
  caps / ETS / the simulate inventory treat them like any other impact.
- **Impact-aware optimisation (3 modes)** — ε-constraint (cap a category, minimise cost);
  **direct impact objective** (`objective_impact` + `impact_weight`/`cost_weight` blend in
  `_objective`); **cost-vs-impact Pareto frontier** (the new `frontier` backend sweeps a cap
  and re-runs least-cost per point → `outputs.frontier`).
- **LCA rigor** — lifecycle-**phase** rollup (optional `phase` node tag → materials ·
  manufacturing · use · end-of-life) and **Monte-Carlo factor uncertainty** (`simulate.
  uncertainty = {sigma, n, seed}` → per-impact P5–P95) in the simulate inventory.
- **Open-data importer** — `data/lcia.py`: AR6 GWP100 CFs, EF-3.1-style method scaffold,
  an open background-factor seed, and `apply_lcia` / CSV loaders.
- **Frontend** — `FrontierSetup` cockpit + `FrontierResult` chart, a "Minimise impact"
  objective in `TargetsTabView`, `by_phase`/`uncertainty` cards in `LcaResult`, an
  uncertainty toggle in `SimulateSetup`, and the `frontier` backend in the method picker.

> **Frontier on green_steel — fixed.** An earlier note here blamed a flat green_steel
> frontier on "background/traded CO₂ outside the constrained inventory." That diagnosis was
> wrong (it read a stripped value-chain view from the `/model` endpoint). The real, merged
> green_steel model **does** carry an `impacts` sheet, 11 foreground `io` CO₂ factors, and
> pre-existing **soft** impact caps. The flat curve was a **cap-injection bug**, now fixed:
> 1. The `frontier` backend *appended* its hard ε-cap to the model's caps; under system-scope
>    pooling that (a) **summed** with the model's own per-year caps and (b) — because one
>    pre-existing cap was soft — got **softened** too (penalty cheaper than abating), so every
>    point collapsed to the baseline. Fix: the backend now **replaces** the swept impact's
>    caps with its single hard ε-cap (keeping other impacts' caps).
> 2. Assemble's system-scope pooling computed `any_soft` / `pen_max` **globally**, so one soft
>    cap on any impact softened *every* impact's pooled cap. Fix: pool soft/penalty **per
>    impact**.
>
> Post-fix green_steel produces a proper monotone frontier (tighter CO₂ cap ⇒ lower emissions,
> higher cost; a cap below the achievable floor drives total under-production via demand slack
> — the cost-blowup endpoint, since demand is soft in this model). Regression tests:
> `test_frontier_binds_despite_preexisting_soft_cap` and
> `test_system_scope_pools_soft_per_impact_not_globally`.

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

1. **LCIA characterisation (biggest gap).** ✅ **SHIPPED** (engine + importer scaffold +
   frontend). A `characterisation` sheet `(flow_impact_id, category_id, factor)` makes each
   category a *derived impact* (`emit[category] = Σ_flow CF·emit[flow]`); pricing / caps /
   ETS / the simulate inventory all treat it like any other impact (verified:
   `tests/backends/test_characterisation.py`). **Still to do:** ship a *complete* method
   factor set (EF 3.1 / ReCiPe — `data/lcia.py` has the AR6 GWP100 table + an EF-3.1
   scaffold) and author the foreground elementary-flow `io` rows the method needs.
2. **Background / upstream factors for purchased flows.** ⚠️ **PARTIAL** — the
   `commodity_impacts` mechanism + an open background **seed** exist (`data/lcia.py::
   BACKGROUND_SEED`, `load_background_csv`), but the bundled example models don't yet carry
   a real background dataset, so the inventory is truncated at the **upstream** boundary
   (e.g. grid electricity, ore, transport bought from outside the model carry no impact).
   This is a *completeness* gap, distinct from the cap-injection bug above — green_steel's
   *foreground* CO₂ is modelled and now caps correctly. **Still to do:** import a full open
   dataset (USEEIO / EXIOBASE / IEA) into the example models.
3. **Allocation rules for co-products & recycling.** Default chosen = **cut-off**; declare
   system-expansion / avoided-burden (and mass vs economic) as an option. Changes the
   recycling-loop and co-product numbers, so decide alongside #2.
4. **Use & end-of-life first-class + phase rollup.** ✅ **phase rollup SHIPPED** (optional
   `phase` node tag → materials · manufacturing · use · end-of-life, in the simulate
   inventory + `LcaResult`). **Still to do:** promote use/EoL from "author-it-yourself" to
   standard, data-backed processes.
5. **Functional-unit rigor.** Explicit FU + reference flows (e.g. "1 vehicle, 200,000 km
   over 12 yr") instead of "largest demand".
6. **Uncertainty & data quality.** ✅ **Monte-Carlo SHIPPED** (`simulate.uncertainty =
   {sigma, n, seed}` → per-impact P5–P95, reusing log-normal factor draws). **Still to do:**
   a pedigree / data-quality flag and per-factor (not just global-σ) distributions.
7. **Interpretation outputs + validation.** Contribution/hotspot analysis by flow and by
   phase (beyond by-stage), sensitivity, an exportable LCA report (goal & scope / LCI /
   LCIA / interpretation / limitations), and calibration against EPDs / published LCAs.

## Decisions (settled with the user)
- **LCIA method:** **EF 3.1** first (EU PEF reference, JRC-published CFs), method-agnostic
  engine so ReCiPe is swappable. AR6 GWP100 ships as the seed table.
- **Background dataset:** an **open** one (USEEIO / EXIOBASE / IEA energy) via an importer —
  no licensed DB (ecoinvent ruled out).
- **Allocation:** default **cut-off**, with system-expansion / avoided-burden as an option.

## Next step
**#2 — load a real open background dataset into the example models, and author a full
method's CFs.** The engine, the three optimisation modes, the frontend and the importer
scaffold are all in place and verified (impact caps and the frontier now bind correctly on
green_steel's foreground CO₂). The remaining gap is *coverage*: bring upstream/background
factors and a complete EF-3.1 CF set into the bundled models so the inventory spans
cradle-to-gate and multiple impact categories, not just modelled foreground CO₂.
