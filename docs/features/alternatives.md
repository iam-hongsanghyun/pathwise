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
