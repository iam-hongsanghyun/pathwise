# Alternatives & substitution — import ↔ domestic, competing supply

> *"How do I define existing vs alternative machines? A connection to production
> is one-way. How do I model an entire import country being replaced by domestic
> production?"*

You don't need a special construct. The optimiser already expresses alternatives
through the **commodity balance**: several producers feeding the same commodity to
a consumer, with the least-cost mix chosen each period. A connection isn't
"one-way" in aggregate — *multiple* connections summing into one balance is the
substitution.

## Pattern A — parallel producers (the default)

Put both sources in the chain and connect **both** to the same consuming stream:

- an **import** node (e.g. `AU iron ore`) → consumer, commodity `iron_ore`;
- a **domestic** node (e.g. `KR iron ore`) → consumer, commodity `iron_ore`.

The consumer's balance is `produced + inflow + bought = consumed + …`, so both
inflows sum and the optimiser splits volume by cost. As the carbon price rises or
an import is capped, flow shifts from one to the other — "the import is replaced
by domestic production" emerges; no binary needed. `green_steel_chain` already
does this with hydrogen: Australian (green), Qatari (blue) and Korean (green)
producers all feed the Korean mill's `hydrogen` balance and compete.

## Levers to shape the choice

| Want | Use |
|---|---|
| an import quota / capacity limit | a `markets` row with `max_buy` (or `max_flow` on a connection) |
| a phased switch at a point in time | a [transition](transitions.md) `import_tech → domestic_tech` (switch capex + `introduction_year`) |
| make imports lose over time | rising commodity `price` / carbon (`impact_prices`, `commodity_impacts`) |
| outsource a whole step | make its output **purchasable** (a market) instead of produced |

## How to *add* an alternative in the value chain

Alternatives are a **value-chain** choice — they are *not* baked into the
Component library (a technology there is defined purely on its own). Select a
machine in the Value-chain view; its right pane has an **Alternatives (optimiser
may switch to)** section listing the technologies the machine can switch to, with
a searchable picker drawing from the pool of *all* library technologies (base +
this scenario's). Adding one:

- merges that technology's recipe (its `io` + referenced streams) into the
  session model, and
- records a `transitions` row `baseline → alternative` (the engine's switch
  mechanism — see [transitions.md](transitions.md)).

Remove an alternative with the ✕. Because it's a transition, the choice is
*tech-level*: every machine running the same baseline shares the alternatives.
The optimiser then runs whichever route is cheapest under the carbon price / cap.
(Adding the same recipe to two parallel machines and connecting both to a
consumer — pattern A above — remains the way to model a continuous split.)

## How to *see* an alternative in the UI

There's no special "alternative" line — an alternative is simply **one consumer
commodity with more than one source**. Select the consuming node and read its
**Flow context** (right pane, Value-chain view): each input commodity lists its
source nodes, and any commodity with multiple sources is tagged *N alternatives*.
E.g. selecting the Korean mill shows `hydrogen: Australia, Qatar · 2 alternatives`
— the optimiser picks the least-cost split.

## Existing vs "alternative" machines

A facility is the sum of its machines and a process can carry several feasible
technologies. So "an alternative machine" is just **another machine (or
technology) producing the same commodity** — model both and let the balance / the
transition decide. A machine's *required inputs* are wired in the Value-chain view
(connection or purchase); its recipe is defined in the [Component view](components.md).

## What is **not** built in

- A hard **mutually-exclusive** choice ("import **XOR** domestic, never both").
  The LP blends; forcing exclusivity needs binary / big-M variables (a MILP),
  which the model doesn't add today. Workaround: run separate scenarios, or cap
  one source to zero.
- **Relative** share caps ("imports ≤ 50 % of supply by 2035"). Absolute caps are
  expressible (`max_buy`); relative ones would need new constraints.

There is a reserved `CouplingLink.alternative_of` marker in the value-chain spec
for true either/or alternatives; it is **not yet** wired into the solver. If you
need hard exclusivity, that's the place it would go — ask and we'll scope it.
