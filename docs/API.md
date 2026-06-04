# API contract — the frontend ↔ backend boundary

This contract is the **only** coupling between the frontend and the backend.
Anything that serves it can replace the backend; anything that speaks it can
replace the frontend. Keep it small and stable.

Principles:

- **Stateless backend.** The backend reads no files and stores no data. All
  data originates in the frontend (user-defined) and is sent in the request;
  the entire result is returned in the response.
- **One true source per config domain.** *Server-side* config (solver limits,
  job concurrency, logging) lives in the backend and is surfaced by
  `GET /api/config`. *User-definable* model config (discount rate, carbon
  price, lifetimes, toggles, solver tuning) lives in the frontend and is sent
  inside the scenario on every run.
- **Minimal chatter.** The only data payloads exchanged are: the **model**
  (sent on run) and the **entire result** (received once the job is done).
  Workbook parsing and result export are client-side.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness (used by the launcher) |
| GET | `/api/status` | `{ ready, buildId, version }` |
| GET | `/api/config` | **handshake** — backend's one true source (below) |
| POST | `/api/run` | send `{ model, scenario, options }` → `{ jobId, status }` |
| GET | `/api/run/{id}` | poll → `running`, or `done` + **entire result**, or `error` |
| DELETE | `/api/run/{id}` | cancel a running job |

### `GET /api/config` (handshake)

```jsonc
{
  "schemaVersion": "1.0",
  "version": "0.1.0",
  "domains": [ { "name": "shipping", "label": "Shipping Fleet",
                 "terminology": {...}, "requiredSheets": [...], "schema": {...} } ],
  "backends": [ { "name": "linopy", "label": "linopy + HiGHS",
                  "solver": "HiGHS", "features": {...} } ],
  "server": { "solver": "highs", "maxSolverTimeLimitS": 1800, "defaultMipGap": 0.01 },
  "buildId": "<content hash for client-side caching>"
}
```

No model-parameter defaults appear here — those are the frontend's.

### `POST /api/run`

```jsonc
{
  "model":    { "<sheet>": [ { "<col>": <value>, ... }, ... ] },   // the workbook
  "scenario": { "domain": "shipping", "selection": {...},
                "economics": {...}, "features": {...}, "solver": {...},
                // optional bilevel mode: search the emission pathway itself
                "outer": { "enabled": true, "method": "anneal|sweep",
                           "max_iterations": 60, "sweep_steps": 11,
                           "floor_fraction": 0.3, "seed": 42 } },
  "options":  { "domain": "shipping", "backend": "linopy" }
}
```

### `GET /api/run/{id}` (when done) — the entire result

```jsonc
{
  "jobId": "...", "status": "done",
  "result": {
    "status": "optimal | infeasible | invalid | error",
    "objective": <number|null>,
    "validation": { "errors": [...], "warnings": [...] },   // folded in, no separate call
    "terminology": {...},
    "outputs": { "chosen_technology": [...], "carrier_energy": [...],
                 "transitions": [...], "new_builds": [...], "measures": [...], "slack": [...] },
    "summary": { "periods": [ { "period", "energy_mj", "emissions_tco2e",
                                "intensity_gco2e_per_mj" } ] },
    // present only for bilevel runs (scenario.outer.enabled):
    "pathway_search": { "method", "objective", "groups": [...],
                        "evaluations": <int>,
                        "pathway": [ { "year", "limit" } ],          // chosen sector cap
                        "bounds": { "upper": [...], "floor": [...] },
                        "frontier": [ {...} ] }                       // per-evaluation trace
  }
}
```

If the workbook fails validation the run returns `status: "invalid"` with the
errors in `validation` — no separate validate round-trip.

## Generic workbook (the `model`)

Data tables, snake_case sheets. Required: `assets`, `technologies`, `carriers`,
`carrier_compatibility`, `periods` (+ `targets` for emission limits). Optional:
`baseline_mix`, `transitions`, `measures`, `new_build_options`, `carbon_price`,
`carrier_cost`, `emission_intensity`, `meta`. Column contracts are documented in
`src/pathwise/data/assemble.py`. A sector pack supplies the schema/terminology
(see `GET /api/config`); the frontend renders and edits it.
