# ALGORITHM — pathwise process-network model

A domain-agnostic, multi-period **mixed-integer linear program (MILP)** for
least-cost transition planning of a **network of production processes**. Solved
with `linopy` + HiGHS. This document is the contract that `src/pathwise/core/`
implements.

The authoritative implementation is `src/pathwise/core/build.py`.

## 1. Sets and indices

| Symbol | Set | Meaning |
|---|---|---|
| `c ∈ C` | companies | owner/site grouping for demand & caps |
| `p ∈ P` | processes | facility/machine (one technology active per period) |
| `k ∈ K` | technologies | process configuration (intensities, factors, costs) |
| `r ∈ R` | commodities | any stream: energy / material / indirect / product / by-product (each with its own unit) |
| `i ∈ I` | impacts | CO₂, SOₓ, NOₓ, … (priceable, cappable) |
| `m ∈ M` | measures | energy-efficiency / emission-reduction / environmental |
| `b ∈ Bₘ` | MACC blocks | piecewise steps of measure `m` |
| `t ∈ T` | periods | ordered horizon; `t₀ = min T` baseline |
| `e=(p→p') ∈ E` | edges | directed inter-process flow |

**Multi-commodity flow.** A process consumes a bundle of input commodities and
produces a bundle of outputs (product + residual energy + residual material +
by-products). An output commodity can (a) satisfy product demand, (b) route along
an edge to a downstream process's input, or (c) be sold/wasted. Per-commodity
balance holds at every process node. Each commodity carries its own unit;
intensities/yields/prices/impact-factors that reference a commodity all use that
commodity's unit (no cross-unit conversion needed inside the matrix).

## 2. Decision variables

`u[p,k,t]∈{0,1}`, `replace/renew/continue[p,k,t]∈{0,1}`, `thru[p,t]≥0` (throughput);
`buy[r,p,t]≥0`, `sell[r,p,t]≥0` (external purchase/sale of commodity `r` at `p`);
`flow[e,t]≥0` (commodity routed on edge `e`); `z[p,m,b,t]∈[0,1]`; `emit[p,i,t]`;
slacks `ξ`. Inflow needed `= Σ_k in_intensity[k,r]·thru_k`; outflow produced
`= Σ_k out_yield[k,r]·thru_k`; node balance ties `buy + Σ_in flow = inflow` and
`outflow = Σ_out flow + sell + demand_served`.

## 3. Objective

$$\min \sum_t DF_t\Big[\sum_{p,k}\text{opex}_{k,t}\,x_{p,k,t}
+\sum_{p,r}(\text{price}_{r,t}\,\text{buy}_{p,r,t}-\text{sale}_{r,t}\,\text{sell}_{p,r,t})
+\sum_{p,i}\pi_{i,t}\,\text{emit}_{p,i,t}\Big]
+\sum_{p,k}\text{capex}_{p,k,t}\,w_{p,k,t}
+\sum_{p,k}\text{renewal}_{k,t}\,\text{ren}_{p,k,t}
+\sum_{m,b}DF_t\,\text{capex}_{m,b}\,\Delta z_{m,b,t}
+\sigma\!\sum(\xi^D+\xi^{cap})$$

`DF_t=(1+ρ)^{-(t-t_0)}`. Operational terms scale by period duration. Capex enters
on four event families, each multiplied by `capex_charge(year, lifespan)` (see 3b):
technology **replacement** on `w`, **renewal** (same-tech rebuild) on `ren`,
**measure** adoption on the increment `Δz`, and a one-time **storage** build on
`cap_built` (charged at the build year). The `min` sense is kept under the profit
objective by entering product revenue as negative cost (§6b).

## 3b. Economics / discounting

### Discount factor

`DF_t = (1 + ρ)^{-(t − t₀)}` where `ρ` is the annual discount rate and `t₀` is
`base_year` (defaults to the first horizon year).

### Capex convention (`economics.capex_convention`)

A capital outlay `C` on an asset of life `L` in year `t` enters the objective as
`capex_charge(t, L) · C` on the event variable. Two conventions are available:

| `capex_convention` | Formula | Notes |
|---|---|---|
| `"npv"` (default) | `DF_t` | Full discounted lump at the event year. |
| `"annuity"` | `CRF_due(ρ, L) · Σ_{t≤t'<t+L, t'∈years} DF_{t'} · Δ_{t'}` | Capital-recovery-factor annuity due over the asset life. |

Where `CRF(ρ, L) = ρ(1+ρ)^L / ((1+ρ)^L − 1)` (= `1/L` when ρ = 0) and
`CRF_due = CRF / (1+ρ)` (payments start in the build year). The two are
present-value equivalent when the full asset life lies inside the horizon; ANNUITY
charges strictly less when the horizon truncates the life, because unbuilt future
years carry no cost.

Set via `ScenarioConfig.economics.capex_convention`; the same convention applies
to transition capex, renewal capex, and technology capex.

## 4. Constraints (implemented in `core/build.py`)

- **One technology / capacity**: `Σ_{k∈feas(p)} u_{p,k,t}=1`; `x_{p,k,t} ≤ CAP_p·u_{p,k,t}`.
- **Capacity factor** (utilisation band, per process): a must-run floor
  `x_{p,k,t} ≥ min_cf_{k,t}·CAP_p·u` (technology `min_capacity_factor`) and a
  per-machine ceiling `x_{p,k,t} ≤ max_cf_{p,t}·CAP_p·u` (process
  `max_capacity_factor`, default 1 ⇒ inert). Both year-aware.
- **Baseline lock**: `u_{p,k₀(p),t₀}=1`.
- **Transition event**: `w_{p,k,t} ≥ u_{p,k,t}−u_{p,k,prev}` (replacement capex on `w`).
- **Lagged edges**: an edge with `lag_years = L` delivers across time — flow leaving
  the producer in year `t` arrives at the consumer in `t+L` (the consumer's inflow
  at `t` draws `flow[edge, t−L]`; arrivals predating the horizon are not received).
  Models a use-phase / recycling return; a quality change is the producer emitting
  a different commodity.
- **Node balance** (per `p,r,t`): `produced+buy+Σ_{in}flow = consumed+Σ_{out}flow+sell+deliver`,
  where `produced=Σ_k yield_{k,r}x`, `consumed=Σ_k int_{k,r}x − savings`. Only raw
  inputs (kind∈{energy,material,indirect}, produced by no technology) may be bought;
  only products may be delivered; only sellable streams sold.
- **Demand** (slack-softened): `Σ_{p∈c} deliver_{p,q,t}+ξ^D ≥ D_{c,q,t}`.
- **Impacts**: `emit_{p,i,t}=Σ_{r,k} f_{r,i,t}·int_{k,r,t}·x_{p,k,t}+Σ_k(d^{tech}_{k,i,t}+d^{proc}_{p,i,t})·x_{p,k,t}−abate_{p,i,t}`,
  `emit ≥ 0`. The commodity term is on **gross** throughput (`int·x`), so MACC
  energy-efficiency savings cut *purchased volume* via the node balance, not the
  emission factor; only the explicit `abate` term (emission/environmental measures)
  reduces `emit`. `d^{proc}` is a per-facility factor added on top of the
  technology's own `d^{tech}`. Caps `Σ_{p∈c} emit ≤ CAP_{c,i,t}+ξ^{cap}` are
  **soft** by default (penalised slack); `impact_cap_soft=false` makes a cap hard
  (`ξ=0`), and an **intensity** cap (`impact_cap_intensity`) binds
  `Σ emit ≤ CAP·Σ production` instead of a flat limit.
- **MACC** (LP-safe): efficiency savings `= Σ reduction·ref_consumption·z`; abatement
  `= Σ reduction·ref_impact·z`; blocks cumulative (`z_a≥z_b`) and persistent (`z_t≥z_{prev}`).
- **Input blend groups** (fuel mixes): per technology group `g` with members `C_g`
  and requirement `R_g = Σ_{c∈C_g} int_{k,c}`:
  `Σ_{c∈C_g} fin_c = R_g·x` and `s̲_c·R_g·x ≤ fin_c ≤ s̄_c·R_g·x` — the optimiser
  picks each member's share within `[s̲, s̄]`. Grouped inputs are consumed via
  `fin`; others keep the fixed form `int·x`.
- **Output slate groups** (co-product slates, e.g. a naphtha cracker): the
  production-side mirror. Per slate `G` with requirement `R_G = Σ_{c∈G} yield_{k,c}`:
  `Σ_{c∈G} fout_c = R_G·x` and `s̲_c·R_G·x ≤ fout_c ≤ s̄_c·R_G·x` — the product
  mix follows prices within the unit's physical flexibility. Grouped outputs are
  produced via `fout`; others keep the fixed form `yield·x`. Declared on `io`
  output rows via the same `group`/`share_min`/`share_max` columns.
- **Replacement coupling** (incompatible swap forces neighbours): planned. Edges
  otherwise model flow with optional per-period min/max bounds — see *Edge flow
  bounds* in §5b and [features/stream-bounds.md](features/stream-bounds.md).
- **Asset end-of-life lifecycle** (`_lifecycle` in `core/build.py`): a process that
  declares `introduced_year` is lifecycle-tracked. A technology may be active in
  year `t` only if a *live vintage* covers it:

  $$u[p,k,t] \leq \underbrace{\text{live}_0[p,k,t]}_{\text{original install}} + \sum_{\substack{t' \in T \\ t-L < t' \leq t}} \text{refresh}[p,k,t']$$

  ASCII: `u[p,k,t] <= live0[p,k,t] + Σ_{t-L<t'<=t} refresh[p,k,t']`

  where `L` = `lifespan`, `live0 = 1` if `k` is the baseline and
  `t < introduced_year + L`, else 0; `refresh = ren` for the baseline (a
  same-technology rebuild) and `refresh = w + ren` for a replacement target
  (a switch-in or a subsequent rebuild). A renewal is permitted only when the
  technology's `actions` include `renew`. Models with no `introduced_year` are
  unaffected. See also: `TransitionAction.RENEW`, `Technology.renewal_by_year`,
  `Process.introduced_year`, and the new features docs in
  [transitions.md](features/transitions.md).
- **Availability gates** (decide *when* a machine exists / a technology may run):
  - **Active window** (machine existence): `on_{p,t}=0` outside
    `[introduced_year_p, decommission_year_p)` — off **before** the build year and
    off **from** the close year (close is **exclusive**: close 2038 ⇒ runs through
    2037). This window overrides the technical lifespan. Either bound is optional.
  - **Availability window** (technology market): a technology is infeasible before
    its `introduction_year` (available-from, inclusive) and **from** its
    `phase_out_year` (available-to, **exclusive**) — so a facility running it must
    transition or switch off by then. Per-machine once the technology is instanced;
    the baseline is exempt from intro but not from phase-out.
  - **Vintage timing** (opt-in `vintage_timing`): `w` and `ren` may fire only at
    end-of-life boundaries `((t − introduced_year) mod L = 0)` — continue-only in
    between, the rigid grid.
  - **Fleet adoption caps**: `Σ_p u_{p,k,t} ≤ N_{k,t}` (at most `N` machines on a
    technology in a year).
  - **Purchase caps**: `Σ_p buy_{p,r,t} ≤ max_purchase_{r,t}` (per-commodity
    external-supply ceiling).

  The action semantics that fall out of this single covering inequality:

  - **Continue** — free (no event), available **anytime a live vintage covers `t`**.
    It is *not* available once the vintage expires: at `t ≥ introduced_year + L`
    the strict window `t-L < t' ≤ t` excludes the original install, so `live0 = 0`
    and `u` can only stay 1 via a `refresh` event. Reaching end of life therefore
    forces a **replace or renew** — continue is impossible there.
  - **Replace** — a switch-in `w` may fire in **any** year, so a technology can be
    replaced mid-lifespan, not only at end of life. Replacing early carries its
    cost *implicitly*: the abandoned asset's capex was already a sunk lump in its
    build year (NPV convention; or its remaining annuity stream under `annuity`),
    and the new technology's capex is paid again — so early replacement is never
    free. The pre-existing baseline carries no capex term (a paid-off historical
    asset), so abandoning it early strands nothing further.
  - **Renew** — a same-technology rebuild `ren`. Allowed in any year the active
    technology permits it, but never economically chosen mid-life (continue is
    free), so in practice it only fires at end of life. Bounded per machine by
    the renewal-count cap below.

  **Per-machine renewal-count cap** (`Process.max_renewals`, constraint `rencap`):

  $$\sum_{k,\,t} \text{ren}[p,k,t] \;\leq\; \text{max\_renewals}_p$$

  ASCII: `Σ_{k,t} ren[p,k,t] <= max_renewals[p]`

  A machine may rebuild at most `max_renewals` times over the whole horizon
  (summed across every technology it runs). `None` ⇒ unlimited (no row added);
  `0` ⇒ renewal forbidden, so an expiring vintage must replace or switch off;
  `N` ⇒ at most `N` rebuilds, after which the window constraint forces a
  replacement — the "reline a BF-BOF `N` times, then build new" rule. Binds only
  on lifecycle-tracked machines (those declaring `introduced_year`).

## 5b. Storage, facility costs & decision controls

- **Capacity derate**: available throughput `= CAP_p·(1 − failure_rate_p)`; a
  facility also carries a fixed annual O&M paid while it operates.
- **Per-commodity storage** (inter-year inventory). Per store `s` of commodity `r`:
  `level_t = (1−loss)·level_{t-1} + η_c·charge_t − discharge_t/η_d`;
  `extbuy_t = Σ_{p∈scope} buy_{p,r,t} + charge_t − discharge_t ≥ 0`;
  `0 ≤ level_t, charge_t, discharge_t ≤ cap_built ≤ max_capacity`. Only `extbuy`
  is priced (process buy of a stored commodity is the internal draw). Cost adds
  `capex·cap_built` (one-time) + `opex·cap_built` (annual). Lets the system buy
  cheap years / release dear years against fluctuating annual prices.
- **Investment budget**: `Σ (nominal capex in year t for company c) ≤ budget_{c,t}`
  over transition + measure + storage capex.
- **Production bounds** (per scope `c`, commodity `q`, year `t`):
  `Σ_{p∈c} deliver_{p,q,t} ≥ min_production_{c,q,t}` and `≤ max_production_{c,q,t}`
  (both hard). `c` resolves via `Process.in_scope` (`"all"`, node id, company,
  group, or any ancestor), so a per-machine cap binds just that machine.
- **Consumption bounds** (the consumer-side mirror; per scope `c`, commodity `q`,
  year `t`): `Σ_{p∈c} gross_consumed_{p,q,t} ≥ min_consumption_{c,q,t}` and
  `≤ max_consumption_{c,q,t}`. `gross_consumed` is the machine's intake of `q`
  (the blend `fin` flow for grouped members, else `int·x`), summed over its
  providers — `min` = required offtake (take-or-pay), `max` = max purchase.
- **Edge flow bounds** (per provider→consumer link, commodity): `min_flow_{e,t}
  ≤ flow_{e,t} ≤ max_flow_{e,t}` via `Edge.min_flow_at`/`max_flow_at` (year-aware;
  sparse year rows interpolated, flat-held ends). A node-space `connections_t`
  row is fanned onto every synthesized edge by `_expand_hierarchy`, so a
  per-provider bound caps each provider's link independently.

## 6b. Markets, tradable ETS & profit

- **Per-company objective** (`company_config`): `cost` (default — demand is a
  hard, slack-softened floor) or `profit` (demand is the max sellable; revenue
  `= sale_price·deliver` enters the objective as negative cost; producing less
  is allowed). Objective sense stays *minimise* (`min cost − revenue`).
- **Commodity markets** (KEPCO / PPA-RE100 / JKM): least-cost mixture clears a
  stream's external need, `Σ_m (mbuy − msell) = need`, each `≤ max_buy/max_sell`,
  priced `mbuy·price − msell·sell_price`. Markets override the flat commodity
  price; a stream with no market falls back to its attribute price.
- **Tradable ETS** (impact market): `allocation_t + abuy_t − asell_t =
  Σ_{p∈scope} emit`; cost `abuy·price − asell·sell_price` (net can be negative).
  Replaces flat impact pricing for that impact; hard `impact_caps` still apply.
- **Non-replaceable** facility ⇒ locked to baseline tech. **Storage** build is
  optional (`max_capacity = 0` forbids it).

## 10. Time resolution (current vs planned)

Current: **annual periods** for long-term planning; prices/caps/demand are
year-keyed trajectories. **Planned**: PyPSA-style **weighted snapshots**
(hourly→yearly) for intra-period price fluctuation and short-cycle storage
arbitrage / market analysis.
