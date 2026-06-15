# Facility transitions

A **transition** lets a facility switch the technology it runs over time — e.g. a
blast furnace converting to H2 direct reduction as carbon prices rise. It is the
explicit, capex-bearing alternative to running several machines in parallel.

## Data

`transitions` sheet — one row per allowed switch:

| Column | Meaning |
|---|---|
| `from_technology` | the technology a facility currently runs (any facility on it may switch) |
| `to_technology` | the target technology (must exist in `technologies` + its `io`) |
| `action` | `replace` (default) · `renew` · `continue` |
| `capex_per_capacity` | one-off switching cost per unit capacity |

Optional levers on the technologies themselves shape *when* a switch may happen:
`introduction_year` (earliest a target may be adopted) and `phase_out_year`
(forces leaving a technology after a year).

## How it solves

- Each process has a binary "active technology" per period; period 0 is **locked**
  to the baseline (the earliest a switch can occur is the second period).
- A switch trips a transition **event** variable and incurs
  `capex_per_capacity × capacity` in that period.
- A rising carbon price (`impact_prices`) and/or a tightening cap (`impact_caps`)
  are what make a costlier-but-cleaner target win.

## The wiring caveat (important)

Connection edges form off a machine's **baseline** technology's `io` (see
[valuechain.md](valuechain.md)). So a stream the target technology introduces —
e.g. hydrogen for H2-DRI when the baseline is a blast furnace — will **not** be
delivered by a value-chain connection unless either:

1. the baseline already lists that input (give it a *token* amount so the edge
   forms — the `green_steel` example gives its blast furnace a tiny `hydrogen`
   co-injection so the cross-border H2 connections wire to it, then the BF→H2-DRI
   transition draws real hydrogen), or
2. the stream is **purchasable** (a `markets` row / commodity `price`), so the
   switched facility buys it.

## Example

In `green_steel_chain`, the integrated mill carries two transitions —
`BlastFurnace → H2_DRI` (iron-making) and `BOF → EAF` (steel-making). Under the
rising carbon price + declining CO₂ cap, the solve fires `BF → H2-DRI` in 2030,
drawing hydrogen from the Australian / Qatari / Korean producers via the value
chain. See also [macc.md](macc.md) (cheaper partial abatement that competes with
switching) and [alternatives.md](alternatives.md).
