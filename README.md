# pathwise

**General-purpose multi-period process/asset transition optimiser.**

`pathwise` finds the least-cost pathway for a fleet of *assets* to meet
activity demand and emission targets over a multi-year horizon, choosing among:

- **Technology transitions** — retrofit an existing asset to a different technology (e.g. an engine/fuel switch), at a capital cost.
- **MACC efficiency measures** — adopt energy-efficiency / abatement measures (piecewise marginal-abatement-cost blocks) on top of a technology.
- **New-build options** — purchase new assets (fleet renewal / capacity expansion).

All capital costs are properly discounted (capital-recovery-factor annuity or
NPV), and emission / carbon-price policy is fully data-driven.

The engine is **domain-agnostic**. A *sector pack* maps a sector's vocabulary
onto the generic model. **Shipping** ships as the first pack; adding a new
sector (e.g. **steel**) means adding one folder under
`src/pathwise/domains/` — the core, the solver, the API, and the frontend are
untouched.

## Architecture

```
core/      generic optimisation model — no I/O, no sector vocabulary
domains/   sector packs (shipping, …) + DomainPack registry
data/      generic workbook assembly, scenario, validation, imputation
results/   solution extraction + per-period summary
backends/  pluggable solver backends (linopy + HiGHS)
api/       FastAPI web application (stateless: config handshake + run)
frontend/  React + TypeScript web UI — owns all data and user config
```

- **Solver:** [linopy](https://linopy.readthedocs.io) + [HiGHS](https://highs.dev).
- **Isolation:** frontend and backend are coupled by **one HTTP contract only**
  (`docs/API.md`); either is replaceable. The backend is **stateless** — all data
  comes from the frontend; xlsx parse/export happen client-side. See
  [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Run the app

```bash
./run.command      # installs deps if needed, starts backend + frontend, opens the browser
```

Then pick a sector, click **Load sample** (or upload your own `.xlsx`), set the
scenario, and **Run**. Stop with Ctrl-C.

To convert a legacy shipping workbook into the generic format (offline tool):

```bash
uv run python tools/migrate_shipping_to_generic.py path/to/Reference.xlsx out.xlsx
```

## Develop

```bash
uv sync --all-extras          # backend deps
uv run pytest                 # backend tests
uv run ruff check . && uv run mypy src/
(cd frontend/pathwise_default && npm install && npm run build)  # frontend
```

See [`docs/ALGORITHM.md`](docs/ALGORITHM.md) for the formulation,
[`docs/API.md`](docs/API.md) for the HTTP contract,
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the isolation model, and
[`docs/DOMAINS.md`](docs/DOMAINS.md) for adding a sector pack.
