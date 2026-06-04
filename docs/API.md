# API & data schema (skeleton)

> Filled out as Phases 2–5 land. This file documents (a) the canonical generic
> workbook schema, (b) the JSON scenario format, and (c) the HTTP contract.

## Generic workbook (Excel)

Data tables, snake_case sheets, wide-year time series.

**Required:** `meta`, `assets`, `technologies`, `carriers`,
`carrier_compatibility`, `baseline_mix`, `periods`, `cost_trajectories`,
`targets`.

**Optional / feature-gated:** `measures` (MACC), `transitions`,
`new_build_options`, `emission_intensities`, `blend_bounds`,
`carrier_limits`, `class_limits`, `carbon_price`.

`meta` carries `schema_version`, `domain`, `base_period`, and per-column pint
unit declarations (`key="unit:carriers.cost"`, `value="USD/MJ"`).

_(Column-level definitions: TODO Phase 2.)_

## JSON scenario (run definition)

The workbook holds data; the scenario holds the *run definition* — which named
sets to use, feature toggles, economics, cost components, solver options,
horizon. _(Schema: TODO Phase 2, pydantic `ScenarioConfig`.)_

## HTTP endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness |
| GET | `/api/status` | startup warm + build_id |
| GET | `/api/config` | ConfigBundle (schema, domains, backends, defaults, build_id) |
| GET | `/api/domains` | list sector packs + capabilities |
| GET | `/api/domains/{id}/schema` | one pack's workbook schema + terminology |
| GET | `/api/backends` | solver backends + capabilities |
| POST | `/api/validate` | validate `{model, scenario}` → report |
| POST | `/api/workbook/parse` | upload `.xlsx` → `{model:{sheet:rows[]}}` |
| POST | `/api/run` | start async job → `{jobId}` |
| GET | `/api/run/{id}` | poll → running / done+result / error |
| DELETE | `/api/run/{id}` | cancel |
| POST | `/api/export/xlsx` | results → workbook bytes |
| GET/DELETE | `/api/log` | in-process log ring buffer |

_(Request/response models: TODO Phase 5.)_
