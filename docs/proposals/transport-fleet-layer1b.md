# Proposal: Layer 1b — fleet table + finite-fleet route assignment (MILP)

> Status: **design — confirm before code.** Extends the shipped Layer 1a
> ([transport-network.md](transport-network.md)) from *one machine per route* to
> *a shared pool of ship cohorts allocated across routes*. This is where the
> "fleet as a table, not a box per ship" idea and the per-route min/max count
> live.
>
> **Two decisions locked (owner, 2026-06-24):**
> 1. **Integer (MILP) fleet counts from the start** — `units[archetype, route,
>    year] ∈ ℤ≥0`, not continuous "ship-years". (Tradeoff accepted: slower
>    solves, MILP early. We keep the LP relaxation available as a warm-start /
>    infeasibility diagnostic, but the reported answer is integer.)
> 2. **Design doc before any engine change** — this file is the gate. No code
>    until it's confirmed.

---

## 0. Where Layer 1a left us (the baseline this extends)

The shipped `transport_methanol.sqlite` models **each route as its own machine**:

| machine | baseline_technology | capacity (t/yr) | opex ($/t) | io |
|---|---|---|---|---|
| `ship_us_kr` | `Ship_US_KR` | 2 000 000 | 60 | `methanol_us → methanol_kr`, CO₂ 0.30 |
| `ship_eu_kr` | `Ship_EU_KR` | 2 000 000 | 75 | `methanol_eu → methanol_kr`, CO₂ 0.38 |
| `ship_cn_kr` | `Ship_CN_KR` | 2 000 000 | 20 | `methanol_cn → methanol_kr`, CO₂ 0.08 |

A transport leg *is* a technology: `opex` = freight $/t, an `io` `role=impact`
row = the leg's emission factor, `capacity` = annual throughput ceiling. The
optimiser buys from the three markets (`methanol_us` 350, `methanol_eu` 520,
`methanol_cn` 360) and routes via whichever leg is cheapest once freight +
carbon is added. This already reuses objective / capacity / impacts / LCIA
wholesale — **no engine change.**

**What 1a cannot express, and 1b must:**
- A ship is welded to one route. There is no *shared fleet* that reallocates
  across routes when policy shifts (the whole point of the 풍선효과).
- `capacity` is an exogenous constant (2 M), not derived from *how many ships of
  what class* serve the route.
- "Buy 3 ships of class A, decide how to split them across US/EU/CN routes" is
  inexpressible. That is the carrier's actual decision.

1b separates **ship class (cohort)** from **route assignment**.

---

## 1. Decision A — place-scoped commodity naming

**Question (from the 1a open list):** explicit `r@node` ids, or a derived
`(commodity, node)` key the engine computes?

**Recommendation: keep explicit place-scoped commodity ids** (`methanol_us`,
`methanol_kr` — what 1a already ships), and add a **naming convention +
authoring helper**, not an engine key.

- **Engine stays generic.** A place-scoped commodity is just a commodity; the
  engine never learns about "places". This matches the standing rule that
  pathwise is sector-agnostic and the Python core is a thin generic reader.
- **Convention:** canonical id is `base@node` (e.g. `methanol@korea`); a thin
  helper in `data/` derives/splits it so the **UI** can present a `(commodity,
  place)` pair while the stored id stays a flat string. Underscore suffixes
  (`methanol_kr`) remain valid aliases for hand-authored data.
- **Cost:** an N-source × M-sink network needs N+M place-scoped commodities and
  N×M legs. That's data volume, not engine complexity, and it's exactly what the
  fleet/route tables below are for. A derived `(commodity, node)` key would touch
  the entire `io` / `connections` / market / demand authoring surface and the
  engine's commodity indexing — higher risk for no engine benefit.

**Confirm:** are we happy formalising `base@node` as the canonical form (with
`base_node` underscore as an accepted alias), engine-agnostic? If a future sink
needs the *same* physical commodity from multiple origins tracked separately for
footprint, this convention already handles it.

---

## 2. Decision B — the fleet-table data model

Three tables. Two are new; all reuse existing column idioms.

### 2a. Cohort = a row in a fleet table (`archetype × vintage`)

A **cohort** is the optimiser-side unit (never an individual ship). It is an
**archetype** (ship class: capacity, fuel, energy/km, speed, capex, opex,
eligible measures) crossed with a **vintage** (build year, via
`available_from`). "IFO380-built-2015" and "ammonia-built-2030" are two rows
differing only in `available_from` + fuel — set-based, LP/MILP-friendly,
exactly the existing `technologies` + `transitions` idiom.

Reuse, don't invent:
- An **archetype maps to a `technology`** (`technologies`: lifespan, capex,
  opex; `io`: fuel input + cargo in/out + emission factor). Vintage = the
  `available_from`/`available_to` already on a technology's active window.
- A fuel/engine switch (IFO380→methanol→ammonia) is a **`transition`**
  (`from_technology → to_technology`, `action`, `capex_per_capacity`) — already
  supported, already in green_steel.
- The **count** of a cohort is the genuinely new field (see 2c).

### 2b. Route = an edge; alternatives are separate edges

A route is a `connections`/`edges` row (`from_node, to_node, commodity_id`,
+ the shipped `freight_cost`/`emissions`/`energy`/`lag_years`). **Suez vs Cape
vs Arctic between the same pair are separate edge rows** with different
distance/toll/carbon exposure — the optimiser picks among them. No new schema.

### 2c. Assignment = the new MILP layer (`fleet` + `fleet_routes`)

Two small new sheets, mirroring `technology_caps` (which is already
`dict[technology_id → int]`, a fleet-wide adoption cap — the integer-count
concept already exists):

```
fleet(archetype, year, available)          # ships of this class in existence in a year
                                            #   (or built/retired via transitions later)
fleet_routes(archetype, route, year,       # eligibility + throughput contribution + bounds
             share, min_units, max_units)
#   share      = annual throughput ONE class-`archetype` ship delivers on `route`
#              = (365 / round_trip_days) · cargo_capacity        ← §5 ship-count closure
#   round_trip_days ≈ 2·(distance_nm / speed) + port_time        ← ROUND trip (incl. ballast leg)
#   min/max_units = per-route fleet-count floor/ceiling (FleetGroup{[min,max]})
```

`share` is **authored from distance + speed + capacity** (a derivation helper,
not a magic constant) so a chokepoint reroute (Hormuz→Cape) is a distance edit
that flows through to throughput — the spatial model can finally *see* it.

---

## 3. The MILP (pathwise style)

```
Sets
  A   archetypes (ship cohorts)         R   routes (edges)        T   years
Parameters
  share[a,r]        t/yr one class-a ship delivers on route r   (from distance/speed/cargo)
  avail[a,t]        class-a ships in existence in year t          (fleet sheet)
  freight[r,t]      $/t on route r                                (edge freight_cost — existing)
  ef[r,i]           impact i per t on route r                     (edge emissions — existing)
New decision variable
  units[a,r,t] ∈ ℤ≥0    class-a ships assigned to route r in year t      ← the only new var
Existing variables
  move[r,t] ≥ 0     tonnes routed on r (= leg process throughput); buy/sell/produce  (existing)
Objective (unchanged shape)
  min  Σ freight·move  +  Σ price·buy  +  Σ_i scoped_price[i]·ef·move  +  capex·build + …
New / changed constraints
  (C1) capacity-from-fleet:   move[r,t] ≤ Σ_a units[a,r,t] · share[a,r]      ← replaces fixed machine cap
  (C2) fleet conservation:    Σ_r units[a,r,t] ≤ avail[a,t]                  ← shared pool, not welded to a route
  (C3) per-route bounds:      min_units[a,r,t] ≤ units[a,r,t] ≤ max_units[a,r,t]
Reused verbatim
  flow balance at each place-scoped commodity  (_flow_balance, place-scoped already works)
  emissions ef·move → ctx.emit → priced (scoped carbon) / capped / characterised (LCIA)
  transitions build/retire/retrofit, lifespan, vintage windows
```

(C1)–(C3) are **one new constraint family** over an integer var. The objective,
impacts, LCIA, transitions, and place-scoped flow balance are untouched. The
solver (HiGHS) and the MILP machinery (binary `on`/`u` commitment vars already
exist in `core/variables.py`) carry it.

---

## 4. Engine changes — precise scope (new vs reused)

| Piece | Status |
|---|---|
| `units[a,r,t]` integer variable | **new** — `core/variables.py` |
| (C1) capacity-from-fleet, (C2) fleet conservation, (C3) per-route bounds | **new** — `core/build.py`, ~one constraint block (mirrors the existing `cap` / `technology_caps` blocks) |
| `fleet`, `fleet_routes` sheets + `Problem` fields | **new** — `data/sheets.py`, `data/assemble.py`, `core/problem.py` (mirror `technology_caps` shape) |
| `share` derivation helper (distance/speed/cargo → t/yr) | **new** — small, `data/` |
| `units` reported per route/year in outputs | **new** — `core/extract.py` |
| Freight cost / emissions / energy on edges | **reused** — shipped (1a) |
| Place-scoped flow balance, markets, demand | **reused** |
| Carbon/pollutant pricing + caps + LCIA characterisation | **reused** (scoped pricing comes from the impact-generality proposal — same feature as 1c per-leg policy) |
| Build / retire / re-engine / fuel switch | **reused** — `transitions` |

Net: **one new integer var + one new constraint family + two data sheets.** This
is a perturbation, consistent with 1a's "no engine change" finding extended by
the minimum needed for a shared finite fleet.

---

## 5. UI — table not box-per-ship (the owner's idea, refined)

Three layers, cleanly separated (matches build-plan §3.2/§3.3/§9):

- **Map = ports + routes only.** Nodes = ports/regions; edges = routes
  (Suez/Cape/Arctic as separate edges). Sits on the existing `TopologyCanvas`
  as an additive geographic layer. **No ships on the map.**
- **Fleet = a table.** One *row per cohort* (archetype × vintage): capacity,
  fuel, energy/km, speed, capex, opex, `available_from`, eligible measures,
  `available` count. This is how the Facility view already lists machines.
- **Assignment = a table.** Route × cohort → `share`, `min_units`, `max_units`;
  the solved `units[a,r,t]` is written back into this table per year. This *is*
  "the number of fleet for each route, with min/max".
- **Individual named ships = post-solve only**, in the simulation/disaggregation
  layer (Phase 4): an itinerary table (which ship, which route, utilisation,
  realised burn). Never an optimiser variable, never a map box.

---

## 6. Validation case (Layer 1b)

Extend the methanol example: replace the three fixed-capacity route-machines
with **one shared fleet** of 2–3 cohorts (e.g. a cheap high-CO₂ class and a
costlier low-CO₂ class) and `fleet_routes` over the US/EU/CN→KR routes.

Assert:
1. With no carbon price, the fleet packs onto the cheapest freight+source combo
   up to `avail`, spilling to the next route only when `units` hits its cap.
2. A rising scoped carbon price **reallocates `units`** off the high-CO₂ route
   onto the low-CO₂ one — and the *integer* counts step (not smoothly), which is
   the point of MILP-from-the-start.
3. The shadow price on (C2) fleet conservation = the marginal value of an extra
   ship → the breakeven for ordering a newbuild. Surface it as a first-class
   output (same discipline as the MACC/transport output framing: direction +
   breakeven, not point forecasts).

Tiny instance, automated test (`tests/...test_fleet_assignment.py`), fast suite.

---

## 7. Open questions to confirm before code

1. **Naming (Decision A):** formalise `base@node` canonical + `base_node` alias,
   engine-agnostic — agreed?
2. **`fleet` granularity:** is `avail[a,t]` an exogenous given for 1b (count just
   gets *allocated*), with **build/retire of the count** deferred to a later
   increment? Or do we want `build`/`retire` integer vars on the cohort in 1b
   too? (Recommend: exogenous `avail` in 1b; endogenous newbuild/scrap next.)
3. **MILP cost:** integer-from-the-start is locked — confirm we accept a HiGHS
   MILP on the validation instance and will watch solve time as routes×cohorts
   grow (mitigation: LP relaxation warm-start, optionally relax to LP for large
   scenario sweeps and re-solve the chosen point as MILP).
4. **Per-route bounds semantics:** are `min_units`/`max_units` hard operational
   limits (berth/contract) or soft preferences? (Recommend hard for 1b.)

## 8. Anti-goals (unchanged from build plan §9)

No sub-annual time / scheduling / dwell. No per-ship integer vars in the
optimiser (cohorts only; ships in the sim). No stored `cost_per_tonne` on a
measure. No greedy MACC. No hardcoded policy/fuel/carbon values. One core, two
apps — no fork.
