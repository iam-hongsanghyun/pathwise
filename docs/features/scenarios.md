# Scenarios & import — base vs per-session libraries

A **scenario** is a complete model you can open (the example library) or upload.
On import, pathwise **splits** it across the two builder views so each holds only
what it is responsible for:

- the **value-chain STRUCTURE** (nodes, connections, machines) loads into the
  Value-chain view;
- the **component DETAILS** (streams, technology recipes, measures) populate a
  **per-session component library** shown in the Component view.

The underlying session model still holds *everything* (structure + component
sheets) so the optimiser can build and solve — the split is about *where you
edit and visualise*, not about removing data.

## Two sets of component libraries

| Set | Scope | Lives in | Editing it… |
|---|---|---|---|
| **base** | shared, global | `<data_dir>/component_libraries/<id>.sqlite` (seeded from `assets/`) | affects every session |
| **session** (scenario) | one session only | `<data_dir>/session_libraries/<session_id>/<id>.sqlite` | affects only that scenario |

Both sets are stored as **SQLite** — the same sheets-in-SQLite form the examples
use (one table per kind: commodities, technologies, io, measures, …), so a
library is inspectable with any SQLite tool. The bundled seeds in `assets/` stay
as readable JSON and are converted to SQLite on first run.

The Component view lists both, each tagged in the tree — `… · scenario` for the
session set, `… · base` for the shared set. A scenario's components and your edits
to them never touch the shared catalogue, so you can tweak an imported model
freely.

## What import does

`POST /api/session/{id}/example/{example_id}`:

1. Parses the example file (SQLite / JSON / xlsx) into the session model
   (structure + component sheets) — the Value-chain view renders the structure.
2. Builds the scenario's **component library** and saves it to the session set:
   - if the example's `index.json` entry names a shipped `library`, that bundled
     component library is used verbatim (fully faithful, incl. MACC bundles);
   - otherwise the library is **extracted** from the workbook's component sheets
     (`extract_library_from_workbook`): commodities, technologies + their `io`,
     and per-facility measures de-duplicated back to reusable templates. (MACC
     bundles and technology→MACC links aren't present in an assembled workbook,
     so they're omitted; the individual measures are still recovered.)
3. Returns `{sessionId, sheets, library_id}` — `library_id` is the new session
   library, which the Component view shows under `· scenario`.

To attach a faithful library to an example, add a `"library": "<id>"` field to its
`index.json` entry pointing at a bundled component library (see the
`green_steel_chain` example → `green_steel`).

## Session-scoped library API

Mirrors the global component-library CRUD, scoped by session:

```
GET    /api/session/{id}/component-libraries          # list (scope="session")
GET    /api/session/{id}/component-library/{lib_id}    # one library
PUT    /api/session/{id}/component-library/{lib_id}    # create / overwrite
DELETE /api/session/{id}/component-library/{lib_id}    # delete
```

Backed by `SessionLibraryStore` (one JSON file per library under the session's
directory) — see [components.md](components.md) for the library contents and
[valuechain.md](valuechain.md) for the structure side of the split.
