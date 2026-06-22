# pathwise — user manual

A guide for someone opening pathwise for the first time. It explains what the tool
does, the three layers it is built on, and how to go from a blank screen to a
solved least-cost transition pathway.

> New here? Read **[1. What pathwise is](#1-what-pathwise-is)** and
> **[3. Your first 10 minutes](#3-your-first-10-minutes)**, then keep the
> **[tab reference](#5-the-tabs)** open as you work.

---

## 1. What pathwise is

pathwise finds the **least-cost, multi-year pathway** for a network of production
facilities — which technologies to run, build, renew or replace each year, what to
buy and sell, and which retrofit measures to adopt — subject to demand, emission
caps, budgets, and a carbon price. You describe the world; the optimiser (a MILP
solved with HiGHS) chooses the cheapest way to meet it over the horizon.

It is **domain-agnostic**: steel, power, hydrogen, petrochemicals, shipping — all
the same machinery. Nothing in the engine is sector-specific; a "sector model" is
just data.

## 2. The three layers (read this once)

Everything in pathwise is one of three things. Keeping them straight is the key to
using the tool well.

| Layer | Is a… | Holds | Where you edit it |
|---|---|---|---|
| **Component** | a **technology** (a reusable template) | the recipe and defaults: inputs/outputs and their intensities, efficiency, impacts, lifespan, capex, renewal, opex, availability | **Library** tab |
| **Facility** | a **machine** (one real instance of a technology) | a private, fully-editable copy of a component **plus** real-world facts: capacity, owner, build/close year, output bounds | **Facility** tab |
| **Value chain** | the **market** | who supplies which stream to whom, at what price, and per-link flow limits | **Value chain** tab |

Three rules follow from this:

1. **A Component is a template.** Editing a component changes the catalogue, not
   any machine already placed.
2. **A Facility machine is its own copy.** When you place a component as a machine,
   it copies the component's defaults; from then on you can edit *every* value of
   that machine independently — two machines from the same component can have
   different capex, efficiency, lifespan, etc.
3. **The Value chain only wires what exists.** It connects and prices machines and
   streams that the Facility layer already defines; it never invents technology
   data.

## 3. Your first 10 minutes

```bash
./run.command      # starts the backend + web app and opens your browser
```

Then, the fastest way to learn the tool is to **open a bundled example**:

1. Go to the **Project** tab.
2. Under *Start from an example*, pick e.g. **Green steel — AU/Qatar → Korea**.
3. The whole model loads — components, facilities, and a wired value chain.
4. Go to **Targets & constraints** and press **Run (▶)** to solve, then open
   **Analytics** to read the charts.
5. Now go to **Facility**, expand the tree to a machine (e.g. the mill's blast
   furnace), and look at its editor — this is where per-machine data lives.
6. Change something (a cost, an efficiency), re-run, and watch the pathway shift.

That loop — *edit → run → read* — is the whole tool.

## 4. Building a model from scratch

If you are not starting from an example, the natural order is left-to-right
through the tabs:

1. **Library** — define your technologies (components): their input/output streams
   and intensities, costs, lifespan, and which actions they allow
   (continue / renew / replace). These are reusable templates.
2. **Facility** — build the structure (sectors → companies → facilities) and **place
   technologies as machines**. Each placement is an independent instance you then
   fill in: capacity, build/close year, and any per-machine overrides of the
   component's values.
3. **Value chain** — wire the machines together (who sends which stream to whom),
   set market prices, and per-link flow limits.
4. **Targets & constraints** — set production targets/demand, emission caps,
   carbon price, and investment budgets (scoped to the whole system, a company, or
   a single machine), then press **Run (▶)** to solve.
5. **Analytics** — read the results.

## 5. The tabs

| Tab | What it's for |
|---|---|
| **Project** | Name the workspace; start from an example; import/export the whole project as one self-contained bundle. |
| **Library** | The component catalogue — define/edit technology templates, streams, and MACC measures. |
| **Facility** | The real-world structure and **per-machine editor** (see §6). |
| **Value chain** | The market map — connect machines, set prices and per-link stream limits. Machine facts shown here are read-only (edit them in Facility). |
| **Targets & constraints** | Production targets, emission caps, carbon price, budgets — by scope. **Run the solve (▶)** from here. |
| **Analytics** | Read the results (pathway, costs, emissions, trades). |
| **Settings** | Scenario, economics (discount rate, capex convention), and design options. |

Top bar: **Undo** (Ctrl/Cmd+Z), **New** (empty model), **Clear** (wipe all session
data and start fresh).

## 6. The Facility editor (where most of your time goes)

Select a machine in the Facility tree and the editor opens in four zones:

- **Technology** (top-left) — this machine's own copy of the component: lifespan,
  available-from / available-to, replace capex, renewal cost, opex, min capacity
  factor. *Editing here does not affect other machines.*
- **Machine** (bottom-left) — capacity (the fixed nameplate), owner, build year,
  close year, max capacity factor, max renewals.
- **Input streams** (top-right) — each input's intensity, per unit of output.
- **Products & emissions** (bottom-right) — output yields, emission factors, and
  the machine's annual output floor/ceiling.

Each zone scrolls on its own, and you can drag the dividers to resize the
columns and the top/bottom split.

### Static vs temporal values

Most numbers can stay **static** (one value for the whole horizon) or vary over
time (**temporal**). Fields that support this are shown as a **green inline value**;
click it to open a popup where you either keep one value or set a year-anchored
trajectory (a few `(year, value)` points + a Linear or Step fill rule).

A plain **input box** means the field is direct/static-only — capacity (a fixed
nameplate), lifespan, the build/close/availability years, owner, and max renewals.

Every numeric field shows its **physical unit** (e.g. `MWh/t` for an electricity
intensity, `t/yr` for capacity, `/t` for opex).

## 7. Key concepts

### Technology lifecycle — continue / renew / replace

Each year a machine can:

- **continue** — keep running its current technology (free), while a live vintage
  covers it;
- **renew** — rebuild the same technology at its renewal cost (resets its life),
  if the technology allows it and the machine's **max renewals** budget isn't spent;
- **replace** — switch to a different technology, paying that technology's capex.

At end of life a machine **must** renew or replace (it can't keep running a
worn-out asset for free). Replacing early carries its cost implicitly (you pay the
new technology's capex; a new build's old capex is already sunk).

### Active window and availability

- **Build year / close year** define when the *machine* physically exists. It is
  off before the build year and off **from** the close year (close is *exclusive*:
  close 2038 ⇒ runs through 2037). This overrides the technical lifespan.
- **Available-from / available-to** define when a *technology* may be used in the
  market — e.g. coal `available-to = 2040` means it's unusable from 2040 (a
  phase-out). Available-to is *exclusive* too.

### Cost vs profit

By default each company **minimises cost** to meet a demand floor. Switch a company
to **profit** (in the optimisation settings) and demand becomes the maximum it may
sell, with revenue entering the objective — producing less is then allowed.

### Solving a value chain

A value chain can be solved jointly (one big problem), per-company as a forward
cascade (upstream prices/intensities flow downstream), or each unit independently.
Choose the mode in Settings / the optimisation scope.

## 8. Tips & troubleshooting

- **Demand can't be met → "slack".** If the model can't satisfy demand (e.g. a
  machine is closed and nothing replaces it), it reports unmet demand as slack
  rather than failing. Check capacities, build/close years, and availability.
- **Editing an example machine's recipe.** Bundled examples may share a technology
  across machines; new machines you place get independent copies. If an edit seems
  to affect a "sibling," it's a shared example template.
- **Start over.** *New* gives an empty model (undoable); *Clear* wipes all session
  data (not undoable).
- **Export to keep it.** Use **Project → Export** to save the whole model
  (components + facilities + value chain) as one file you can re-open or share.

## 9. Where to go next

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — how the pieces fit (layers, storage, the
  backend-owns-the-model pattern).
- **[ALGORITHM.md](ALGORITHM.md)** — the optimisation model: variables, objective,
  every constraint family.
- **[AUTHORING.md](AUTHORING.md)** — authoring bundled components, value chains, and
  example workbooks by hand.
- **[API.md](API.md)** — the HTTP API.
