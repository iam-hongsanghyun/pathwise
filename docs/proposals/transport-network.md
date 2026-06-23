# Proposal: spatial transport — costed, physical, multi-modal stream movement

> Status: **plan** (build after the LCIA work, which is shipped). Adds *physical
> transport* to stream movement between locations — shipping / flight / road / rail /
> pipeline — each with its own cost, capacity and emission factor. Not everywhere:
> transport is opt-in per connection; an untagged connection stays free (as today).

## The one decision that keeps this alive: annual resolution
No sub-annual time. No ship scheduling, port queueing, dwell time, weather, or
arrival timing. The moment we track *when* a ship arrives and *how long* it waits we
have left optimisation for discrete-event simulation / vehicle routing, and the model
stops being calibratable. Hold this line: **everything is an annual average.** A
transport leg's "speed" enters only as an annual-throughput ceiling, never as a clock.
The temporal gap (days in transit) is real but **ignored for now** — and when we do want
it, the edge model already carries `lag_years` (integer-year delivery lag, see
`core/build.py::_flow_balance`), so a coarse lag is a data field, not new machinery.

## What this actually is (a known object)
Stripped of shipping vocabulary it is a **min-cost multi-commodity flow** problem on a
transport network, optionally with an integer **fleet-assignment** layer (MILP). It is
the same object PyPSA solves for power — buses/lines/generators/loads — which is why it
is a *perturbation of pathwise, not a rewrite*:

| transport concept | pathwise primitive (today) |
|---|---|
| port / region | a value-chain **node** (`nodes`) |
| shipping lane / route | a **connection / edge** (`connections`, `Edge`) |
| regional source (methanol US Gulf / EU / China) | a **market** buy at a node (`markets`) |
| regional demand (Korea / Taiwan / EU) | **demand** at a node (`demand`) |
| in-transit delay | edge `lag_years` (already supported; 0 for now) |
| **freight cost on a leg** | **— missing —** |
| **per-leg emissions** | **— missing (as an edge attribute) —** |
| **fleet as a finite, allocatable capacity** | **— missing —** |

## Why it's a perturbation: what already exists vs. what's new
Edges are already first-class. `Edge` (`core/entities.py`) has `from_process`,
`to_process`, `commodity_id`, `max_flow`/`min_flow` (+ per-year), the flow is a decision
variable `flow[edge, t]`, balance nets in/out-flow, and lagged delivery is implemented
(`flow[edge, t-lag]`). Tests already cover edge bounds / availability / temporal flow
bounds. **What edges lack: a cost and an emission factor — they are bounded but FREE
today** (no flow term in `_objective`). That free flow is exactly the "commodities
teleport" the spatial model removes.

So Layer 1 is: **give a transported edge a cost + an emission factor + a finite
capacity that a fleet allocates** — and let the existing objective / impact / LCIA
machinery carry it the rest of the way.

## Two ways to model a leg — recommendation: **transport-as-process**
There are two clean encodings; pick one and stay on it.

- **(A) Edge attributes.** Add `cost`, `mode`, `emission_factor` to `Edge`; add a
  freight term to `_objective` and an edge-emission term to `_impacts`. Lightest schema,
  but needs new objective + impact code paths and a new fleet object.
- **(B) Transport-as-process (recommended).** A leg *is* a technology/process that
  consumes `methanol@USGulf` and produces `methanol@Korea`, with:
  - `opex` = freight $/tonne (already in the objective),
  - `io` `role=impact` rows = the leg's CO₂/CH₄/NOₓ/SO₂/PM (already characterised into
    GWP/AP/EP/PM by the LCIA layer just shipped, and already split foreground/background
    by `lca.by_origin`),
  - `capacity` = the leg's **annual throughput ceiling** — which is exactly the
    annual-capacity-asset idea: a ship class with round-trip `N` days does `≈365/N`
    voyages/yr × cargo, so you author that product as the capacity and never model a
    voyage. The existing capacity / availability / `max_cf` machinery then bounds it.
  - fleet upgrades / new ships = `transitions` (already supported).

  (B) **reuses essentially everything** — objective, capacity, impacts, the LCIA
  fg/bg split, transitions — and makes "ship as annual-capacity asset" literal. The only
  genuinely new concept is *commodity-at-a-place* (a methanol-at-Korea commodity distinct
  from methanol-at-USGulf), which is just naming, plus the fleet-allocation constraint
  below if a finite fleet is shared across routes.

## Layer 1 — the LP (pathwise style), transport-as-process

```
Sets
  N   nodes (ports / regions)
  R   commodities, place-scoped where transported: r@n  (e.g. methanol@korea)
  L   transport legs  (process p with mode m ∈ {ship,air,road,rail,pipe})
  T   years
Parameters
  freight[p,t]    $/tonne on leg p           (process opex)
  ef[p,i]         t-flow i / tonne on leg p   (io role=impact → LCIA categories)
  cap[p,t]        annual throughput ceiling   (= 365/N · cargo · n_ships ; process capacity)
  price[r@n,t]    landed source price         (market buy at node n)
  demand[r@n,t]   regional demand             (demand at node n)
  fleet[c]        ships of class c available  (optional MILP layer)
  share[c,p]      cap contributed by one class-c ship on leg p
Variables
  move[p,t] ≥ 0   tonnes routed on leg p in t   (= the leg process throughput)
  buy / sell / produce / consume               (existing)
  a[c,p] ∈ ℤ≥0    ships of class c assigned to leg p   (optional MILP)
Objective   min  Σ  freight[p,t]·move[p,t]  +  Σ price·buy  +  carbon/policy on ef·move  + …
Constraints
  flow balance at each r@n     (existing _flow_balance, now place-scoped)
  move[p,t] ≤ cap[p,t]         (existing capacity bound)             — or, with a fleet:
  move[p,t] ≤ Σ_c a[c,p]·share[c,p]      and   Σ_p a[c,p] ≤ fleet[c]  (capacitated assignment)
  emissions ef·move enter ctx.emit  → priced (carbon), capped (policy), characterised (LCIA)
```

The carbon/policy term is the **whole point**: each leg's emissions ride the existing
`impact_prices` / `impact_caps` / characterisation, so an EU-only vs global vs no carbon
price is a scenario over those sheets — and the answer (which source lands cheapest,
how the fleet reallocates) falls straight out.

## Build order
1. **Layer 1a — costed legs (MVP, ~2–3 wk).** Transport-as-process with `opex` freight +
   `io` emissions + `capacity` ceiling. ~5–10 routes, 3–4 ship classes, methanol/ammonia/
   LNG, sources US Gulf / EU / China–ME, sinks Korea / Taiwan / EU. Single year, static.
   Delivers the methanol-from-EU-vs-US-vs-China-under-policy comparison directly. Mostly
   *data* + place-scoped commodities; little engine change.
2. **Layer 1b — finite fleet assignment (MILP).** The `a[c,p]` integer layer when a shared
   fleet of classes A/B/C must be split across routes (the "세 척을 어떻게 배정" question).
   New constraint family; reuses the linopy backend.
3. **Layer 1c — modes + per-leg policy.** `mode ∈ {ship,air,road,rail,pipe}` as a tag
   driving distance→annual-voyages, fuel and emission factors; per-leg carbon (a leg in
   EU waters vs not). Route-disruption scenarios (e.g. Hormuz → Cape reroute) become a
   capacity/`lag`/distance edit, which the spatial model can finally see.
4. **Layer 2 — carrier-facing optimiser (separate scoping).** Whose ledger flips: Layer 1
   serves the *importer/trader* (maritime transport = upstream **Scope 3**, GHG Protocol
   Cat. 4 — already what `lca.by_origin` background captures); Layer 2 serves the *carrier*
   (the identical emissions are **Scope 1** / route compliance) and adds competition →
   equilibrium (Nash–Cournot). Genuinely harder, OilSim-adjacent — **do not build first.**

## Output framing (same lesson as MACC)
A transport-cost optimisation is only as credible as its freight + carbon coefficients,
which are noisy. Don't sell point estimates ("methanol from the US is $X cheaper"). Sell
**direction + breakeven**: which carbon price flips the sourcing decision, the **shadow
price** on the carbon/capacity constraint, how large a policy shift reroutes a fleet. The
frontier backend (cost-vs-impact) and the dual/shadow-price extraction already fit this.

## Data — do NOT gate on AIS
Assemble route / ship-class parameters offline: Clarksons-style route snapshots, bilateral
trade flows, representative ship classes, annual averages. Real-time AIS is a v2 fantasy
feature, never a dependency — if the model needs live AIS to run, it won't survive contact
with reality.

## Why now
The policy layer (the model's driver) is live and messy: EU ETS already covers shipping
and FuelEU Maritime is in force, while the IMO Net-Zero Framework's adoption vote slipped
~a year (reconvening ~fall 2026; earliest entry ~March 2028 at ~USD 100/t CO₂e). EU-only
vs global vs nothing **is** the scenario axis, and regional-carbon-price route-reshuffling
(the 정책 풍선효과) is a real, unanswered question — exactly what a scenario optimiser is for.

## Open questions to settle before Layer 1
- **Place-scoped commodities**: explicit `r@node` ids, or a `(commodity, node)` key the
  engine derives? (Naming affects the whole `connections`/`io` authoring surface.)
- **Allocation of a leg's emissions** for the importer's footprint: per-tonne attribution
  is the cut-off default already chosen for LCIA — confirm it carries to transport.
- **Fleet sharing**: is the finite-fleet MILP (1b) in the MVP, or do v1 legs just carry an
  exogenous annual capacity (1a) and the fleet split come later?
