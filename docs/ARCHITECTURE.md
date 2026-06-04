# ARCHITECTURE

```
frontend (React + React Flow)  ──HTTP──▶  api (FastAPI, stateless)
                                              │
                                      backends (linopy + HiGHS)
                                              │
            data (schema/assemble/validate) ─▶ core (process-network MILP, no I/O)
```

- **Stateless contract.** The frontend sends `{model, scenario, options}` to
  `POST /api/run` and polls `GET /api/run/{id}` for the entire result. The backend
  reads no files and owns no data.
- **core/** is pure: workbook → `Problem` → `linopy` model → solve → result dict.
  No sector vocabulary, no I/O.
- **data/** owns the workbook schema and the workbook↔problem assembly.
- **Designer ⇄ tables.** The frontend keeps one `workbook` object; the React Flow
  designer and the editable tables are both controlled views over it, bridged by
  pure `graphToWorkbook` / `workbookToGraph` functions.

> Status: scaffolding; expanded as P1–P6 land.
