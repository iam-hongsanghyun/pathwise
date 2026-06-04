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

## 3. Objective (stub)

Discounted total system cost: capex(replace) + renewal(renew) + opex + resource
cost + per-impact price (carbon/ETS) + measure capex − abatement credit + slack
penalty. Filled in at P2.

## 4. Constraints (stub)

Demand balance; one-tech + transition logic; resource use + pairing; network flow
balance; impact equation + caps; MACC adoption; replacement coupling. Filled in at P2.
