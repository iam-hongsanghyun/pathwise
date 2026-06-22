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

Optional levers shape *when* a technology may be used (its market-availability
window): `introduction_year` (available-from, **inclusive** — earliest it may be
adopted) and `phase_out_year` (available-to, **exclusive** — unusable *from* that
year, so `phase_out_year = 2040` means the technology is gone by 2040).

Technology-level fields relevant to lifecycle tracking:

| Field | Meaning |
|---|---|
| `lifespan` | Asset economic lifetime [yr]; drives end-of-life enforcement and the annuity-convention sum |
| `renewal_by_year` | Year-keyed renewal cost [currency / unit capacity]; charged when the same technology is rebuilt at end of life |
| `actions` | Allowed transition actions for this technology (`replace` / `renew` / `continue`); `renew` here gates whether rebuilds are *possible* at all |

Process- / machine-level fields:

| Field | Meaning |
|---|---|
| `introduced_year` | **Build year** [yr]; the machine is *off before it*, and it sets the install date for lifecycle ageing |
| `decommission_year` | **Close year** [yr], **exclusive** — the machine is off *from* this year (runs through `decommission_year − 1`). With the build year it forms the **active window** `[build, close)`, which overrides the technical lifespan |
| `max_renewals` | Per-machine cap on the **total number of renewals** over the horizon: `0` = no renewal (must replace at end of life), `N` = at most `N` rebuilds then must replace, blank = unlimited |

## How it solves

- Each process has a binary "active technology" per period; period 0 is **locked**
  to the baseline (the earliest a switch can occur is the second period).
- A switch trips a transition **event** variable and incurs
  `capex_per_capacity × capacity` in that period.
- A rising carbon price (`impact_prices`) and/or a tightening cap (`impact_caps`)
  are what make a costlier-but-cleaner target win.

## Asset end-of-life renewal

When a process declares `introduced_year`, pathwise enforces **lifecycle tracking**:
a technology may be active only while a *live vintage* covers it.

- The original baseline install covers year `t` while `t < introduced_year + lifespan`.
- A replacement (a `replace` event in year `t'`) starts a new `lifespan`-year window from `t'`.
- A **renewal** (a `renew` event in year `t'`) rebuilds the *same* technology, resets
  the vintage window, and charges `Technology.renewal_by_year` × capacity (rather
  than the full `capex_by_year`).

Once the live vintage lapses, the process must **renew**, **replace**, or switch off.
A machine's **`max_renewals`** caps how many times it may rebuild before it must
replace (`Σ_t ren ≤ max_renewals`); separately, the **build/close active window**
forces it off outside `[introduced_year, decommission_year)` regardless of vintage.
The constraint is:

```
u[p,k,t]  ≤  live0[p,k,t]  +  Σ_{t-L < t' ≤ t} refresh[p,k,t']
```

where `live0 = 1` if `k` is the baseline and `t < introduced_year + L`; `refresh`
is the renewal (`ren`) variable for baseline rebuilds, and `w + ren` for replacement
targets. See [ALGORITHM.md](../ALGORITHM.md) section 4 for the full formulation.

Processes that do **not** set `introduced_year` are completely unaffected — all
existing scenarios without install dates are unchanged.

Renewals appear in the result as `outputs.renewals` (list of
`{process, technology, period}`) and per-year renewal cost appears in
`summary.periods`.

### Capex convention for renewals

Renewal cost uses the same `economics.capex_convention` as replacement capex —
either a discounted NPV lump (`"npv"`, the default) or a capital-recovery-factor
annuity over the asset life (`"annuity"`). Set via
`ScenarioConfig.economics.capex_convention`. See [ALGORITHM.md](../ALGORITHM.md)
section 3b for the math.

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
   switched facility buys it externally. See [alternatives.md](alternatives.md)
   ("outsource a whole step — make its output purchasable via a market/price")
   for a worked example of this pattern.

## Example

In `green_steel_chain`, the integrated mill carries two transitions —
`BlastFurnace → H2_DRI` (iron-making) and `BOF → EAF` (steel-making). Under the
rising carbon price + declining CO₂ cap, the solve fires `BF → H2-DRI` in 2030,
drawing hydrogen from the Australian / Qatari / Korean producers via the value
chain. See also [macc.md](macc.md) (cheaper partial abatement that competes with
switching) and [alternatives.md](alternatives.md).
