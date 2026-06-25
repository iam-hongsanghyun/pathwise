# Generic rename — current → new (owner-confirmed)

Rename pathwise's domain vocabulary to generic, sector-neutral terms. **Scope: UI +
data layer** (sheet names, columns, API, TS — not just labels). Owner-confirmed
2026-06-25.

## Final mapping

| Current | New | Layers touched |
|---------|-----|----------------|
| machine / `machines` sheet / `machine_id` / `kind="machine"` | **Asset** / `assets` / `asset_id` / `kind="asset"` | data + engine + API + TS + UI |
| Component (Library tab) | **Template** | UI (no sheet) |
| Facility (tab) | **System** | UI (no sheet) |
| value chain / `valuechain.py` / `ValueChainSpec` / `run_value_chain` | **Network** / `network.py` / `NetworkSpec` / `run_network` | code + UI |
| connection / `connections` sheet | **Link** / `links` | data + engine + API + TS + UI |
| stream **+** commodity / `commodities` / `commodity_id` | **Flow** / `flows` / `flow_id` (UNIFIED) | data + engine + API + TS + UI — **widest blast radius** |
| measure / `measures` / `measure_id` / `measure_blocks(_t)` | **Lever** / `levers` / `lever_id` / `lever_blocks(_t)` | data + engine + API + TS + UI |
| `optimisation_scope: "system"` (whole-model) | relabel **"Model"** | UI label (value stays `"system"` internally) |
| brand "PROCESS VALUE-CHAIN OPTIMISER" | **"PROCESS NETWORK OPTIMISER"** | UI string |
| technology, impact, fleet, `nodes`, `processes`, `edges`/`Edge`, `routes` | **KEEP** | — |

### Decisions / collisions resolved
- **`nodes` ≠ asset:** `nodes` = structure (groups + asset leaves); `assets` (was
  `machines`) = economics; joined by id. "node" stays the umbrella term. `machine`
  could not become `nodes` (taken) → **Asset**.
- **commodity → Flow is FULL** (column `commodity_id`→`flow_id` too) per owner. Note
  the internal `flow` decision variable (quantity on a link) coexists with the new
  `flows` sheet (substances) — different namespaces, acceptable.
- **connection → Link, NOT edge:** `connections`→`links`. The flat-model `edges`/
  `Edge` primitive (what the `flow` var runs on, ~0 examples) stays internal as
  "edge". A physicalised link with geography stays a **route** (`routes`).
- **System vs system-scope:** Facility tab → "System"; the whole-model optimisation
  scope relabels to **"Model"** so the two don't clash.
- **technology→process rejected** (collides with `processes` sheet) → technology KEPT.

## Back-compat (no binary migration)
A `normalize_workbook(wb)` at the load boundary (backend `assemble_problem` +
`validate`; frontend on model adopt) maps OLD sheet/column/kind names → NEW. The 13
example `.sqlite` files and existing user models keep loading untouched; models
re-saved by the UI migrate to new names. Idempotent (new names pass through).

## Execution order (each its own green commit: `npm run build` + `uv run pytest`)
1. ~~Stage 1 — headline UI labels~~ ✅ shipped 0b24c98.
2. **Foundation** — `data/aliases.py` `normalize_workbook` + wire into assemble/validate + frontend adopt. (Map seeded empty; grows per term.)
3. **measure → Lever** (smallest, ~50 files, no kind change, no collision) — proves the pattern.
4. **machine → Asset** (`kind` value change → ~dozen frontend tree checks; back-compat kind alias).
5. **connection → Link**.
6. **commodity+stream → Flow (FULL)** — biggest; likely 2 commits (sheets/engine, then API/TS/frontend).
7. **Sweep** — remaining inline UI strings (kind badges, legends, helper text), scope→"Model", brand string, `valuechain.py`→`network.py` module/class rename.

Blast radius (files mentioning the term, backend / frontend): measure 27/23 ·
machine 22/25 · commodity 32/30 · connection ~. Push ORIGIN only.
