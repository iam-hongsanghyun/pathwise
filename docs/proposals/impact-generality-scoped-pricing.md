# Proposal: impact-agnostic everywhere + scoped (per machine/group) impact pricing

> Status: **plan** (no code yet). Two related corrections to keep pathwise honest as a
> *general multi-impact* tool:
> 1. **Never hardcode `"CO2"`** — every impact (CO₂, CH₄, SO₂, NOₓ, GWP, AP, …) is a
>    user-defined `(impact_id, unit)`; nothing in the engine may assume one exists or
>    privilege it, or other impacts can't be guaranteed to flow through.
> 2. **Impact price is policy → it must be scopeable** by machine / group / sector
>    (and region), not a single global trajectory — so EU vs US vs Korea, or steel vs
>    power, can carry different carbon (or pollutant) prices.

## How impacts work today (the mental model — confirmed)
Impacts are generic. An emission attaches to a **stream / activity** in four places, all
per-impact, none CO₂-specific:
- a technology's `io` `role=impact` row (per throughput) and the legacy `tech_impacts`,
- `commodity_impacts` — the cradle burden a *purchased commodity* (a stream) carries,
- `freight_*` on a `connections` edge (the spatial-transport layer).
A price is just `impact_prices(impact_id, year, price)` → `Impact.price_by_year` →
`prob.impacts[i].price(t)`. So "CO₂" is one user-defined impact with a unit and a price;
the engine should treat **all** impacts identically. The two gaps below break that.

## Audit — where `"CO2"` is hardcoded (grep over `src/`)
**A. Real defect — excludes other impacts (must fix):**
- `core/build.py` `_objective` — freight CO₂ priced at `prob.impacts["CO2"]` only.
- `core/extract.py` `_period_costs` — same freight CO₂ hardcode.
  → freight today carries a single `freight_co2`; a model's SO₂/CH₄/… freight is dropped.

**B. Soft fallbacks — single-impact ops that default to `"CO2"` when unset (tidy up):**
- `backends/frontier_backend.py` (`fr.get("impact") or "CO2"`),
- `backends/macc_backend.py` (`_capped_impact` → `"CO2"`),
- `backends/simulation_backend.py` (`_primary_impact`; sweep default),
- `backends/overrides.py` (`set_carbon_price` default),
- `core/extract.py` macc default; `data/valuechain.py` coupling-signal default.
  These accept any impact but assume CO₂ when omitted. Fix: default to the **first
  defined / first capped impact**, never a literal `"CO2"`, so a no-CO₂ model still runs.

**C. Data (fine):** `data/lcia.py` GWP100/EF tables name CO₂/CH₄/N₂O as flows — that's the
factor library, not an engine assumption. Leave as-is.

## Part 1 — Generalize freight emissions (per-impact)
Replace the single `freight_co2` column + the `impacts["CO2"]` pricing with a general
per-edge, per-impact freight emission, mirroring the existing `commodity_impacts` /
`tech_impacts` shape:

- **Schema:** a long sheet `connection_impacts(from_node, to_node, commodity_id,
  impact_id, factor)` (+ flat `edge_impacts`). `Edge.co2: float` → `Edge.emissions:
  dict[impact_id, float]`. Keep `freight_cost` + `freight_energy` as columns.
- **Objective / period cost:** freight emission term becomes
  `Σ_e Σ_i price[i,t]·emissions_e[i]·flow[e,t]` over **all** priced impacts — no `"CO2"`.
- **Report:** `outputs.transport` lists freight cost + energy + **per-impact** emissions.
- Sets up the deferred step (fold freight emissions into `ctx.emit` so they're
  characterised + cappable) — they're already per-impact then.
- Migration: read a legacy `freight_co2` column as `emissions={<the model's GHG impact>}`
  only if such an impact id is *passed in*, never assumed — or just drop it (the feature
  shipped one commit ago; no external data depends on it).

## Part 2 — Scoped impact pricing (the big change)
Make `impact_prices` carry an optional scope, exactly like `impact_caps` already do
(`company` + `in_scope`), so price varies by machine / facility / company / group /
sector / region. Default scope `"all"` ⇒ today's global behaviour (back-compatible).

- **Schema:** `impact_prices(company?, impact_id, year, price)` (+ a wide
  `impact_prices_t`). Absent `company` ⇒ `"all"`.
- **Data model:** `Problem.impact_price_by_scope: dict[(scope, impact), dict[year, price]]`
  (mirrors `impact_caps`). `Impact.price_by_year` stays as the `"all"` fallback.
- **Resolution rule (most-specific wins):** for process `p`, impact `i`, year `t`, the
  applied price is the price of the **most specific** scope `s` with `p.in_scope(s)` that
  has a price for `(s, i)`; fall back through group → company → `"all"` → 0. (Pricing does
  *not* pool the way absolute caps sum — a price is applied per process, not aggregated.)
- **Engine:** the objective's impact term changes from a per-`(impact, period)` price
  DataArray to per-`(process, impact, period)` (resolve each process's scoped price), then
  `Σ price[p,i,t]·emit[p,i,t]`. `extract._period_costs` mirrors it.
- **Consistency:** ETS impact *markets* and `impact_caps` are already scoped; this brings
  pricing in line. (ETS-vs-price interaction unchanged: an impact is either ETS-traded or
  priced, per the existing `ets_impacts` split.)
- **Frontend:** the targets/policy editor lets a price row pick a scope (reusing the
  scope selector already used for caps).

This is what makes the transport "policy 풍선효과" real — a regional/sector carbon-price
patchwork that reshuffles sourcing and routing is now expressible, and the breakeven /
shadow-price outputs become the per-scope policy answer.

## Build order & risk
1. **Part 1 (freight per-impact)** — contained; corrects a one-commit-old feature. ~½ day.
2. **Part B (de-CO₂ the fallbacks)** — mechanical; default to first defined/capped impact.
   Low risk, do alongside Part 1.
3. **Part 2 (scoped pricing)** — touches the core objective + `_period_costs` + schema +
   assemble + frontend. The math is a coefficient-array reshape (impact→process×impact),
   well-trodden in this codebase. Needs regression tests: global price unchanged (back-
   compat), a per-group price binds only its group, most-specific-scope wins. ~2–3 days.

## Verification
- No `"CO2"` literal remains in `src/` outside `data/lcia.py` (a grep gate in CI/review).
- A model whose only impact is `SOx` prices + caps + frontiers it with zero `"CO2"` mention.
- Freight emissions reported and priced for **every** impact, not just CO₂.
- Scoped pricing: a steel-sector CO₂ price of X and a power-sector price of Y bind their
  own processes; `"all"` is the fallback; global-only models are bit-for-bit unchanged.

## Open questions
- **Scope key**: reuse `company` + `in_scope` (machine/company/group/sector/region all via
  the node ancestry) — confirm that's the granularity (it matches caps).
- **Most-specific-wins vs additive**: a price is single-valued per process (most-specific
  wins). Confirm no use-case wants *stacked* prices (e.g. national + regional surcharge);
  if so, that's an explicit `additive` flag, not the default.
