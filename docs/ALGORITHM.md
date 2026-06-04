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
| `r ∈ R` | resources | energy / material / indirect input |
| `q ∈ Q` | products | process outputs (demand targets) |
| `i ∈ I` | impacts | CO₂, SOₓ, NOₓ, … (priceable, cappable) |
| `m ∈ M` | measures | energy-efficiency / emission-reduction / environmental |
| `b ∈ Bₘ` | MACC blocks | piecewise steps of measure `m` |
| `t ∈ T` | periods | ordered horizon; `t₀ = min T` baseline |
| `e=(p→p') ∈ E` | edges | directed inter-process flow |

## 2. Decision variables (stub)

`u[p,k,t]∈{0,1}`, `replace/renew/continue[p,k,t]∈{0,1}`, `prod[p,t]≥0`,
`rc[p,r,t]≥0`, `flow[e,t]≥0`, `z[p,m,b,t]∈[0,1]`, `emit[p,i,t]`, slacks `ξ`.

## 3. Objective (stub)

Discounted total system cost: capex(replace) + renewal(renew) + opex + resource
cost + per-impact price (carbon/ETS) + measure capex − abatement credit + slack
penalty. Filled in at P2.

## 4. Constraints (stub)

Demand balance; one-tech + transition logic; resource use + pairing; network flow
balance; impact equation + caps; MACC adoption; replacement coupling. Filled in at P2.
