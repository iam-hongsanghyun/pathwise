# Proposal: a `simulate` backend — scenario LCA & policy what-if

> Status: **proposal** (P1 landing alongside this doc). Reviewers: please react to
> the *Decisions* and *Open questions* sections.

## 1. Motivation

pathwise today answers one question: **"what is the least-cost way to hit the
target?"** (the `linopy` MILP, the `macc` greedy runner, the `portfolio`
backend). That is the right tool when you trust the objective and want the model
to *choose* for you.

But a common real question is different. *An automaker wants to cut the lifecycle
emissions of its product.* It already has a configuration (today's plant, today's
suppliers). It is weighing **specific interventions** — switch to green steel,
source renewable power, add an efficiency measure, lightweight the body — and
wants to **see and compare** the lifecycle impact, the cost, and how a **policy
lever** (carbon price / ETS / a regulatory cap) changes the picture.

For that, optimisation is the wrong lens: it is opaque (it picks for you), and it
assumes its cost objective equals the user's goal. The right lens is a
**simulator**: *pin a configuration, perturb one thing, compare A vs B.*

This is the same relationship `macc` already has to `linopy`: a different
**solve method over the same value-chain model, not a new data format**. The
simulator reuses `validate → assemble → Problem` and then, instead of optimising,
**evaluates fixed configurations and diffs them.**

## 2. The two lenses

| | Optimise (`linopy` / `macc`) | Simulate (`simulate`) |
|---|---|---|
| Question | "What's cheapest to hit the target?" | "What happens if I change *this*?" |
| Decisions | Model chooses (tech, transitions, measures) | **User pins them**; model evaluates |
| Output | One optimal pathway | Side-by-side **A vs B** (LCA, cost, policy) |
| Use | Find the frontier | Test interventions, communicate, sensitivity |

## 3. Architecture (reuse, don't rebuild)

```
Workbook ──validate──▶ assemble_problem ──▶ Problem
                                              │
                          ┌───────────────────┼───────────────────┐
                          ▼                    ▼                   ▼
                   LinopyBackend         MaccBackend         SimulationBackend   ← new
                   (MILP optimise)    (greedy abate)     (evaluate fixed configs)
```

- New `SimulationBackend` implements the existing `Backend` Protocol
  (`name="simulate"`, `label`, `capabilities()`, `run(model, scenario, options)`)
  and registers in `backends/registry.py`. It is then selectable exactly like the
  other methods (the run UI already has a method picker).
- **No schema changes.** Same `Workbook`, same `Problem`, same `entities`.
- A **variant is a set of edits to the Workbook**, then evaluate: swap a machine's
  `baseline_technology`, toggle a measure, change a stream price / source. Each
  variant → `assemble_problem` → evaluate → LCA. Comparison = diff the LCAs.

### Decision — how a fixed configuration is *evaluated*

Two options:

1. **Fixed-config LP (recommended).** Reuse `build()` + `solve()`, but with the
   structural choices pinned: for the baseline, evaluate the model with
   `transitions` stripped and measures held at the scenario's set — so each
   machine runs its baseline technology and the LP only resolves flows / buy /
   sell. This reuses **all** existing machinery (blend groups, pools, `lag_years`
   recycling, stream limits, the annuity/NPV capex conventions) and is guaranteed
   consistent with the optimiser. Cost: one LP solve per variant (cheap — no
   integer variables once decisions are pinned).
2. **Direct propagation (future fast-path).** For an acyclic, choice-free network,
   propagate demand upstream and sum `intensity × throughput`. Faster and needs no
   solver, but re-implements blends / pools / lagged loops. Defer; revisit only if
   solve latency in a big policy sweep becomes a problem.

**Recommendation: option 1.** Fidelity and code-reuse beat the marginal speed of
option 2, and the recycling loop (lagged edges) "just works".

## 4. LCA framing

The project premise is **"sector models *are* value chains"** — so the value
chain's stages already *are* the lifecycle stages. The LCA is the model's emission
inventory, **grouped by stage** and **normalised per functional unit**.

- **Functional unit**: the studied product (e.g. one car). Taken from the demand
  the user is analysing.
- **Phase / stage mapping**: by default, group emissions by the **company node**
  each process sits under (mining → ironmaking → steel → power/H2 → automaker →
  scrap). A coarser **lifecycle-phase** rollup (`materials` · `manufacturing` ·
  `use` · `end-of-life`) is an optional `phase` tag (process- or sector-keyed) in
  the scenario; default heuristic: the company carrying the analysed demand =
  *manufacturing*, its upstream suppliers = *materials*, a node that returns a
  commodity via a **lagged** connection = *end-of-life* (the recycling credit).
- **Boundary**: the network gives **cradle-to-gate** out of the box. The **use
  phase** (driving emissions over the car's life) is *not* in the model yet; it is
  a one-process add — a `Use` process consuming `car-years` and emitting fuel /
  grid CO₂ — in the *same* framework. P1 reports use-phase = 0 with an explicit
  note; adding it is a P3 modelling task, not an engine change.

The recycling loop just shipped (`green_steel`) *is* the end-of-life phase, so
"with vs without recycling" is a natural first comparison.

## 5. Scenario config (the simulator's input)

```jsonc
{
  "simulate": {
    "functional_unit": { "company": "vc/korea/kr_auto", "commodity": "car" },
    "baseline": { "plan": "as-is" },          // current config: transitions off
    "variants": [
      { "label": "green steel",     "overrides": [ /* workbook edits */ ] },
      { "label": "renewable power", "overrides": [ ... ] }
    ],
    "policy_sweep": {                          // optional
      "lever": "carbon_price", "impact": "CO2",
      "from": 0, "to": 300, "step": 25
    }
  }
}
```

An `override` is a small, typed workbook edit, e.g.
`{ "op": "set_machine_tech", "machine": "…/bof", "technology": "EAF" }`,
`{ "op": "toggle_measure", "measure": "…", "on": true }`,
`{ "op": "set_price", "commodity": "electricity", "price": … }`.

## 6. Output (extends the result dict)

```jsonc
"outputs": {
  "lca": {
    "functional_unit": { "commodity": "car", "amount": 7200000 },
    "by_stage":  [ { "stage": "vc/korea/kr_steel", "impact": "CO2", "total": …, "per_unit": … }, … ],
    "by_impact": [ { "impact": "CO2", "total": …, "per_unit": … } ],
    "cost":      { "capex": …, "opex": …, "purchase": …, "carbon": …, "total": …, "per_unit": … }
  },
  "comparison": [                              // P2
    { "label": "green steel", "abatement_tco2": …, "cost_delta": …, "abatement_cost_per_t": …,
      "breakeven_carbon_price": … }
  ],
  "policy_sweep": [                            // P3
    { "carbon_price": 0,   "variants": [ { "label": "baseline", "cost": …, "co2": … }, … ] }, …
  ]
}
```

## 7. Policy levers (where simulation shines)

- **Carbon price / ETS**: already in the model (`impact_prices`, ETS markets).
  Per variant, carbon cost = Σ emissions × price. **Sweep** the price and find the
  **break-even** where a green variant becomes the cheaper choice — a single,
  decision-grade number.
- **Emission cap / regulation**: check each variant against an `impact_caps` limit
  (e.g. a regulatory gCO₂/veh) → compliant / over by X. Show the cap a variant
  *unlocks*.
- **Other regulation**: subsidies / fees map onto stream prices or per-impact
  prices; same evaluation, different inputs.

## 8. Phasing

| Phase | Scope | Status |
|---|---|---|
| **P1** | `SimulationBackend` registered; evaluate the **baseline (as-is) configuration**; return the per-stage LCA inventory + cost incl. carbon cost; tests. | ✅ shipped (#111) |
| **P2** | Variants + **A vs B comparison**: abatement, cost delta, $/impact-unit, break-even carbon price. Override ops `set_machine_tech` · `set_price` · `set_carbon_price` · `toggle_measure`. | ✅ shipped |
| **P3** | **Policy sweep** (parametric carbon price) + **cap-compliance** vs `impact_caps`; **use-phase** is an ordinary authored process (no engine change), reported as its own stage. | ✅ shipped |
| **P4** | Frontend: an LCA results view (per-stage bars, by-impact, A-vs-B comparison, policy-sensitivity curve, cap compliance) + a simulate setup screen (baseline · variants · sweep), driven by the existing method picker. | ✅ shipped |

**Use-phase authoring convention** (P3 decision: *a real `Use` process in the
model*). To extend a model from cradle-to-gate to cradle-to-grave, add a `Use`
stage like any other: a company node + machine whose technology **consumes the
product** (e.g. one car) and **emits** the in-use impact (fuel / grid CO₂ over the
asset's life), with demand placed on the use-stage output (the service, e.g.
`mobility`). It then appears in `by_stage` automatically — see
`tests/backends/test_simulation_backend.py::test_use_phase_process_is_a_lifecycle_stage`.
The model must supply the per-product use-phase emission factor; the engine does
not invent it.

## 9. Open questions (for review)

1. **Phase granularity** — is per-company-stage enough, or do we want the explicit
   four-phase rollup (materials/manufacturing/use/end-of-life) in P1?
2. **Use phase** — model it as a process now (P1/P3), or keep cradle-to-gate and
   let users add a use process themselves?
3. **Override vocabulary** — which `op`s to support first (`set_machine_tech`,
   `toggle_measure`, `set_price` cover most asks).
4. **Baseline definition** — P1 uses "as-is" (transitions stripped + measures off).
   *Direction (confirmed): the optimiser's output is the simulator's input.* See
   §10 — the canonical baseline is a **frozen optimisation result**, and the
   simulator gets its **own setup** for perturbing it. P1's "as-is" is just the
   trivial default until that setup lands.

## 10. TODO — dedicated simulation setup (optimise → simulate handoff)

> Deferred. Captured here so it isn't lost; **not** in P1.

Selecting `simulate` should switch to **its own setup**, distinct from the
optimisation setup — because a simulation needs a *fixed configuration to
evaluate*, not a target to optimise toward. The pieces:

- **The optimiser's result IS the simulator's input.** The natural baseline is a
  **frozen optimisation pathway**: run `linopy`, take its chosen technologies /
  transitions / measures / flows, and hand that whole plan to `simulate` as the
  starting configuration. ("Optimise once → freeze → ask what-if.")
- **Interventions are events on that frozen plan.** The simulation setup lets the
  user pin changes as **timed events**, e.g. *"replace machine X with tech Y in
  year T"*, *"this stream switches source / price in year T"*, *"adopt measure M
  from year T"* — then re-evaluate and diff against the frozen baseline.
- **A different setup screen.** When the method is `simulate`, the run UI should
  present this configuration/event editor (and a baseline picker: as-is · a saved
  optimisation result · a manual config) instead of the optimisation targets/caps
  setup. The two lenses share the model but not the setup.

This supersedes the simple `variants[]`/`overrides[]` sketch in §5 for the *UI*
layer; the override vocabulary (§5, open Q3) is the underlying mechanism the event
editor compiles down to.
