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

## Model layers: Component · Facility · Value chain

Three layers with **strictly separate concerns** — a technology's physics, a
specific machine's economics, and the market it trades in. Do not mix them.

| Layer | Is a… | Owns | Capacity |
|---|---|---|---|
| **Component** | Technology (general, machine-agnostic) | **Every** technical value that defines the technology: input requirements & intensities, output yields & intensities, efficiency, direct-impact factors, lifespan, replacement capex, **renewal cost**, opex, allowed actions | `1` (a unit technology) |
| **Facility** | Machine (one instance of a technology) | **Everything inherited from its component, editable per machine** (the same technology can have different capex / renewal cost / efficiency / intensities), **plus** the machine-specific facts: capacity, build year, close year, replace capex, renewal cost, `max_renewals`, `max_capacity_factor`, min/max output, required input/output streams + their intensities | per-machine (set here) |
| **Value chain** | Market (who trades what with whom) | Stream connections (who provides which commodity to which consumer), buy/sell **prices**, and per-link input/output **stream limits** | — |

Rules:

- The **component schema must carry every field**, including the machine-specific
  ones — they sit empty/default at the component level (it is a template). A
  facility is a component with those fields filled in and any inherited value
  overridden.
- **Fixed machine/technology facts never live in the value chain.** Not renewal
  cost, not `max_renewals`, not capacity, not `max_capacity_factor` — those are
  properties of the machine (facility), set once.
- Boundary cases: **`max_capacity_factor` → machine (facility)**, not market.
  Input/output **stream limits → market (value chain)**. Intensities/requirements
  → technology (component) with per-machine override (facility). Renewal
  cost / capex → component default + facility override; never value chain.

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
