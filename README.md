# pathwise

**Process-network cost-optimisation model with a visual designer.**

`pathwise` finds the least-cost, multi-year transition pathway for a network of
production **facilities** (machines). Each machine consumes **energy, material, and
indirect resources** to make **products** while emitting multiple **environmental
impacts** (CO₂, SOₓ, NOₓ, …). The optimiser (a MILP, solved with HiGHS) chooses,
per year, among:

- **Technology lifecycle** — `continue` / `renew` / `replace`, with a build/close
  active window and market availability windows per technology.
- **Energy-efficiency MACC**, **emission-reduction MACC**, and **environmental
  measures** — piecewise marginal-cost curves.
- what to **buy and sell** on each market stream,

driven by cost curves plus a **carbon price / ETS**, priced per impact, under
demand, emission caps, and budgets.

### The three layers

pathwise is built on a strict separation — see
**[docs/USER_MANUAL.md](docs/USER_MANUAL.md)** for the full guide:

- **Component** — a *technology* template (recipe, intensities, costs, lifespan,
  availability). Edited in the **Library**.
- **Facility** — a *machine*: a private, fully-editable copy of a component plus
  real-world data (capacity, owner, build/close year, output bounds). Edited in the
  **Facility** tab. Most values are static **or** year-varying (temporal).
- **Value chain** — the *market*: who supplies which stream to whom, at what price,
  with per-link flow limits.

> **First time?** Start with **[docs/USER_MANUAL.md](docs/USER_MANUAL.md)** — open
> a bundled example, run it, and learn the *edit → run → read* loop.

A web designer (React Flow + editable tables) builds the structure, recipes, and
market wiring visually, two-way synced with the model.

## Architecture

```
src/pathwise/
  core/      process-network MILP — no I/O (entities, constraints, objective, build, extract)
  data/      workbook schema, assembly, validation, scenario
  backends/  pluggable solver backends (linopy + HiGHS)
  api/       FastAPI app (stateless: config handshake + run)
frontend/    Vite + React + TypeScript (React Flow designer)
```

- **Solver:** [linopy](https://linopy.readthedocs.io) + [HiGHS](https://highs.dev).
- **Backend-centric:** the backend owns the model — xlsx parse/export, the working-model
  store, the example workbooks, and the template library all live server-side. The browser
  is a thin client (it persists only a session id) and never parses spreadsheets.

## Develop

```bash
uv sync --all-extras
uv run pytest
uv run ruff check . && uv run mypy src/
```

## Run the app

```bash
./run.command          # backend (uvicorn) + frontend (Vite); opens the browser
```

## Documentation

| Doc | For |
|---|---|
| [docs/USER_MANUAL.md](docs/USER_MANUAL.md) | **Start here** — a first-time user's guide to the tabs, the editor, and the *edit → run → read* loop. |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the pieces fit: the Component / Facility / Value-chain layers, storage, the backend-owns-the-model pattern. |
| [docs/ALGORITHM.md](docs/ALGORITHM.md) | The optimisation model — sets, decision variables, objective, every constraint family. |
| [docs/AUTHORING.md](docs/AUTHORING.md) | Authoring bundled components, value chains, and example workbooks by hand (the sheet schema). |
| [docs/API.md](docs/API.md) | The HTTP API surface (`/api/*`). |
| [docs/HANDBOOK.md](docs/HANDBOOK.md) | Team conventions, code-review checklist, project standards. |
