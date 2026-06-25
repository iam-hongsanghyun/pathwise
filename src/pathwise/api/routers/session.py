"""Session + assets routers — the backend owns the working model.

The ragnarok pattern: the frontend ingests a model once (or asks the backend to
load an example / parse an upload), then reads pages and writes patches; runs
submit by ``sessionId``. All file parsing/writing happens here, server-side.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from pathwise.api.routers._deps import runs_store, session_libs, session_store
from pathwise.api.session_store import SessionNotFound, SessionStore
from pathwise.api.workbook_io import (
    parse_sqlite,
    parse_xlsx,
    result_to_sqlite,
    result_to_xlsx,
    write_sqlite,
    write_template_xlsx,
    write_xlsx,
)
from pathwise.config import get_settings
from pathwise.core.network import run_network
from pathwise.data.aliases import normalize_workbook
from pathwise.data.components import extract_library_from_workbook, load_component_library
from pathwise.data.libraries import discover_libraries, load_library_workbook
from pathwise.data.network import NetworkSpec, load_network
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.schema import template_columns
from pathwise.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api")

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Sheets every fresh session starts with, so the model tree renders editable
# groups before any data is loaded (mirrors the old frontend emptyWorkbook()).
CORE_SHEETS = [
    "periods",
    "flows",
    "technologies",
    "processes",
    "io",
    "impacts",
    "markets",
    "storage",
    "demand",
    "transitions",
    "levers",
    "lever_blocks",
    "maccs",
    "macc_links",
    "edges",
]


_store = session_store
_session_libs = session_libs
_runs = runs_store


def _model_or_404(store: SessionStore, session_id: str) -> dict[str, list[dict[str, Any]]]:
    try:
        return store.get_model(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'") from exc


class ModelIngest(BaseModel):
    """Body for ``POST /api/session/model``."""

    model: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    sessionId: str | None = None


class PatchOps(BaseModel):
    """Body for ``PATCH /api/session/{sid}/sheet/{name}``."""

    ops: list[dict[str, Any]]


@router.post("/session")
def create_session() -> dict[str, Any]:
    """Create a fresh session seeded with the empty core sheets."""
    store = _store()
    session_id = store.create({name: [] for name in CORE_SHEETS})
    return {"sessionId": session_id}


@router.post("/session/{session_id}/clear")
def clear_session(session_id: str) -> dict[str, Any]:
    """Reset the session to an empty model and drop its own component libraries.

    Clearing the model also discards the session-scoped component libraries an
    example/import created (they were the *scenario's* own catalogue, not the
    shared base set), so the Component view doesn't accumulate stale libraries.
    """
    store = _store()
    if not store.exists(session_id):
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'")
    counts = store.put_model(session_id, {name: [] for name in CORE_SHEETS})
    _session_libs().delete_session(session_id)
    cleared_runs = _runs().clear(session_id=session_id, keep_exported=True)
    return {"sessionId": session_id, "sheets": counts, "clearedRuns": cleared_runs}


@router.post("/cache/clear")
def clear_cache(x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    """Wipe ALL working session data and hand back a fresh empty session.

    Guarded by ``settings.admin_token`` when set: callers must send a matching
    ``X-Admin-Token`` header (else 403). Unset (the local-first default) ⇒ open.

    Removes every session model and every session-scoped component library (the
    gitignored working state under ``<data_dir>/sessions`` and
    ``<data_dir>/session_libraries``), plus every stored run the user has NOT
    exported (exported runs are kept as history). The shared base component
    libraries and bundled examples are left untouched.
    """
    admin_token = get_settings().admin_token
    if admin_token and x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="admin token required")
    cleared_sessions = _store().clear_all()
    cleared_libraries = _session_libs().clear_all()
    cleared_runs = _runs().clear(keep_exported=True)
    session_id = _store().create({name: [] for name in CORE_SHEETS})
    logger.info(
        "cache cleared: %d session(s), %d session-library set(s), %d run(s)",
        cleared_sessions,
        cleared_libraries,
        cleared_runs,
    )
    return {
        "clearedSessions": cleared_sessions,
        "clearedSessionLibraries": cleared_libraries,
        "clearedRuns": cleared_runs,
        "sessionId": session_id,
    }


@router.post("/session/model")
def ingest_model(body: ModelIngest) -> dict[str, Any]:
    """Ingest a full model into a (new or existing) session."""
    store = _store()
    sid = body.sessionId
    if sid and store.exists(sid):
        counts = store.put_model(sid, body.model)
    else:
        sid = store.create(body.model)
        counts = {k: len(v) for k, v in body.model.items()}
    return {"sessionId": sid, "sheets": counts}


@router.get("/session/{session_id}")
def session_exists(session_id: str) -> dict[str, Any]:
    """Lightweight existence probe (always 200) for the client's session check.

    The frontend resumes a stored session only if the backend still knows it.
    Probing ``/model`` for that returned 404 for an unknown id — correct, but it
    spams the browser console on every fresh boot with a stale localStorage id.
    This endpoint answers the same question with a 200 ``{exists}`` payload.
    """
    return {"sessionId": session_id, "exists": _store().exists(session_id)}


@router.get("/session/{session_id}/model")
def full_model(session_id: str) -> dict[str, Any]:
    """The whole session workbook (pathwise models are small).

    Normalised through the back-compat alias map so a model stored under OLD sheet/
    column names (a bundled example or a pre-rename user model) reaches the frontend
    in the current vocabulary; once the frontend saves it back the store self-heals.
    """
    return {
        "sessionId": session_id,
        "model": normalize_workbook(_model_or_404(_store(), session_id)),
    }


@router.get("/session/{session_id}/sheet/{name}")
def sheet_page(session_id: str, name: str, offset: int = 0, limit: int = 0) -> dict[str, Any]:
    """One page of a sheet."""
    settings = get_settings()
    store = _store()
    if not store.exists(session_id):
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'")
    lim = min(limit or settings.max_sheet_page, settings.max_sheet_page)
    return store.get_sheet(session_id, name, offset=max(offset, 0), limit=lim)


@router.patch("/session/{session_id}/sheet/{name}")
def patch_sheet(session_id: str, name: str, body: PatchOps) -> dict[str, Any]:
    """Apply batch edits (set / addRow / deleteRows / replace) to a sheet."""
    store = _store()
    if not store.exists(session_id):
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'")
    try:
        total = store.patch_sheet(session_id, name, body.ops)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"malformed patch op: {exc}") from exc
    return {"name": name, "total": total}


def _parse_model_file(data: bytes) -> dict[str, list[dict[str, Any]]]:
    """Parse an uploaded model file by sniffing its magic bytes: a SQLite database
    (``SQLite format 3\\0``) vs an ``.xlsx`` (a zip, ``PK``). Both round-trip to the
    same ``{sheet: rows[]}`` model."""
    return parse_sqlite(data) if data[:16] == b"SQLite format 3\x00" else parse_xlsx(data)


@router.post("/session/{session_id}/workbook")
async def upload_workbook(session_id: str, file: UploadFile) -> dict[str, Any]:
    """Parse an uploaded model file (``.xlsx`` or ``.sqlite``) server-side and
    replace the session model — so an edited spreadsheet becomes the project."""
    store = _store()
    if not store.exists(session_id):
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'")
    data = await file.read()
    try:
        # Parsing is synchronous/CPU-bound (pandas); keep it off the event loop.
        model = await run_in_threadpool(_parse_model_file, data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"could not parse workbook: {exc}") from exc
    counts = store.put_model(session_id, model)
    return {"sessionId": session_id, "sheets": counts}


# Sheets that don't count as "model content" when deciding an empty model → template.
_NON_CONTENT_SHEETS = {"meta", "project", "node_layout"}


def _model_is_empty(model: dict[str, list[dict[str, Any]]]) -> bool:
    """True when the model carries no actual data (only metadata / layout) — an
    export then yields the blank fill-in template instead of an empty file."""
    return not any(rows for name, rows in model.items() if name not in _NON_CONTENT_SHEETS and rows)


def _template_response(filename: str = "pathwise_template.xlsx") -> Response:
    return Response(
        content=write_template_xlsx(template_columns()),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/template.xlsx")
def download_template() -> Response:
    """The blank fill-in template: one sheet per table with its column headers."""
    return _template_response()


@router.get("/session/{session_id}/export")
def export_workbook(session_id: str) -> Response:
    """Download the session model as a human-readable ``.xlsx`` (one sheet per table).

    An empty model exports the blank template instead — so a fresh project gives
    the user a structured workbook to fill in, not an empty file."""
    model = _model_or_404(_store(), session_id)
    if _model_is_empty(model):
        return _template_response("pathwise_model.xlsx")
    return Response(
        content=write_xlsx(model),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="pathwise_model.xlsx"'},
    )


@router.get("/session/{session_id}/export.sqlite")
def export_workbook_sqlite(session_id: str) -> Response:
    """Download the session model as a single-file SQLite database (one table per sheet)."""
    model = _model_or_404(_store(), session_id)
    return Response(
        content=write_sqlite(model),
        media_type="application/x-sqlite3",
        headers={"Content-Disposition": 'attachment; filename="pathwise_model.sqlite"'},
    )


def _mark_exported(result: dict[str, Any]) -> None:
    """Flag the stored run (if any) as exported, so a cache clear keeps it."""
    run_id = result.get("runId")
    if run_id:
        _runs().mark_exported(str(run_id))


@router.post("/export/result")
def export_result(result: dict[str, Any]) -> Response:
    """Flatten a run result into a downloadable ``.xlsx`` (and mark it exported)."""
    _mark_exported(result)
    return Response(
        content=result_to_xlsx(result),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="pathwise_result.xlsx"'},
    )


@router.post("/export/result.sqlite")
def export_result_sqlite(result: dict[str, Any]) -> Response:
    """Flatten a run result into a downloadable SQLite (one table per output, by
    year — technology, throughput, transitions, consumption, emissions, …).

    Marks the stored run exported so a cache clear keeps it."""
    _mark_exported(result)
    return Response(
        content=result_to_sqlite(result),
        media_type="application/x-sqlite3",
        headers={"Content-Disposition": 'attachment; filename="pathwise_result.sqlite"'},
    )


# ── Run history (persisted run results) ───────────────────────────────────────


@router.get("/runs")
def list_all_runs() -> dict[str, Any]:
    """Light metadata for ALL persisted runs (newest first).

    Global (not session-scoped) so exported runs stay visible in the history even
    after a cache clear hands back a fresh session id.
    """
    return {"runs": _runs().list()}


@router.get("/session/{session_id}/runs")
def list_runs(session_id: str) -> dict[str, Any]:
    """Light metadata for this session's persisted runs (newest first)."""
    return {"sessionId": session_id, "runs": _runs().list(session_id)}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """The full stored result for one run."""
    result = _runs().get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"unknown run '{run_id}'")
    return result


@router.post("/runs/{run_id}/export")
def mark_run_exported(run_id: str) -> dict[str, Any]:
    """Mark a stored run exported (so a cache clear keeps it)."""
    if not _runs().mark_exported(run_id):
        raise HTTPException(status_code=404, detail=f"unknown run '{run_id}'")
    return {"runId": run_id, "exported": True}


@router.delete("/runs/{run_id}")
def delete_run(run_id: str) -> dict[str, Any]:
    """Delete one stored run (exported or not)."""
    if not _runs().delete(run_id):
        raise HTTPException(status_code=404, detail=f"unknown run '{run_id}'")
    return {"runId": run_id, "deleted": True}


# ── Examples (bundled example workbooks, loaded server-side) ──────────────────


@router.get("/examples")
def list_examples() -> list[dict[str, Any]]:
    """The example-library index."""
    index = Path(get_settings().examples_dir) / "index.json"
    if not index.exists():
        return []
    return json.loads(index.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@router.post("/session/{session_id}/example/{example_id}")
def load_example(session_id: str, example_id: str) -> dict[str, Any]:
    """Load a bundled example workbook into the session (server-side parse)."""
    store = _store()
    if not store.exists(session_id):
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'")
    examples_dir = Path(get_settings().examples_dir).resolve()
    index = json.loads((examples_dir / "index.json").read_text(encoding="utf-8"))
    entry = next((e for e in index if e.get("id") == example_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown example '{example_id}'")
    fpath = (examples_dir / str(entry["file"])).resolve()
    # Keep the resolved path inside the examples dir (defends against a stray
    # ``..`` / absolute path in index.json).
    if not fpath.is_relative_to(examples_dir) or not fpath.exists():
        raise HTTPException(status_code=404, detail=f"example file missing for '{example_id}'")
    # Examples ship as a SQLite workbook (a built node hierarchy); JSON / .xlsx
    # are also accepted by the generic loader.
    if fpath.suffix in (".sqlite", ".db"):
        model = parse_sqlite(fpath.read_bytes())
    elif fpath.suffix == ".json":
        model = json.loads(fpath.read_text(encoding="utf-8"))
    else:
        model = parse_xlsx(fpath.read_bytes())
    counts = store.put_model(session_id, model)
    # Split the import: the network STRUCTURE (nodes / connections) stays in
    # the session model (shown in the Network view); the component DETAILS
    # (streams / technologies / measures) populate the session's OWN component
    # library (shown in the Component view), distinct from the shared base set.
    lib_id = "".join(c for c in example_id if c.isalnum() or c in "-_.") or "scenario"
    shipped = entry.get("library")
    seeds = Path(get_settings().component_seeds_dir)
    # Component seeds ship as SQLite (a legacy .json is still honoured).
    seed_path = next(
        (
            seeds / f"{shipped}{suffix}"
            for suffix in (".sqlite", ".db", ".json")
            if shipped and (seeds / f"{shipped}{suffix}").exists()
        ),
        None,
    )
    if seed_path is not None:
        lib = load_component_library(seed_path)  # faithful, shipped library
        if not lib.label:
            lib.label = str(entry.get("label") or example_id)
    else:
        lib = extract_library_from_workbook(model, label=str(entry.get("label") or example_id))
    _session_libs().put(session_id, lib_id, lib)
    return {"sessionId": session_id, "sheets": counts, "library_id": lib_id}


# ── Importable libraries (auto-discovered: <tier>/<id>.json) ──────────────────


@router.get("/libraries")
def list_libraries() -> list[dict[str, Any]]:
    """Every importable library, discovered by globbing the tier folders.

    No index — the catalogue is the JSON files on disk, so adding a library is
    just dropping a file under base/ · example/ · project/.
    """
    return discover_libraries(get_settings().libraries_dir)


@router.post("/session/{session_id}/library/{tier}/{library_id}/import")
def import_library(session_id: str, tier: str, library_id: str) -> dict[str, Any]:
    """Import a library into the session: components → the session component
    library, and (when the workbook carries a node hierarchy) the network →
    the session model."""
    store = _store()
    if not store.exists(session_id):
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'")
    try:
        wb = load_library_workbook(get_settings().libraries_dir, tier, library_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    label = next(
        (r.get("value") for r in wb.get("meta", []) if r.get("key") == "label"), library_id
    )
    lib_id = "".join(c for c in library_id if c.isalnum() or c in "-_.") or "library"
    _session_libs().put(session_id, lib_id, extract_library_from_workbook(wb, label=str(label)))

    has_chain = bool(wb.get("nodes"))
    sheets: dict[str, int] = {}
    if has_chain:  # a network → load the structure into the session model
        sheets = store.put_model(session_id, wb)
    return {
        "sessionId": session_id,
        "library_id": lib_id,
        "imported_value_chain": has_chain,
        "sheets": sheets,
    }


# ── Value chains (coupled multi-stage models, solved as a forward cascade) ─────


class NetworkRun(BaseModel):
    """Body for ``POST /api/network/{name}/run`` (scenario optional)."""

    scenario: dict[str, Any] = Field(default_factory=dict)


def _load_chain(name: str) -> NetworkSpec:
    path = Path(get_settings().value_chains_dir) / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"unknown network '{name}'")
    return load_network(path)


@router.get("/networks")
def list_value_chains() -> list[dict[str, Any]]:
    """The network index."""
    index = Path(get_settings().value_chains_dir) / "index.json"
    if not index.exists():
        return []
    return json.loads(index.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@router.get("/network/{name}")
def value_chain_detail(name: str) -> dict[str, Any]:
    """One network spec (for the designer)."""
    return _load_chain(name).model_dump()


@router.post("/network/{name}/run")
def run_chain(name: str, body: NetworkRun | None = None) -> dict[str, Any]:
    """Resolve each stage's workbook and solve the chain as a forward cascade."""
    spec = _load_chain(name)
    vdir = Path(get_settings().value_chains_dir).resolve()
    workbooks: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for stage in spec.stages:
        wb_path = (vdir / stage.model).resolve()
        if not wb_path.is_relative_to(vdir) or not wb_path.exists():
            raise HTTPException(
                status_code=404, detail=f"stage '{stage.id}' model '{stage.model}' not found"
            )
        workbooks[stage.id] = (
            parse_sqlite(wb_path.read_bytes())
            if wb_path.suffix in (".sqlite", ".db")
            else json.loads(wb_path.read_text(encoding="utf-8"))
        )
    # No scenario ⇒ plain defaults; base_year defers to each stage workbook's
    # first period (don't silently pin a hardcoded calendar year).
    overrides = (body.scenario if body else None) or {}
    return run_network(spec, workbooks, ScenarioConfig.from_dict(overrides))
