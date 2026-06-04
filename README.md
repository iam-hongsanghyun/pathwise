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
data/      workbook + JSON-scenario loading, validation, imputation
results/   solution extraction, post-calculation, Excel export
backends/  pluggable solver backends (linopy + HiGHS)
api/       FastAPI web application (async solve jobs)
frontend/  React + TypeScript web UI (workbook editor, run, visualise)
```

- **Solver:** [linopy](https://linopy.readthedocs.io) + [HiGHS](https://highs.dev).
- **Input:** Excel workbook (data tables) + JSON scenario (run definition).
- **Frontend:** browser app — upload/edit a workbook, pick a sector and scenario, run, and visualise.

## Quick start

```bash
uv sync --all-extras          # install (Python)
cp .env.example .env          # configure
uv run pytest                 # tests
uv run ruff check .           # lint
uv run mypy src/              # type-check
```

## Run the app

```bash
uv sync --all-extras                       # backend deps
(cd frontend/pathwise_default && npm install)  # frontend deps
./run.sh                                   # backend :8000 + frontend :5173
```

Open http://127.0.0.1:5173, pick a sector, upload a workbook (a sample is at
`data/sample_kss_line.xlsx`), set the scenario, and Run. To convert a legacy
shipping workbook into the generic format:

```bash
uv run python tools/migrate_shipping_to_generic.py path/to/Reference.xlsx data/fleet.xlsx
```

See [`docs/ALGORITHM.md`](docs/ALGORITHM.md) for the mathematical formulation,
[`docs/API.md`](docs/API.md) for the data schema and HTTP contract, and
[`docs/DOMAINS.md`](docs/DOMAINS.md) for how to add a new sector pack.
