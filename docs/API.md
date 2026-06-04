# API

Minimal, stateless HTTP surface.

- `GET  /api/health` — liveness.
- `GET  /api/config` — handshake: schema version, domains, backends, server limits.
- `POST /api/run` — body `{model, scenario, options}` → `{jobId}`.
- `GET  /api/run/{id}` — poll → the entire result (validation folded in).
- `DELETE /api/run/{id}` — cancel.

```jsonc
// POST /api/run
{
  "model":    { "<sheet>": [ { "<col>": <value>, ... } ] },   // the workbook
  "scenario": { "selection": {...}, "economics": {...}, "features": {...}, "solver": {...} },
  "options":  { "domain": "process", "backend": "linopy" }
}
```

> Status: scaffolding; result schema finalised at P3.
