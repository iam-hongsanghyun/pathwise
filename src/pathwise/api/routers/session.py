"""Session + assets routers — the backend owns the working model.

The ragnarok pattern: the frontend ingests a model once (or asks the backend to
load an example / parse an upload), then reads pages and writes patches; runs
submit by ``sessionId``. All file parsing/writing happens here, server-side.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from pathwise.api.session_store import SessionNotFound, SessionStore
from pathwise.api.workbook_io import parse_xlsx, result_to_xlsx, write_xlsx
from pathwise.config import get_settings
from pathwise.core.valuechain import run_value_chain
from pathwise.data.library import (
    Library,
    add_chain,
    add_facility,
    add_replacement,
    load_library,
)
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.valuechain import ValueChainSpec, load_value_chain
from pathwise.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api")

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Sheets every fresh session starts with, so the model tree renders editable
# groups before any data is loaded (mirrors the old frontend emptyWorkbook()).
CORE_SHEETS = [
    "periods",
    "commodities",
    "technologies",
    "processes",
    "io",
    "impacts",
    "markets",
    "storage",
    "demand",
    "transitions",
    "measures",
    "measure_blocks",
    "maccs",
    "macc_links",
    "edges",
]


def _store() -> SessionStore:
    return SessionStore(Path(get_settings().data_dir) / "sessions")


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


class LibraryInsert(BaseModel):
    """Body for ``POST /api/session/{sid}/library``.

    ``mode="initial"`` creates a facility instance running the template today;
    ``mode="replacement"`` registers the template's technology as a TRANSITION
    OPTION of ``replace_process``'s baseline (no new facility) — the future
    system the optimiser may switch into.
    """

    library: str
    kind: str = Field(pattern="^(facility|chain)$")
    id: str
    mode: str = Field(default="initial", pattern="^(initial|replacement)$")
    replace_process: str | None = None
    x: float | None = None
    y: float | None = None


@router.post("/session")
def create_session() -> dict[str, Any]:
    """Create a fresh session seeded with the empty core sheets."""
    store = _store()
    session_id = store.create({name: [] for name in CORE_SHEETS})
    return {"sessionId": session_id}


@router.post("/session/{session_id}/clear")
def clear_session(session_id: str) -> dict[str, Any]:
    """Reset the session to an empty model (the core sheets, no rows)."""
    store = _store()
    if not store.exists(session_id):
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'")
    counts = store.put_model(session_id, {name: [] for name in CORE_SHEETS})
    return {"sessionId": session_id, "sheets": counts}


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


@router.get("/session/{session_id}/model")
def full_model(session_id: str) -> dict[str, Any]:
    """The whole session workbook (pathwise models are small)."""
    return {"sessionId": session_id, "model": _model_or_404(_store(), session_id)}


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
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"name": name, "total": total}


@router.post("/session/{session_id}/workbook")
async def upload_workbook(session_id: str, file: UploadFile) -> dict[str, Any]:
    """Parse an uploaded ``.xlsx`` server-side and replace the session model."""
    store = _store()
    if not store.exists(session_id):
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'")
    try:
        model = parse_xlsx(await file.read())
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"could not parse workbook: {exc}") from exc
    counts = store.put_model(session_id, model)
    return {"sessionId": session_id, "sheets": counts}


@router.get("/session/{session_id}/export")
def export_workbook(session_id: str) -> Response:
    """Download the session model as ``.xlsx`` (written server-side)."""
    model = _model_or_404(_store(), session_id)
    return Response(
        content=write_xlsx(model),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="pathwise_model.xlsx"'},
    )


@router.post("/export/result")
def export_result(result: dict[str, Any]) -> Response:
    """Flatten a run result into a downloadable ``.xlsx``."""
    return Response(
        content=result_to_xlsx(result),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="pathwise_result.xlsx"'},
    )


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
    examples_dir = Path(get_settings().examples_dir)
    index = json.loads((examples_dir / "index.json").read_text(encoding="utf-8"))
    entry = next((e for e in index if e.get("id") == example_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown example '{example_id}'")
    model = parse_xlsx((examples_dir / str(entry["file"])).read_bytes())
    counts = store.put_model(session_id, model)
    return {"sessionId": session_id, "sheets": counts}


# ── Facility-template library (insert server-side) ────────────────────────────


def _library(name: str) -> Library:
    path = Path(get_settings().library_dir) / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"unknown library '{name}'")
    return load_library(path)


@router.get("/library")
def list_library() -> list[dict[str, Any]]:
    """The template-library index."""
    index = Path(get_settings().library_dir) / "index.json"
    if not index.exists():
        return []
    return json.loads(index.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@router.get("/library/{name}")
def library_detail(name: str) -> dict[str, Any]:
    """One library's templates (for the preview cards)."""
    return _library(name).model_dump()


@router.post("/session/{session_id}/library")
def insert_template(session_id: str, body: LibraryInsert) -> dict[str, Any]:
    """Insert a facility or chain template into the session model."""
    store = _store()
    model = _model_or_404(store, session_id)
    lib = _library(body.library)
    try:
        if body.kind == "chain":
            model = add_chain(model, lib, body.id)
            created = [str(r["process_id"]) for r in model["processes"][-1:]]
        elif body.mode == "replacement":
            if not body.replace_process:
                raise ValueError("replacement insert needs 'replace_process'")
            model = add_replacement(model, lib, body.id, body.replace_process)
            created = [lib.facility(body.id).technology.technology_id]
        else:
            model = add_facility(model, lib, body.id)
            pid = str(model["processes"][-1]["process_id"])
            if body.x is not None and body.y is not None:
                layout = [
                    r for r in model.get("node_layout", []) if str(r.get("id")) != f"process:{pid}"
                ]
                layout.append({"id": f"process:{pid}", "x": round(body.x), "y": round(body.y)})
                model["node_layout"] = layout
            created = [pid]
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.put_model(session_id, model)
    return {"sessionId": session_id, "created": created}


# ── Value chains (coupled multi-stage models, solved as a forward cascade) ─────


class ValueChainRun(BaseModel):
    """Body for ``POST /api/value-chain/{name}/run`` (scenario optional)."""

    scenario: dict[str, Any] = Field(default_factory=dict)


def _load_chain(name: str) -> ValueChainSpec:
    path = Path(get_settings().value_chains_dir) / f"{name}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"unknown value chain '{name}'")
    return load_value_chain(path)


@router.get("/value-chains")
def list_value_chains() -> list[dict[str, Any]]:
    """The value-chain index."""
    index = Path(get_settings().value_chains_dir) / "index.json"
    if not index.exists():
        return []
    return json.loads(index.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@router.get("/value-chain/{name}")
def value_chain_detail(name: str) -> dict[str, Any]:
    """One value-chain spec (for the designer)."""
    return _load_chain(name).model_dump()


@router.post("/value-chain/{name}/run")
def run_chain(name: str, body: ValueChainRun | None = None) -> dict[str, Any]:
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
        workbooks[stage.id] = json.loads(wb_path.read_text(encoding="utf-8"))
    overrides = (body.scenario if body else None) or {"economics": {"base_year": 2025}}
    return run_value_chain(spec, workbooks, ScenarioConfig.from_dict(overrides))
