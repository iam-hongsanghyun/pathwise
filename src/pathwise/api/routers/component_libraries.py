"""Component-library router — the writable catalogue the builder edits.

Unlike the read-only facility ``library`` (bundled ``assets``), component
libraries are **user-owned**: there are *many* named libraries, each a
:class:`~pathwise.data.components.ComponentLibrary` (commodities, technologies,
machines with their MACC measures, groups). They live as JSON under the writable
``<data_dir>/component_libraries`` (gitignored), seeded once from the bundled
starters so a fresh install opens with real, editable content.

The Component builder reads/writes whole libraries here (list / get / save /
delete); copy and move between libraries are plain client-side edits that PUT
both libraries back. The Value-Chain builder calls ``/instantiate`` to drop a
**fresh copy** of a component into a company node of the session model.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pathwise.api.session_store import SessionNotFound, SessionStore
from pathwise.config import get_settings
from pathwise.data.components import (
    ComponentLibrary,
    instantiate_into,
    load_component_library,
)
from pathwise.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api")

#: A library id is a safe file stem — no path separators or traversal.
_LIB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _components_dir() -> Path:
    """The writable component-library directory; seeded from bundled starters.

    Seeding happens only when the directory does not yet exist, so a user who
    deletes every library does not have the starters resurrected.
    """
    d = Path(get_settings().data_dir) / "component_libraries"
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        seeds = Path(get_settings().component_seeds_dir)
        if seeds.is_dir():
            for f in sorted(seeds.glob("*.json")):
                shutil.copy(f, d / f.name)
    return d


def _lib_path(lib_id: str) -> Path:
    if not _LIB_ID.match(lib_id):
        raise HTTPException(status_code=422, detail=f"invalid library id '{lib_id}'")
    return _components_dir() / f"{lib_id}.json"


def _summary(lib_id: str, lib: ComponentLibrary) -> dict[str, Any]:
    return {
        "id": lib_id,
        "label": lib.label or lib_id,
        "commodities": len(lib.commodities),
        "technologies": len(lib.technologies),
        "machines": len(lib.machines),
        "groups": len(lib.groups),
    }


def _store() -> SessionStore:
    return SessionStore(Path(get_settings().data_dir) / "sessions")


@router.get("/component-libraries")
def list_component_libraries() -> list[dict[str, Any]]:
    """Every writable component library, summarised (id + label + counts)."""
    out: list[dict[str, Any]] = []
    for f in sorted(_components_dir().glob("*.json")):
        try:
            out.append(_summary(f.stem, load_component_library(f)))
        except Exception as exc:  # a malformed file should not break the list
            logger.warning("skipping unreadable component library %s: %s", f.name, exc)
    return out


@router.get("/component-library/{lib_id}")
def get_component_library(lib_id: str) -> dict[str, Any]:
    """One component library's full content."""
    path = _lib_path(lib_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"unknown component library '{lib_id}'")
    return load_component_library(path).model_dump()


@router.put("/component-library/{lib_id}")
def save_component_library(lib_id: str, library: ComponentLibrary) -> dict[str, Any]:
    """Create or overwrite a component library (validated server-side)."""
    path = _lib_path(lib_id)
    path.write_text(library.model_dump_json(indent=2), encoding="utf-8")
    logger.info(
        "saved component library %s (%d machines, %d groups)",
        lib_id,
        len(library.machines),
        len(library.groups),
    )
    return _summary(lib_id, library)


@router.delete("/component-library/{lib_id}")
def delete_component_library(lib_id: str) -> dict[str, Any]:
    """Delete a component library file."""
    path = _lib_path(lib_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"unknown component library '{lib_id}'")
    path.unlink()
    return {"id": lib_id, "deleted": True}


class InstantiateInsert(BaseModel):
    """Body for ``POST /api/session/{sid}/instantiate``.

    Drop a fresh copy of ``component`` from ``library`` under ``parent_id`` (a
    group node already in the session — a company, a subgroup, …). ``instance_id``
    overrides the auto-generated root id.
    """

    library: str
    component: str
    parent_id: str
    instance_id: str | None = None


@router.post("/session/{session_id}/instantiate")
def instantiate_component(session_id: str, body: InstantiateInsert) -> dict[str, Any]:
    """Stamp a fresh component instance into the session's node hierarchy."""
    path = _lib_path(body.library)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"unknown component library '{body.library}'")
    lib = load_component_library(path)
    store = _store()
    try:
        model = store.get_model(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'") from exc

    before = {str(r.get("node_id")) for r in model.get("nodes", [])}
    try:
        model = instantiate_into(
            model, lib, body.component, parent_id=body.parent_id, instance_id=body.instance_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    created = [str(r["node_id"]) for r in model["nodes"] if str(r["node_id"]) not in before]
    root = next(
        (
            r["node_id"]
            for r in model["nodes"]
            if str(r.get("parent_id")) == body.parent_id and str(r["node_id"]) in created
        ),
        created[0] if created else None,
    )
    counts = store.put_model(session_id, model)
    return {"sessionId": session_id, "created": created, "root": root, "sheets": counts}
