# Architecture — isolation & replaceability

pathwise is two independently-replaceable halves joined by one HTTP contract
(`docs/API.md`).

```
┌─────────────────────────────┐         ┌──────────────────────────────────┐
│  Frontend (any client)      │  HTTP   │  Backend (any solver service)     │
│  frontend/pathwise_default  │ ──────► │  src/pathwise/api                 │
│                             │ /api/   │                                   │
│  • owns ALL data            │ config  │  • STATELESS (no files, no data)  │
│    (upload/edit/sample)     │ + run   │  • owns server-side config only   │
│  • owns user model config   │ ◄────── │  • pluggable solver backends      │
│    (defaults.ts)            │ result  │  • pluggable sector packs         │
│  • parses/exports xlsx      │         │                                   │
└─────────────────────────────┘         └──────────────────────────────────┘
```

## What lives where

| Concern | Home | Why |
|---|---|---|
| Workbook data (assets, fuels, …) | **Frontend** | user-defined; uploaded/edited/sampled client-side |
| Model config (discount rate, carbon price, lifetimes, toggles, solver tuning) | **Frontend** (`src/defaults.ts`) | user-definable; sent in the scenario |
| xlsx parse / export | **Frontend** (`src/workbook.ts`, SheetJS) | keeps the backend file-free |
| Sector schemas + terminology | **Backend** (domain packs) | the engine's source of truth; handshaked via `/api/config` |
| Solver backends + capabilities | **Backend** (registry) | engine truth; handshaked |
| Solver resource limits, job concurrency, logging | **Backend** (`config.py` / `.env`) | server-side; operator-controlled |

Rule of thumb: **server-side → backend; user-definable → frontend.** Each value
has exactly one home, so there is no config to keep in sync.

## Replaceability

- **Swap the backend:** implement `GET /api/config` and `POST /api/run` +
  `GET/DELETE /api/run/{id}` (any language/solver). The frontend needs no change.
- **Swap the frontend:** call those two endpoints. The backend needs no change.
- **Add a sector** (e.g. steel): drop `src/pathwise/domains/steel/` + one
  `register_domain` call — core, shipping, solver, API, frontend untouched. It
  then appears in `/api/config` and the frontend's sector selector. See
  `docs/DOMAINS.md`.
- **Add a solver backend:** implement the `Backend` protocol and
  `register_backend` — it appears in `/api/config`.

## Communication discipline

The frontend sends the model once and receives the whole result once. There is
no incremental fetching of config fragments or partial results; status polling
is a thin transport detail, not a data channel. This keeps the system suited to
a server-hosted deployment where round-trips are costly.
