"""Component-library router — the writable catalogue the builder edits.

Unlike the read-only facility ``library`` (bundled ``assets``), component
libraries are **user-owned**: there are *many* named libraries, each a
:class:`~pathwise.data.components.ComponentLibrary` (commodities, technologies,
machines with their MACC measures, groups). They are stored as **SQLite** (one
table per kind, like the example workbooks) under the writable
``<data_dir>/component_libraries`` (gitignored), seeded once from the bundled
starters so a fresh install opens with real, editable content.

The Component builder reads/writes whole libraries here (list / get / save /
delete); copy and move between libraries are plain client-side edits that PUT
both libraries back. The Value-Chain builder calls ``/instantiate`` to drop a
**fresh copy** of a component into a company node of the session model.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pathwise.api.session_library_store import SessionLibraryStore
from pathwise.api.session_store import SessionNotFound, SessionStore
from pathwise.api.workbook_io import write_sqlite
from pathwise.config import get_settings
from pathwise.data.components import (
    ComponentLibrary,
    add_alternative,
    instantiate_into,
    library_to_workbook,
    load_component_library,
    place_technology,
)
from pathwise.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api")

#: A library id is a safe file stem — no path separators or traversal.
_LIB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


#: Manifest tracking what each starter looked like when last seeded, so the
#: reconciler can tell "user deleted/edited it" (leave alone) apart from "a new
#: or updated bundled starter the user has never seen" (seed it).
_SEED_MANIFEST = ".seeds.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _seed_bytes(seed: Path) -> bytes:
    """The SQLite bytes a bundled starter seeds to (``.json`` is converted)."""
    if seed.suffix == ".sqlite":
        return seed.read_bytes()
    return write_sqlite(library_to_workbook(load_component_library(seed)))


def _reconcile_seeds(d: Path) -> None:
    """Bring bundled starters into the writable dir without trampling the user.

    A plain "seed only if the directory is missing" check means starters added
    to a release never appear for an existing install (the reported "no library"
    bug). This reconciler instead seeds **per library**, keyed by a manifest:

    - A starter the user has never seen (not in the manifest, no working copy) is
      seeded — so newly-bundled sectors show up on the next run.
    - A starter the user **deleted** (in the manifest, no working copy) stays
      gone — deletions are respected.
    - A starter whose bundled content **changed** is refreshed only if the user
      has not edited their copy (its hash still matches what we seeded); local
      edits always win.
    - A pre-existing copy from before the manifest existed is adopted as-is.
    """
    seeds_dir = Path(get_settings().component_seeds_dir)
    if not seeds_dir.is_dir():
        return
    manifest_path = d / _SEED_MANIFEST
    try:
        manifest: dict[str, dict[str, str]] = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        manifest = {}

    changed = False
    seeds = sorted(seeds_dir.glob("*.json")) + sorted(seeds_dir.glob("*.sqlite"))
    for seed in seeds:
        stem = seed.stem
        working = d / f"{stem}.sqlite"
        src_h = _sha(seed.read_bytes())
        rec = manifest.get(stem)
        if rec is None:
            if working.exists():
                # Predates the manifest — adopt the user's copy, don't overwrite.
                manifest[stem] = {"src": src_h, "out": _sha(working.read_bytes())}
            else:
                out = _seed_bytes(seed)
                working.write_bytes(out)
                manifest[stem] = {"src": src_h, "out": _sha(out)}
            changed = True
        elif not working.exists():
            continue  # user deleted it — respect that
        elif rec.get("src") != src_h and _sha(working.read_bytes()) == rec.get("out"):
            out = _seed_bytes(seed)  # bundled content moved on; user hasn't touched theirs
            working.write_bytes(out)
            manifest[stem] = {"src": src_h, "out": _sha(out)}
            changed = True

    if changed:
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def _components_dir() -> Path:
    """The writable component-library directory, reconciled with bundled starters.

    Libraries are stored as SQLite (one table per kind). The bundled seeds may be
    readable ``.json`` (converted to SQLite) or pre-built ``.sqlite``. See
    :func:`_reconcile_seeds` for how new/updated/deleted starters are handled.
    """
    d = Path(get_settings().data_dir) / "component_libraries"
    d.mkdir(parents=True, exist_ok=True)
    _reconcile_seeds(d)
    return d


def _lib_path(lib_id: str) -> Path:
    if not _LIB_ID.match(lib_id):
        raise HTTPException(status_code=422, detail=f"invalid library id '{lib_id}'")
    return _components_dir() / f"{lib_id}.sqlite"


def _summary(lib_id: str, lib: ComponentLibrary, scope: str = "base") -> dict[str, Any]:
    return {
        "id": lib_id,
        "label": lib.label or lib_id,
        "scope": scope,  # "base" (shared) or "session" (this scenario's own set)
        "commodities": len(lib.commodities),
        "technologies": len(lib.technologies),
        "measures": len(lib.measures),
        "maccs": len(lib.maccs),
        "machines": len(lib.machines),
        "groups": len(lib.groups),
    }


def _store() -> SessionStore:
    return SessionStore(Path(get_settings().data_dir) / "sessions")


def _session_libs() -> SessionLibraryStore:
    return SessionLibraryStore(Path(get_settings().data_dir) / "session_libraries")


@router.get("/component-libraries")
def list_component_libraries() -> list[dict[str, Any]]:
    """Every writable component library, summarised (id + label + counts)."""
    out: list[dict[str, Any]] = []
    for f in sorted(_components_dir().glob("*.sqlite")):
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
    path.write_bytes(write_sqlite(library_to_workbook(library)))
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


# ── Per-session component libraries (a scenario's OWN set) ────────────────────
# The shared base libraries above are global; these are isolated per session, so
# an imported scenario's components and a user's edits to them never touch the
# shared catalogue. Same CRUD shape, scoped by session id.


@router.get("/session/{session_id}/component-libraries")
def list_session_component_libraries(session_id: str) -> list[dict[str, Any]]:
    """The session's own component libraries (scope='session'), summarised."""
    libs = _session_libs()
    out: list[dict[str, Any]] = []
    for lib_id in libs.list_ids(session_id):
        try:
            lib = libs.get(session_id, lib_id)
            if lib is not None:
                out.append(_summary(lib_id, lib, scope="session"))
        except Exception as exc:  # a malformed file should not break the list
            logger.warning("skipping unreadable session library %s/%s: %s", session_id, lib_id, exc)
    return out


@router.get("/session/{session_id}/component-library/{lib_id}")
def get_session_component_library(session_id: str, lib_id: str) -> dict[str, Any]:
    """One session library's full content."""
    lib = _session_libs().get(session_id, lib_id)
    if lib is None:
        raise HTTPException(status_code=404, detail=f"unknown session library '{lib_id}'")
    return lib.model_dump()


@router.put("/session/{session_id}/component-library/{lib_id}")
def save_session_component_library(
    session_id: str, lib_id: str, library: ComponentLibrary
) -> dict[str, Any]:
    """Create or overwrite a session library (validated server-side)."""
    if not _LIB_ID.match(lib_id):
        raise HTTPException(status_code=422, detail=f"invalid library id '{lib_id}'")
    _session_libs().put(session_id, lib_id, library)
    return _summary(lib_id, library, scope="session")


@router.delete("/session/{session_id}/component-library/{lib_id}")
def delete_session_component_library(session_id: str, lib_id: str) -> dict[str, Any]:
    """Delete one of the session's libraries."""
    if not _session_libs().delete(session_id, lib_id):
        raise HTTPException(status_code=404, detail=f"unknown session library '{lib_id}'")
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


class PlaceTechnology(BaseModel):
    """Body for ``POST /api/session/{sid}/place-technology``.

    Place ``technology`` from ``library`` as a fresh MACHINE under ``parent_id``,
    with its ``capacity``; the technology's MACC measures come along.
    """

    library: str
    technology: str
    parent_id: str
    capacity: float = 1000.0
    instance_id: str | None = None


@router.post("/session/{session_id}/place-technology")
def place_technology_route(session_id: str, body: PlaceTechnology) -> dict[str, Any]:
    """Add one technology as a machine node to the session's hierarchy."""
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
        model = place_technology(
            model,
            lib,
            body.technology,
            parent_id=body.parent_id,
            capacity=body.capacity,
            instance_id=body.instance_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    created = [str(r["node_id"]) for r in model["nodes"] if str(r["node_id"]) not in before]
    counts = store.put_model(session_id, model)
    return {
        "sessionId": session_id,
        "created": created,
        "root": created[0] if created else None,
        "sheets": counts,
    }


# ── Value-chain alternatives ──────────────────────────────────────────────────
# An "alternative" is another technology the optimiser may switch a machine to.
# It's a VALUE-CHAIN choice (not baked into the Component library): adding one
# merges the technology's recipe into the session and records a transition.


@router.get("/session/{session_id}/technologies")
def list_available_technologies(session_id: str) -> list[dict[str, Any]]:
    """Every technology across the base + this session's libraries — the pool an
    alternative can be drawn from."""
    out: list[dict[str, Any]] = []
    for f in sorted(_components_dir().glob("*.sqlite")):
        try:
            lib = load_component_library(f)
        except Exception:  # a malformed file should not break the list
            continue
        for t in lib.technologies:
            out.append({"library": f.stem, "scope": "base", "technology": t.technology_id})
    sl = _session_libs()
    for lib_id in sl.list_ids(session_id):
        slib = sl.get(session_id, lib_id)
        if slib is None:
            continue
        for t in slib.technologies:
            out.append({"library": lib_id, "scope": "session", "technology": t.technology_id})
    return out


class AddAlternative(BaseModel):
    """Body for ``POST /api/session/{sid}/alternative`` — offer ``technology``
    (from ``library`` in ``scope``) as a switch target for ``machine_id``."""

    library: str
    technology: str
    machine_id: str
    scope: str = "base"  # "base" | "session"
    capex_per_capacity: float = 0.0


@router.post("/session/{session_id}/alternative")
def add_alternative_route(session_id: str, body: AddAlternative) -> dict[str, Any]:
    """Make a technology an alternative the optimiser may switch the machine to."""
    if body.scope == "session":
        maybe = _session_libs().get(session_id, body.library)
        if maybe is None:
            raise HTTPException(status_code=404, detail=f"unknown session library '{body.library}'")
        lib = maybe
    else:
        path = _lib_path(body.library)
        if not path.exists():
            raise HTTPException(
                status_code=404, detail=f"unknown component library '{body.library}'"
            )
        lib = load_component_library(path)

    store = _store()
    try:
        model = store.get_model(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'") from exc
    baseline = next(
        (
            str(m.get("baseline_technology"))
            for m in model.get("machines", [])
            if str(m.get("machine_id")) == body.machine_id
        ),
        None,
    )
    if not baseline:
        raise HTTPException(
            status_code=422, detail=f"machine '{body.machine_id}' has no baseline technology"
        )
    try:
        model = add_alternative(
            model,
            lib,
            body.technology,
            from_technology=baseline,
            capex_per_capacity=body.capex_per_capacity,
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    counts = store.put_model(session_id, model)
    return {
        "sessionId": session_id,
        "from_technology": baseline,
        "to_technology": body.technology,
        "sheets": counts,
    }
