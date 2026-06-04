# pathwise frontend

A lean React + TypeScript (Vite) web UI for the pathwise optimiser.

## What it does

- Loads the config bundle (`/api/config`) and lets you pick a **sector** (shipping today; any registered pack).
- Upload an `.xlsx` workbook (parsed via `/api/workbook/parse`); edit any sheet inline.
- Configure the **scenario** — target set, discount rate, CAPEX convention, and feature toggles (transitions, MACC measures, new builds, carbon price, capital cost).
- **Validate** the workbook and **Run** the optimisation as an async job (submit → poll → result).
- View the per-period energy/emissions summary and the technology-transition decisions; **export** the result to `.xlsx`.

## Develop

```bash
npm install
npm run dev        # http://127.0.0.1:5173 (proxies /api → :8000)
npm run build      # type-check (tsc) + production build
npm run typecheck  # tsc --noEmit only
```

The dev server proxies `/api` to the backend (default `:8077`, overridable via
the `PATHWISE_BACKEND_URL` env var — `../../run.command` sets it automatically so
the ports never drift). A sample workbook to upload ships in `public/` and is
loadable from the **Load sample** button.
