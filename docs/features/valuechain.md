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
- **Right pane** — the selected item's wiring: for a group, its purchasing
  (markets) + targets (demand); for a machine, **how each required input stream
  is satisfied** (by a connection or a purchase). The recipe itself is *not*
  edited here — that's the Component tab.
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
| `valuechain` | in series, upstream → downstream, coupled via price / carbon signals |
| `joint` | all selected units solved together |
| `independent` | each unit on its own, trading only with markets |

## Where an imported scenario lands

On import the structure (nodes / connections / machines) populates this view,
while the component details populate the Component view's per-session library —
see [scenarios.md](scenarios.md).
