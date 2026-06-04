# ALGORITHM — pathwise optimisation model

A domain-agnostic, multi-period mixed-integer linear program (MILP) for
least-cost asset/process transition planning. Implemented in `linopy` and
solved with HiGHS. This document is the contract that `src/pathwise/core/`
implements; sector packs only *populate* it.

It generalises a shipping fleet decarbonisation model and adds three
capabilities the source lacked:

1. **MACC** — piecewise marginal-abatement-cost efficiency measures.
2. **Transition** — endogenous purchase of *new* assets (fleet renewal), not
   just retrofitting existing ones.
3. **Capital cost** — proper discounting via a capital-recovery-factor (CRF)
   annuity (or NPV), replacing the source's undiscounted lump-sum.

---

## 1. Sets and indices

| Symbol | Set | Meaning | Shipping analogue |
|---|---|---|---|
| `a ∈ A` | assets | unit with capacity, vintage, activity | ship |
| `Aᵉˣ ⊆ A` | existing assets | present at horizon start | existing ships |
| `k ∈ K` | technologies | asset configuration (cost + intensity) | engine/fuel config |
| `Kₐ ⊆ K` | feasible techs for `a` | compatibility / transition filter | allowed engines |
| `r ∈ R` | carriers | blendable consumable input | fuel |
| `m ∈ M` | measures | MACC efficiency/abatement retrofit | energy-saving tech |
| `b ∈ Bₘ` | MACC blocks of `m` | piecewise abatement steps | — |
| `t ∈ T` | periods | ordered horizon; `t₀ = min T` baseline | year |
| `g ∈ G` | groups/classes | for fleet/class limits & demand | operator / fleet type |

Derived: `prev(t)` = previous period; `T⁺ = T \ {t₀}`.

## 2. Parameters (units)

**Finance / time**
- `ρ` — discount rate `[1/yr]`.
- `DF_t = (1+ρ)^-(yr(t)-yr(t₀))` — discount factor `[—]`.
- `L_k`, `L_m` — economic lifetime `[yr]`.
- `CRF_x = ρ(1+ρ)^L / ((1+ρ)^L − 1)` — capital recovery factor `[1/yr]`.

**Asset / activity**
- `D_{g,t}` — required activity per group `[activity]`.
- `CAP_a` — capacity `[activity/yr]`; `size_a` — cost-scaling attribute (e.g. GT).
- `built_a`, `retire_a` — availability window `[yr]`.
- `SEC_{k}` — specific energy consumption `[MJ/activity]`.

**Technology / carrier**
- `EI_{k,t}` — emission intensity `[gCO2e/MJ]` (well-to-wake).
- `φ_{k,r}` — carrier split of tech `k` `[—]`; `LCV_r` `[MJ/t]`.
- `p^fuel_{r,t}` — carrier price `[USD/t]` (→ `USD/MJ` via `/LCV`).
- `opex^fix_{k,t}` `[USD/(size·yr)]`, `opex^var_{k,t}` `[USD/MJ]`.
- `s̲_{k,r,t}`, `s̄_{k,r,t}` — min/max carrier share `[—]`.

**CAPEX**
- `capex^retro_{a,k,t}` — retrofit `a→k` `[USD]`.
- `capex^build_{k,t}` — overnight new-build cost `[USD/(activity/yr)]` or `[USD/asset]`.
- `capex^macc_{a,m,b}` — MACC block cost `[USD]`.

**MACC blocks**
- `η_{m,b}` — fractional energy/intensity reduction of block `b` `[—]`.

**Targets / carbon (data-driven — never hardcoded)**
- `EI̅_{g,t}` — intensity limit `[gCO2e/MJ]`.
- `π^C_t` — carbon price trajectory `[USD/tCO2e]`.
- Piecewise tiers: thresholds `θ^(j)_t` `[gCO2e/MJ]`, rates `λ^(j)_t` (negative ⇒ credit).
- `σ_slack` — slack penalty `[USD per unit violation]`.

## 3. Decision variables

| Var | Domain | Units | Intent |
|---|---|---|---|
| `u[a,k,t]` | {0,1} | — | asset `a` runs tech `k` in `t` |
| `x[a,k,r,t]` | [0,1] | — | carrier share within tech |
| `w_retro[a,k,t]` | {0,1} | — | retrofit event `→k` in `t` (triggers CAPEX) |
| `n_build[k,t]` | ℤ₊ / ℝ₊ | assets/cap | new builds commissioned |
| `z[a,m,b,t]` | [0,1] | — | MACC block adoption fraction |
| `q[a,t]` | ℝ₊ | activity | activity served by `a` |
| `h[a,t]` | {0,1}/[0,1] | — | asset alive/active in `t` |
| `ξ_EI[g,t], ξ_D[g,t]` | ℝ₊ | — | slack on intensity / demand |
| `e_tier[j,g,t]` | ℝ₊ | gCO2e/MJ | emissions in carbon-penalty band `j` |

Energy served: `E[a,t] = q[a,t] · SEC_eff`, where `SEC_eff` embeds MACC
reductions on a per-unit-energy basis (keeps the term linear — see §5 C9).

## 4. Objective — discounted total system cost

LaTeX:

$$
\min \sum_{t} DF_t \Big[
\sum_{a,k,r}\frac{E_{a,t}\,\phi_{k,r}\,x_{a,k,r,t}\,p^{\text{fuel}}_{r,t}}{LCV_r}
+\sum_{a,k}\text{opex}^{\text{fix}}_{k,t}\,\text{size}_a\,u_{a,k,t}
+\sum_a CRF\cdot\Theta_{a,t}
+\pi^{C}_t\,\bar E_t
+\sum_j \lambda^{(j)}_t e^{(j)}_{g,t}
+\sigma_{\text{slack}}\sum_g(\xi^{EI}_{g,t}+\xi^{D}_{g,t})
\Big]
$$

where the annualised CAPEX stock accumulates every retrofit / build / measure
still within its economic lifetime:

$$
\Theta_{a,t}=\sum_{k}\sum_{\tau:\,t-L_k<\tau\le t} CRF_k\,\text{capex}^{\text{retro}}_{a,k,\tau} w^{\text{retro}}_{a,k,\tau}
+\sum_{m,b} CRF_m\,\text{capex}^{\text{macc}}_{a,m,b}\,z_{a,m,b,t}.
$$

ASCII fallback:

```
min  sum_t DF_t * [ sum_{a,k,r} E[a,t]*phi[k,r]*x[a,k,r,t]*p_fuel[r,t]/LCV[r]
                  + sum_{a,k} opex_fix[k,t]*size[a]*u[a,k,t]
                  + sum_a CRF*capex_amortised[a,t]
                  + carbon_price[t]*emissions[t]
                  + sum_j lambda[j,t]*e_tier[j,g,t]
                  + slack_penalty*(xi_EI + xi_D) ]
DF_t = (1+rho)^-(year_t - year_0)
CRF  = rho*(1+rho)^L / ((1+rho)^L - 1)
```

CAPEX convention is configurable: **CRF annuity** (default; no end-of-horizon
bias) or **NPV lump** + residual-value credit.

## 5. Constraints

- **C1 Activity/demand balance** (slack-softened): `Σ_{a∈g} q[a,t] + ξ_D[g,t] ≥ D[g,t]`.
- **C2 Capacity/availability**: `q[a,t] ≤ CAP_a · h[a,t]`; `h=0` outside `[built_a, retire_a]`.
- **C3 One tech per asset per period**: `Σ_{k∈Kₐ} u[a,k,t] = h[a,t]`.
- **C4 Baseline lock**: `u[a, k₀(a), t₀] = 1` for `a ∈ Aᵉˣ`.
- **C5 Retrofit event detection** (linearised): `w_retro[a,k,t] ≥ u[a,k,t] − u[a,k,prev(t)]`; `w_retro ≤ u[a,k,t]`; `w_retro ≤ 1 − u[a,k,prev(t)]`.
- **C6 Transition limits/timing**: `Σ_{k,t} w_retro[a,k,t] ≤ N_max_a`; `w_retro = 0` if `yr(t) − built_a < τ_min`.
- **C7 New-build commissioning**: built capacity available only after lead time; integer `n_build` if lumpy.
- **C8 Carrier-share balance**: `Σ_r x[a,k,r,t] = u[a,k,t]`; `s̲·u ≤ x ≤ s̄·u`.
- **C9 MACC adoption** (piecewise, cumulative, persistent): `z[a,m,b,t] ≥ z[a,m,b+1,t]`; `z[a,m,b,t] ≥ z[a,m,b,prev(t)]`; `SEC_eff = SEC·(1 − Σ_{m,b} η_{m,b} z[a,m,b,t])`. Per-unit-energy form keeps it LP.
- **C10 Intensity target** (slack-softened): `Σ E·φ·x·EI ≤ EI̅_{g,t}·Σ E + ξ_EI[g,t]`.
- **C11 Carbon-tier decomposition**: `EI_avg = θ^(0) + Σ_j e_tier[j]`; `0 ≤ e_tier[j] ≤ θ^(j) − θ^(j-1)`. Each band priced at `λ^(j)`.
- **C12 Group/class/carrier limits** (as in source `fuel_limits`).
- **C13 Budget** (optional): `Σ_a DF_t Θ_{a,t} ≤ B_t`.

## 6. Carbon / ETS pricing

The source hardcoded RU/SU rates (`10.0 / 38.0 / 5.0`) and thresholds
(`77.4 / 89.6 / 75.0`). These are **removed** and replaced by config/data-driven
trajectories entering via C11 and the objective. A single carbon price is the
special case of one band with `λ^(1) = π^C_t`. A subsidy/credit is a negative
`λ`. Policy start years are expressed as data (`λ = 0` before the policy year),
not code branches.

## 7. linopy implementation notes

- Declare variables over named xarray dims; pass boolean `mask=` DataArrays
  (`Kₐ`, `Mₐ`, `transition_allowed`) so HiGHS never sees impossible columns.
- Build each cost term as a `LinearExpression`, multiply by `DF_t` / `CRF`
  data arrays, `.sum()`, `add_objective`.
- Solve: `model.solve(solver_name="highs", mip_rel_gap=…, time_limit=…, threads=…)`.
- Keep coefficients well-scaled: convert units (pint) at the data boundary, not
  inside the matrix.

## 8. Edge cases & feasibility

- Per-asset demand balance + slack replaces the source's fleet-level
  aggregation that hid infeasibility; positive slack pinpoints the binding
  period/group.
- Assert non-empty feasible tech set per asset at build time.
- New-build "slots" have `h=0` until commissioned; retrofit vars disabled on
  un-built slots.
- Prefer per-unit-energy MACC (constant multiplier) to stay pure-LP; only
  introduce McCormick aux vars if absolute-energy abatement is required.

## 9. Bilevel emission-pathway search (optional outer level)

Sections 1–8 describe a **single-level** MILP: the emission pathway (intensity
caps `EI̅_{g,t}`, C10) is *fixed input*. The optional outer level instead
*chooses* a single sector-wide per-year intensity cap `c_t` and lets the inner
MILP decide each group's least-cost response — so the sector trajectory is an
output of cost-optimising behaviour rather than an imposed target.

**Decision.** A vector `c = (c_t)_{t∈T}` [gCO2e/MJ], broadcast to **every** group
(`EI̅_{g,t} := c_t ∀g`), then a single joint inner solve. Box bounds:

$$ f_\text{floor}\cdot \bar c_t \le c_t \le \bar c_t,\qquad
   \bar c_t = \max_g \widehat{EI}_{g,t} $$

where `c̄_t` is the loosest existing cap in the selected target set (the
upper bound) and `f_floor ∈ [0,1]` the floor fraction. ASCII:
`floor_frac*upper[t] <= c[t] <= upper[t]`, `upper[t] = max over groups of the target-set cap`.

**Bilevel objective.** With `J(c)` the inner optimal total discounted system
cost (§4) under caps `c` (slack-softened, so an over-tight `c` is feasible but
expensive):

$$ \min_{c\in[\,f_\text{floor}\bar c,\ \bar c\,]} J(c),\qquad
   J(c)=\min_{x\in\mathcal X(c)} \text{cost}(x) $$

ASCII: `min_c J(c)` s.t. `J(c) = min_x cost(x)` over the inner feasible set `X(c)`.

**Outer solvers** (`pathwise.core.outer`):

- **Simulated annealing** (default) — symmetric Gaussian proposal per coordinate,
  clamped to the box; Metropolis acceptance `P = exp(-Δ/T)` for `Δ>0`; geometric
  cooling `T_{k+1}=γT_k`. Reproducible via a seeded `numpy` generator. Each
  proposal is one inner solve, so the iteration count is clamped by the
  server-side `max_outer_iterations`.
- **Deterministic sweep** — scale `c = clip(α·c̄, floor, c̄)` for `α` over a grid
  on `[1,0]`; the cheapest rung wins and the full set traces a cost–emissions
  frontier.

**Notes.** Because carbon is already priced in `J` (§6), the cost-optimal `c`
can be interior (a genuine fuel-switching vs carbon-cost trade-off) or — when no
carbon price is active — sit at the upper bound `c̄` (looser is cheaper). The
`sweep` frontier makes this explicit. Broadcasting one cap to all groups and
solving jointly preserves any cross-group coupling; per-company independent
pathways are a future extension.
