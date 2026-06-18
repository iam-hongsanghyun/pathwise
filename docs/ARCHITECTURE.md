# ARCHITECTURE

```
frontend (React + React Flow)  ──HTTP──▶  api (FastAPI)
                                              │
                                      backends (linopy + HiGHS)
                                              │
            data (schema/assemble/validate) ─▶ core (process-network MILP, no I/O)
```

- **Backend-centric (ragnarok pattern).** The working model lives server-side in a
  **session**. The frontend holds only a `sessionId`; it reads pages of sheets via
  `GET /api/session/{id}/sheet/{name}` and writes patches via
  `PATCH /api/session/{id}/sheet/{name}`. File parsing, xlsx export, and example
  loading all happen server-side. A run is submitted by `sessionId` via
  `POST /api/run`.
- **core/** is pure: workbook → `Problem` → `linopy` model → solve → result dict.
  No sector vocabulary, no I/O.
- **data/** owns the workbook schema, the workbook↔problem assembly, and the
  component library / value-chain data models.
- **Designer ⇄ tables.** The frontend keeps a local view of the session model.
  `workbookToGraph` (`frontend/…/lib/graph.ts`) converts the workbook into React
  Flow nodes and edges for the canvas. The reverse direction is **not** a single
  mirror function — mutations are applied through a set of targeted functions:
  `persistLayout`, `placeEntity`, `unplace`, `deleteEntity`, `addFacilityWithTech`,
  `deleteChain`, `addTransitionOption`, and others, each patching one aspect of the
  workbook in place. The patched workbook is then pushed to the session via
  `PATCH /api/session/{id}/sheet/{name}`.

## Storage / persistence

| Layer | Format | Location | Purpose |
|---|---|---|---|
| Working sessions | SQLite (`.db`) | `data/sessions/*.db` | Server-held editable model per browser session |
| Component libraries (shared) | SQLite (`.sqlite`) | `data/component_libraries/*.sqlite` | User-editable shared catalogue; seeded from bundled starters on first run |
| Component libraries (per-session) | SQLite (`.sqlite`) | `data/session_libraries/<sid>/*.sqlite` | Scenario-specific components; isolated from the shared catalogue |
| Bundled component library seeds | JSON | `src/pathwise/assets/component_seeds/*.json` | Read-only starters; converted to SQLite on first run |
| Bundled example workbooks | SQLite (`.sqlite`) | `src/pathwise/assets/examples/*.sqlite` | Pre-built example models; read server-side and loaded into a session |
| Bundled value-chain specs | JSON | `src/pathwise/assets/value_chains/*.json` | DAG-of-stages definitions for coupled multi-stage runs |

JSON files are the **immutable bundled source**. SQLite is the **mutable working/persistence layer**. There are no CSV files anywhere in the persistence stack.

## Configuration

Environment variables (prefix `PATHWISE_`, loaded from `.env` via `config.py`):

| Variable | Default | Purpose |
|---|---|---|
| `PATHWISE_CORS_ORIGINS` | `["*"]` | Allowed CORS origins; set an explicit list for shared deployments |
| `PATHWISE_SOLVER_NAME` | `"highs"` | Solver passed to the backend; HiGHS is the only currently registered solver |
| `PATHWISE_DATA_DIR` | `"data"` | Root for sessions, component libraries, session libraries |
| `PATHWISE_HOST` / `PATHWISE_PORT` | `127.0.0.1` / `8077` | Serving address |

All variables and their defaults are documented in `.env.example`.
