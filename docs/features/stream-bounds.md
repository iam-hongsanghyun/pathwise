# Stream bounds & temporal values — min/max on every flow

Every flow in the model can carry a **minimum** and a **maximum**, and every
such bound can be **static** (one value for the whole horizon) or **temporal**
(a value that varies by year). This page explains the mental model, the four
bound families, where you set each in the UI, and how they reach the optimiser.

It complements [valuechain.md](valuechain.md) (wiring) and
[alternatives.md](alternatives.md) (competing supply).

---

## 1. The mental model: products vs the pooled commodity

A commodity flows from producers to consumers. Two perspectives matter:

- **An output stream is a _product_** — a commodity *tagged to the producer that
  makes it*. Each producer machine owns its output, so an output bound is set
  **per producer** (it is that machine's own production limit).
- **An input stream is a _commodity_** — the **pool** of that product gathered
  from *all* providers. A consumer draws from the pool.

So a buyer has **two independent levers** on an input:

1. **Per-producer** — how much to buy from *each* provider (e.g. ≤ X from Wind
   farm, ≥ Y from the grid). Same commodity, different limit per source.
2. **Per-commodity (pooled)** — how much of the commodity to take in **in total**,
   summed across all providers.

There is **no separate "pool" commodity**: the commodity *is* the pool, and each
provider→buyer **connection** is its tagged channel. Two providers of the same
commodity are two connections that cap independently and both feed the one
commodity that the pooled bound governs.

---

## 2. The four bound families

| Bound | What it limits | Scope (key) | Sheet(s) | Engine constraint |
|---|---|---|---|---|
| **Production** (output) | how much a machine **produces** of a commodity | machine node + commodity | `min_production`, `max_production` (+ `_t__amount`) | `Σ deliver ≥ min` / `≤ max` |
| **Consumption** (input, pooled) | how much a machine **takes in** of a commodity (all providers) | machine node + commodity | `min_consumption`, `max_consumption` (+ `_t__amount`) | `Σ gross_consumed ≥ min` / `≤ max` |
| **Connection flow** (input, per-provider) | how much flows on **one** provider→buyer link | from_node + to_node + commodity | `connections` (static cols), `connections_t` (long) | per-edge `flow ≥ min_flow` / `≤ max_flow` |
| **Supply cap** (source stream) | how much of a **bought-in** raw stream may be purchased externally | commodity | `commodities.max_purchase`, `commodities_t__max_purchase` | external `buy ≤ max_purchase` |

Plus the **availability window** (`available_from` / `available_to` on
`commodities`): the years a source stream may be bought at all (outside the
window, external `buy = 0`).

### Consumption: required offtake vs max purchase

For an **input** the two consumption bounds read as:

- **`min_consumption` = required offtake** — a take-or-pay floor: the machine
  *must* consume at least this much of the commodity.
- **`max_consumption` = maximum purchase** — an intake ceiling.

These are limits on the **consumer**. They are distinct from the *provider's*
own supply limit (that is the provider's **production** bound) and from the
machine's **capacity** (its nameplate throughput).

---

## 3. Where you set each (UI)

### Machine popup — the recipe rows (Value chain → click a machine)

Each recipe row (one per input/output stream) shows its min/max in aligned
`[name | min | max]` columns. Values render as **small clickable text** (the
static number, or a trend marker like `↗ 6 yr`); click to open the editor.

```
IN  electricity   50 MWh   min none         max no cap        ← pooled commodity (consumption)
    ← Wind farm             ↗ 6 yr MWh/yr    200 MWh/yr        ← per-producer (connection flow)
    ← CCGT                  none             no cap            ← per-producer
OUT hydrogen      1 t       min no floor     max no cap        ← production
```

- **Output row** → the machine's **production** bounds (`min/max_production`).
- **Input row** → the **pooled commodity** bounds (`min/max_consumption`): *min
  offtake* / *max purchase*.
- Under each input, one row **per provider** (`← Wind farm`, `← CCGT`) → the
  per-producer **connection flow** bounds. If a provider link is wired at a
  higher level (e.g. a company-level `Korea Power → Korea Steel`), it appears in
  the child machine's popup as `← Korea Power → Korea Steel`, and editing it caps
  the *company's* purchase on that shared link.
- **Capacity** + **CO₂ intensity** sit below as the machine's own limits.

### Source-stream inspector (Value chain → click a source node)

A **source stream** (consumed by the chain, produced by none) shows its
**purchase price**, an editable **max supply / yr** (the supply cap, static or
temporal), and editable **available from / until** years. When a producer *is*
wired to the stream it is no longer a pure source; internal production then
follows the producer's build/close years and the purchase window only gates
external buying.

### Connection editor (Value chain → click an edge → ✎)

The same per-provider min/max **offtake** can also be set directly on a
connection. The popup and the connection editor write the **same** stores, so a
bound edited in one place shows in the other.

### Optimisation constraints (Targets & constraints tab)

System- or company-wide production floors/ceilings, demand targets, emission
caps and budgets. Each constraint is **one row** with a static-or-temporal
value (no more one-row-per-year). `company = "all"` ⇒ economy-wide.

---

## 4. Static vs temporal — the value editor

Click any min/max (or a constraint value) to open the editor:

- **Static** — one number applied to every modelled year.
- **By year** — a small set of **anchors** (type any year + value), a **horizon
  range** (`from → to`, defaulting to the run periods), and a **fill rule**:
  - **Linear** — straight-line ramp between anchors.
  - **Step** — hold each anchor's value until the next.
  - Outside the anchor span the value is flat-held.

A live preview shows the resulting trajectory. **On save** the editor
*materialises* the fill onto the model's run periods within the range → one row
per period, so what you see is exactly what the engine solves. **On re-open** the
dense rows are *compressed* back to the minimal anchor set and the linear/step
shape is auto-detected, so editing stays clean (six flat rows re-open as two
anchors; a 50→10 ramp re-opens as two Linear anchors).

> **Storage note.** A bound has two mutually-exclusive stores: static writes the
> scalar column / a year-less row; temporal writes the per-year rows (or the wide
> `_t__amount` / `connections_t` sheet). Setting one clears the other.

> **Interpolation nuance.** The `min/max_production` and `min/max_consumption`
> sheets treat per-year rows as **exact** (a lone year row does **not** spread to
> other years; a *year-less* row is the base for every year). The editor sidesteps
> this by materialising a value for every period. The `connections_t`,
> `edges_t` and `commodities_t__*` sheets are **interpolated** (linear, flat-held
> ends) like all other trajectories — so a single year row there flat-holds to the
> whole horizon; author a row per period to vary it (again, what the editor does).

See [`../AUTHORING.md` §3](../AUTHORING.md) for the full temporal-sheet reference.

---

## 5. How it reaches the optimiser

Scope resolution: a bound's scope (the `company` / node-id column) is matched by
`Process.in_scope` — `"all"`, the machine's own node id, its company, its group,
or any ancestor in its hierarchy chain. So a cap scoped to a facility binds every
machine under it; one scoped to a machine node binds just that machine.

Engine constraints (`core/build.py`):

- **Production**: `Σ_{p∈scope} deliver_{p,q,t} ≥ min_production` / `≤ max_production`.
- **Consumption**: `Σ_{p∈scope} gross_consumed_{p,q,t} ≥ min_consumption` /
  `≤ max_consumption`. `gross_consumed` is the machine's intake of `q` (the
  `fin` mix flow for blend-group members, else `intensity·throughput`), summed
  over providers.
- **Connection flow**: a node-space `connections_t` row is fanned by
  `_expand_hierarchy` onto every synthesized `from_process→to_process` **edge**;
  the edge then binds `flow ≥ min_flow_at(t)` / `≤ max_flow_at(t)` per period.
- **Supply cap**: outside `commodities.max_purchase` / over the year's
  interpolated value, external `buy` is bounded; outside the availability window
  `buy = 0` (the `nobuy` mask via `Commodity.available(t)`).

Because consumption is tied to throughput via the recipe, a consumption bound on
a **single-input** machine behaves like a production bound scaled by intensity.
It earns its keep on **blend groups** (substitutable inputs): capping one
member's intake forces the optimiser onto the others — e.g. cap coal → it burns
H₂ instead. See `tests/core/test_consumption_bounds.py` and
`tests/core/test_temporal_flow_bounds.py` for worked least-cost examples.

---

## 6. Not yet (roadmap)

- **Strictly machine-specific per-provider limits.** Today a per-provider bound
  lives on the connection at whatever level it is wired; a company-level link is
  shared by every machine under it. Machine-specific limits need machine-to-machine
  connections.
- **Per-machine max capacity factor** (an output ≤ `maxcf · capacity` ceiling).
  The engine has a must-run *floor* (`mincf`) but no max-CF cap yet.
- **Lag + quality change between flows** — e.g. a car returning as lower-grade
  scrap years later (a recycling loop with a time lag and a commodity transform).
- **Availability windows as alternatives** — multiple sources of one commodity
  with different availability windows treated as an alternative-supply set.
