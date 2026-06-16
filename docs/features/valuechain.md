# Value chain — structure, connections, optimisation

The **Value chain** view (the `V` tab) is about how building blocks **connect** —
the structure and the commodity flows between them. The *details* of each block
(recipes, streams, measures) live in the [Component view](components.md); here you
wire and solve.

## The hierarchy (structure)

The model is a tree of **nodes** (`nodes` sheet): a `value_chain` root → groups
(country / company / facility, free-text `level`) → **machines** (leaves). Each
machine runs one baseline technology (`machines` sheet) and becomes one process
at solve time — a facility is the sum of its machines, so it can run several
technologies in parallel.

- **Left pane** — the structure tree (right-click to add subgroup / component /
  target / connection; drag to re-parent).
- **Centre pane** — the *relationship canvas* for the selected group: its direct
  children and the connections between them. Drill by selecting a deeper group.
- **Right pane** — the selected item's detail. A **single technology** shows its
  full recipe: every **input** and **output** stream with its per-unit
  coefficient and *who provides / consumes it* (the connected group, a purchase,
  or final demand), plus impacts and the years it is available — so a technology
  that buys electricity reads as wired, not floating. A **group** gets the
  lighter Flow context + its purchasing/targets. (The recipe is *edited* in the
  Component tab; here it's shown for wiring.)
  - **Flow context** — a compact "feeds in (before) / feeds out (next)" list, so
    even a lone machine shows what connects to it. It reads every connection
    touching the node *or an ancestor* (so a country-level link shows on the
    machine inside), filtered to commodities the node actually produces/consumes.
    When one input commodity has **more than one source**, they're tagged
    *N alternatives* — that's how you spot a competing/substitutable supply (see
    [alternatives.md](alternatives.md)).

## Connections (commodity flows)

A **connection** (`connections` sheet: `from_node`, `to_node`, `commodity_id`,
`lag_years`) routes a stream between two nodes. At solve time each connection
expands to machine→machine **edges**: every leaf machine in `from_node`'s subtree
that *outputs* the commodity is wired to every leaf machine in `to_node`'s subtree
that *inputs* it.

> **Important:** edges form off each machine's **baseline** technology's `io`. A
> stream a machine only consumes *after* a transition won't be wired unless the
> baseline already lists it (give the baseline a token input, or make the stream
> purchasable). See [transitions.md](transitions.md) and
> [alternatives.md](alternatives.md).

A commodity that no sibling produces can still be satisfied by **purchasing** it
(a `markets` row, or a `price` on the commodity) — this is how imports and raw
inputs enter the chain.

## Optimisation scope

The toolbar's **optimise at** selects the level whose items become optimisation
units; **solve** picks how they're coupled:

| `optimisation_scope` | meaning |
|---|---|
| `system` | one joint problem over the whole model |
| `company` / `facility` / any `level` name | partition at that level |

| `optimisation_mode` | meaning |
|---|---|
| `valuechain` | in series, upstream → downstream, coupled via price / carbon / volume signals |
| `joint` | all selected units solved together |
| `independent` | each unit on its own, trading only with markets |

## Coupling signals (value-chain mode)

When two stages are connected by a `CouplingLink` (defined in `data/valuechain.py`),
an upstream stage's solved result feeds into the downstream stage's inputs. Each link
declares which **signals** to pass — a subset of:

| Signal | What is transferred | How it is injected |
|---|---|---|
| `price` | Average cost of the commodity upstream [currency / unit] | Upserted as the downstream commodity's purchase price trajectory (`commodities_t__price`) |
| `marginal_price` | True marginal cost (finite-difference on demand) — takes precedence over `price` when both requested | Same price injection |
| `carbon_intensity` | Upstream emissions per unit of the commodity [impact unit / commodity unit] | Injected as the downstream commodity's carbon intensity trajectory (a year-varying `commodity_impacts` override) |
| `volume` | Upstream produced quantity of the commodity [commodity unit / yr] | Injected as a per-year cap on the downstream stage's total external purchase (`Σ_p buy[p,r,t] ≤ max_purchase_r(t)` via `commodities_t__max_purchase`) |

The `volume` signal is the supply-availability coupling: the downstream stage can buy
at most as much as the upstream stage produced. It is implemented in
`core/valuechain.py::_volume_signal` / `_inject_volume` and enforced in
`core/build.py::_purchase_caps` via `Commodity.max_purchase_by_year`.

All signals are shifted forward by the link's `lag_years` and interpolated onto the
downstream horizon.

### Configured in `ScenarioConfig.coupling`

```jsonc
"coupling": {
  "signals": ["price"],         // which signals all links pass (default); overridden per link
  "iterations": 1,              // 1 = forward-only; >1 enables feedback fixed-point
  "damping": 0.5,               // relaxation on fed-back demand
  "default_lag": 0              // lag applied when a link sets none
}
```

## Reading the result on the map (chain over time)

A run is drawn **on the same process map as the model** — there is no separate
result view. A **year slider** appears above the canvas; scrubbing it steps the
whole chain through the horizon. For the selected year each machine node shows
its **active technology** (highlighted, with a `⇄`, in the year it transitions)
and its throughput, and each link shows the **flow** carried that year (idle
machines / links dim out). The per-stage status + objective table stays below.
Both joint (`system`) and cascade (`value_chain`) runs annotate the map this way —
the result's process ids are the machine-node ids.

## Where an imported scenario lands

On import the structure (nodes / connections / machines) populates this view,
while the component details populate the Component view's per-session library —
see [scenarios.md](scenarios.md).
