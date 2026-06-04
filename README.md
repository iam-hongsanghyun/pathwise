# pathwise

**Process-network cost-optimisation model with a drag-and-drop designer.**

`pathwise` finds the least-cost, multi-year transition pathway for a network of
production **processes** (facilities/machines). Each process consumes **energy,
material, and indirect resources** to make **products** while emitting multiple
**environmental impacts** (CO₂, SOₓ, NOₓ, …). The optimiser chooses among:

- **Technology transitions** — `replace` / `renew` / `continue`, with up/down-stream
  consequences (an incompatible replacement forces connected processes to change;
  reusable kit lets them stay).
- **Energy-efficiency MACC**, **emission-reduction MACC**, and **environmental
  measures** — piecewise marginal-cost curves.
- driven by cost curves plus **carbon price / ETS**, priced per impact.

A **React Flow** web designer lets you build the facility network, MACC curves, and
transition options visually, two-way synced with editable data tables.

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
- **Stateless backend:** all data arrives in the request; the whole result returns in
  the response. xlsx parse/export is client-side.

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
