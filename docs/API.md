# API

Stateless HTTP surface. All routes are prefixed `/api`.

## Health / config

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness check; returns `{"status": "ok"}`. |
| `GET` | `/api/config` | Handshake: schema version, available domains, backends, server limits. |

## Run

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/run` | Submit a run (by `sessionId` or inline model); returns `{jobId, status}`. |
| `GET` | `/api/run/{job_id}` | Poll for result; returns the full result dict when complete. |
| `DELETE` | `/api/run/{job_id}` | Cancel a running job. |

`POST /api/run` body:

```jsonc
{
  "sessionId": "<sid>",           // use the server-held session model (preferred)
  // OR
  "model": { "<sheet>": [...] },  // inline workbook (legacy / testing)
  "scenario": { ... },            // ScenarioConfig (see below)
  "options":  { "backend": "linopy" }
}
```

## Session

The backend owns the working model (the ragnarok pattern). The browser holds only
a `sessionId`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/session` | Create a fresh session; returns `{sessionId}`. |
| `POST` | `/api/session/model` | Ingest a full workbook into a (new or existing) session. |
| `POST` | `/api/session/{id}/clear` | Reset a session to an empty model. |
| `GET` | `/api/session/{id}/model` | Fetch the whole session workbook. |
| `GET` | `/api/session/{id}/sheet/{name}` | One page of a sheet (params: `offset`, `limit`). |
| `PATCH` | `/api/session/{id}/sheet/{name}` | Batch-apply edits (set / addRow / deleteRows / replace). |
| `POST` | `/api/session/{id}/workbook` | Parse an uploaded `.xlsx` and replace the session model. |
| `GET` | `/api/session/{id}/export` | Download the session model as `.xlsx`. |
| `POST` | `/api/export/result` | Flatten a run result into a downloadable `.xlsx`. |

## Examples

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/examples` | The example-library index. |
| `POST` | `/api/session/{id}/example/{example_id}` | Load a bundled example into the session; returns `{sessionId, sheets, library_id}`. |

## Component libraries (shared base catalogue)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/component-libraries` | List all shared component libraries (id, label, counts). |
| `GET` | `/api/component-library/{lib_id}` | One library's full content. |
| `PUT` | `/api/component-library/{lib_id}` | Create or overwrite a component library. |
| `DELETE` | `/api/component-library/{lib_id}` | Delete a component library. |

## Component libraries (per-session / scenario set)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/session/{id}/component-libraries` | List the session's own component libraries. |
| `GET` | `/api/session/{id}/component-library/{lib_id}` | One session library's full content. |
| `PUT` | `/api/session/{id}/component-library/{lib_id}` | Create or overwrite a session library. |
| `DELETE` | `/api/session/{id}/component-library/{lib_id}` | Delete a session library. |

## Alternatives & component placement

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/session/{id}/technologies` | All technologies across base + session libraries (the "add alternative" picker pool). |
| `POST` | `/api/session/{id}/alternative` | Add a technology from a library as a switch option for a machine. |
| `POST` | `/api/session/{id}/instantiate` | Stamp a component (from a library) into the session hierarchy under a parent node. |
| `POST` | `/api/session/{id}/place-technology` | Place a single technology as a machine node under a parent. |

## Value chains

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/value-chains` | The value-chain index. |
| `GET` | `/api/value-chain/{name}` | One value-chain spec (stages + links). |
| `POST` | `/api/value-chain/{name}/run` | Solve the chain as a forward cascade; returns per-stage results + coupling trajectories. |

---

## ScenarioConfig shape

Sent as the `"scenario"` key in `POST /api/run` (all fields optional; defaults shown).

```jsonc
{
  "name": "scenario",
  "domain": "process",
  "economics": {
    "discount_rate": 0.08,
    "base_year": null,            // null → first horizon year
    "capex_convention": "npv"     // "npv" | "annuity"
  },
  "cost_components": {
    "capex": true,
    "renewal": true,
    "opex": true,
    "commodity_cost": true,
    "impact_price": true,
    "measure_capex": true
  },
  "solver": {
    "name": "highs",
    "threads": 4,
    "time_limit_s": 600.0,
    "mip_gap": 0.01,
    "seed": 42
  },
  "horizon": {
    "start": null,                // null → all workbook years
    "end": null
  },
  "slack_penalty": 1e9,
  "portfolio": { ... },           // only used by the "portfolio" backend
  "coupling": {
    "signals": ["price"],         // subset of "price","marginal_price","carbon_intensity","volume"
    "iterations": 1,
    "damping": 0.5,
    "default_lag": 0
  },
  "optimisation_scope": "company",    // "system" | "company" | "facility" | any level name
  "optimisation_targets": [],         // node ids at the scope level; empty → all
  "optimisation_mode": "valuechain"   // "valuechain" | "joint" | "independent"
}
```

`economics.capex_convention` controls how a capital outlay enters the objective — see
[ALGORITHM.md](ALGORITHM.md) (economics/discounting section).
