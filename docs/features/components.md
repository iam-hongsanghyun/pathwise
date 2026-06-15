# Component builder

The **Component** view (the `C` tab) is where you author the reusable *building
blocks* of a model. It is deliberately separate from the **Value chain** view:

- **Component view** = the *details* of each building block — recipes, streams,
  abatement measures. The "what things are."
- **Value chain view** = how building blocks *connect* — the structure and the
  commodity flows between them. The "how things are wired."

A component **library** is a named, self-contained catalogue of these blocks. The
left rail lists every library; expanding one reveals its three fixed structures:

```
<library>
├── Technology      one recipe each: inputs / outputs / impacts + linked MACCs
├── Stream          the commodities, grouped by owning sector (see below)
└── Measures
    ├── MACC         a named bundle of measures (a marginal-abatement curve)
    └── Individual   the reusable measures themselves
```

Right-click any node for add / rename / delete; edits autosave to the library.

> **Note.** There is no longer a separate "Components" section. A composite unit
> *is* a technology placed as a machine in the Value-chain view, so the old
> Components list duplicated Technology and was removed — the builder is
> **technology-only**.

## Technology

A technology is a recipe. It carries:

| Field | Meaning |
|---|---|
| `technology_id` | unique recipe id |
| `lifespan` | asset life in years (drives renewal scheduling) |
| `capex` | replacement capital cost, per unit capacity |
| `opex` | operating cost, per unit throughput |
| `io` | the input / output / impact rows (see below) |
| `maccs` | the MACCs that apply to this technology |

Each **io** row is `{target, role, coefficient, …}`:

- `role: "input"` — consumes `coefficient` units of the `target` stream per unit
  throughput. Optional `group` + `share_min/share_max` make it a **blend group**
  (the optimiser picks the mix within bounds — e.g. coal/gas/H₂ fuel switching).
- `role: "output"` — produces `coefficient` units; `is_product: true` marks a
  final deliverable (demand can be placed against it).
- `role: "impact"` — emits `coefficient` units of an impact (e.g. `CO2`) per unit
  throughput.

## Stream (commodities) — grouped by owning sector

A stream is a commodity that technologies consume or produce:

| Field | Meaning |
|---|---|
| `commodity_id` | unique stream id |
| `kind` | `energy` · `material` · `indirect` · `product` · `byproduct` |
| `unit` | display unit (`t`, `MWh`, `GJ`, …) |
| `price` | external purchase price (blank ⇒ not buyable, must be produced) |
| `sale_price` | external sale price for surplus |
| `sector` | **owning sector** — see below |

### What "sector" means

A stream belongs to the sector that **produces** it, not the one that consumes
it. Electricity is a **power** stream even though steel mills consume it — it is
*from* the power sector. So in the tree, streams are grouped under their owning
sector:

```
Stream
├── General        industry-agnostic streams (no sector set yet)
├── energy         coal, gas
├── power          electricity
├── hydrogen       hydrogen
├── steel          iron, steel, scrap, hbi
└── mining         iron_ore
```

Leave `sector` blank for a **general** stream — one not (yet) tied to a specific
industry. Sector is purely organisational: it groups streams in this view and is
ignored by the optimiser, so re-classifying a stream never changes a result.

Adding a stream from inside a sector group pre-assigns that sector; adding from
the top-level **Stream** node (or the library) creates a General stream.

## Measures & MACC

A **measure** is a retrofit/abatement lever:

- `type: "energy_efficiency"` → `target` is a *stream*; the measure reduces
  consumption of that stream.
- `type: "emission_reduction"` (or `environmental`) → `target` is an *impact*
  (e.g. `CO2`); the measure reduces that impact directly.
- `blocks` is the stepwise curve: each block has a `reduction` fraction and a
  `capex_per_capacity` (+ optional `opex_per_capacity`), adopted cheapest-first.

A **MACC** bundles measures by id. A technology lists the MACCs that apply to it;
placing that technology stamps every measure of those MACCs onto the resulting
machine, with block costs scaled to the machine's capacity.

## Where libraries live

- **Base / bundled libraries** ship with pathwise (`assets/component_libraries/`)
  and seed a writable copy on first run; they are the shared, reusable catalogue.
- **Per-scenario libraries** (phase 2) — each imported scenario carries its own
  components library, loaded alongside the base set, so a scenario's specific
  recipes don't pollute the shared catalogue.

See [scenarios.md](scenarios.md) (phase 2) for how an imported scenario routes its
component *details* here and its value-chain *structure* to the Value-chain view.
