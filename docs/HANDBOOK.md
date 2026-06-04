# Handbook

Team standards for `pathwise`. The authoritative conventions are in
[`CLAUDE.md`](../CLAUDE.md); this file expands on a few that need detail.

## Tooling

```bash
uv sync --all-extras          # install
uv run pytest                 # tests
uv run pytest --cov=src       # tests + coverage
uv run ruff check . --fix     # lint + autofix
uv run ruff format .          # format
uv run mypy src/              # type-check
```

`pyproject.toml` is the single source of truth — no `setup.py`,
`requirements.txt`, `flake8`, or `black` config.

## Conventions (summary)

- Python 3.11+, type hints on public functions, Google-style docstrings.
- Math docstrings carry an `Algorithm:` section: LaTeX (`$$…$$`) primary plus an
  ASCII fallback line; define every symbol with units.
- Single-letter names are fine when they mirror the equations (`T`, `x`, `dt`).
- No hardcoded values — load via `src/pathwise/config.py` from `.env`; mirror
  every var into `.env.example`.
- Use `pint` for physical quantities at module boundaries.
- Reproducibility: `numpy.random.default_rng(seed)`; commit `uv.lock`.
- Numerical changes: add a test against an analytical solution or a captured
  baseline (`np.testing.assert_allclose` with explicit `rtol`/`atol`).

## Layout

```
src/pathwise/
  core/       generic algorithms (no I/O, no sector vocabulary)
  domains/    sector packs + registry
  data/       loaders, validators, transforms
  results/    extraction, post-calc, export
  backends/   pluggable solver backends
  api/        FastAPI app
  config.py   loads .env, validates types
  logger.py   centralised logging
  units.py    pint registry
tests/        mirrors src/
docs/         ALGORITHM.md (math), API.md (schema+HTTP), DOMAINS.md (packs)
```

## Git workflow

- Feature branch → PR → CI green → merge to main → delete branch.
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`.
- For math changes, paste before/after equations into the PR description.
- Never force-push to main; use `git revert` to undo merged commits.
