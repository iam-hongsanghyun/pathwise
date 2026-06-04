# ALGORITHM — pathwise process-network model

A domain-agnostic, multi-period **mixed-integer linear program (MILP)** for
least-cost transition planning of a **network of production processes**. Solved
with `linopy` + HiGHS. This document is the contract that `src/pathwise/core/`
implements.

> Status: scaffolding. Sections below are stubs filled in during P1–P2.

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

## 2. Decision variables (stub)

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
+\sum_{p,k}DF_t\,\text{capex}_{p,k}\,w_{p,k,t}
+\sum_{s}DF_t\,\text{capex}_s\,\Delta z_{s,t}
+\sigma\!\sum(\xi^D+\xi^{cap})$$

`DF_t=(1+ρ)^{-(t-t_0)}`. Operational terms scale by period duration; capex is a
discounted lump at the event year (annuity convention is a later refinement).

## 4. Constraints (implemented in `core/build.py`)

- **One technology / capacity**: `Σ_{k∈feas(p)} u_{p,k,t}=1`; `x_{p,k,t} ≤ CAP_p·u_{p,k,t}`.
- **Baseline lock**: `u_{p,k₀(p),t₀}=1`.
- **Transition event**: `w_{p,k,t} ≥ u_{p,k,t}−u_{p,k,prev}` (replacement capex on `w`).
- **Node balance** (per `p,r,t`): `produced+buy+Σ_{in}flow = consumed+Σ_{out}flow+sell+deliver`,
  where `produced=Σ_k yield_{k,r}x`, `consumed=Σ_k int_{k,r}x − savings`. Only raw
  inputs (kind∈{energy,material,indirect}, produced by no technology) may be bought;
  only products may be delivered; only sellable streams sold.
- **Demand** (slack-softened): `Σ_{p∈c} deliver_{p,q,t}+ξ^D ≥ D_{c,q,t}`.
- **Impacts**: `emit_{p,i,t}=Σ_r f_{r,i}·consumed_{p,r,t}+Σ_k d_{k,i}·x_{p,k,t}−abate_{p,i,t}`,
  `emit ≥ 0`; caps `Σ_{p∈c} emit ≤ CAP_{c,i,t}+ξ^{cap}`.
- **MACC** (LP-safe): efficiency savings `= Σ reduction·ref_consumption·z`; abatement
  `= Σ reduction·ref_impact·z`; blocks cumulative (`z_a≥z_b`) and persistent (`z_t≥z_{prev}`).
- **Replacement coupling** (incompatible swap forces neighbours): planned;
  edges currently model pure flow.

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
- **Minimum production**: `Σ_{p∈c} deliver_{p,q,t} ≥ min_production_{c,q,t}` (hard).

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
