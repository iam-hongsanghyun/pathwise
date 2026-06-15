# MACC — marginal abatement cost curves

A **MACC** is a set of incremental abatement **measures** a facility can adopt,
cheapest-first. Unlike a [transition](transitions.md) (a wholesale technology
switch), measures are partial retrofits — the optimiser dials each one in as far
as it's worth under the carbon price / cap.

## Data

**`measures`** — the lever:

| Column | Meaning |
|---|---|
| `measure_id` | unique id (per-facility instances are `"<node> · <measure>"`) |
| `type` | `energy_efficiency` (cuts a *stream*) or `emission_reduction` / `environmental` (cuts an *impact*) |
| `target` | the stream id (energy_efficiency) or impact id (emission_reduction) it reduces |
| `facility` | the node it applies to |
| `lifetime` | measure life in years |

**`measure_blocks`** — the stepwise curve for a measure:

| Column | Meaning |
|---|---|
| `measure_id` | parent measure |
| `block` | step order (0, 1, 2 …), adopted in order |
| `reduction` | fraction (0–1) of the target removed by this block |
| `capex` | one-off cost of the block |
| `opex` | recurring cost while adopted |

In a **component library** the same thing is authored as reusable
`MeasureTemplate`s with `capex_per_capacity` / `opex_per_capacity` blocks, bundled
into named **MACCs** (`MaccGroup`); a technology lists the MACCs that apply to it,
and placing it stamps each measure onto the machine with block costs scaled to
the machine's capacity. See [components.md](components.md).

## How it solves

Each (measure, facility) gets its own adoption level per period, monotonic over
time, blocks cumulative. `reduction` applies to a **fixed baseline reference**
(not live throughput), keeping the model linear.

## Modeling note: what `reduction` actually cuts

A measure only reduces its `target`:

- `type: energy_efficiency`, `target: <stream>` → cuts consumption of that stream
  (and thus any cost / upstream emissions tied to producing it).
- `type: emission_reduction`, `target: CO2` → cuts that impact directly.

So if emissions are modeled as a **per-throughput technology impact** (an `io`
row with `role: "impact"`), an *energy-efficiency* measure on the fuel will **not**
reduce them — the impact isn't tied to that fuel's quantity. To abate such
emissions, use an `emission_reduction` measure on the impact. (`green_steel`'s
blast-furnace MACC is `emission_reduction` on `CO2` for exactly this reason; its
plant-electricity efficiency measures cut grid emissions *indirectly*, by reducing
electricity demand.)

## Where MACCs come from on import

An imported scenario's per-facility measures are recovered into its session
component library as reusable templates (de-duplicated by base id) — see
[scenarios.md](scenarios.md).
