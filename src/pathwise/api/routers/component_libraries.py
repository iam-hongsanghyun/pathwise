"""Component-library router — the writable catalogue the builder edits.

Unlike the read-only facility ``library`` (bundled ``assets``), component
libraries are **user-owned**: there are *many* named libraries, each a
:class:`~pathwise.data.components.ComponentLibrary` (flows, technologies,
assets with their MACC measures, groups). They are stored as **SQLite** (one
table per kind, like the example workbooks) under the writable
``<data_dir>/component_libraries`` (gitignored), seeded once from the bundled
starters so a fresh install opens with real, editable content.

The Component builder reads/writes whole libraries here (list / get / save /
delete); copy and move between libraries are plain client-side edits that PUT
both libraries back. The Network builder calls ``/instantiate`` to drop a
**fresh copy** of a component into a company node of the session model.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from pathwise.api.routers._deps import session_libs, session_store
from pathwise.api.session_store import SessionNotFound
from pathwise.api.workbook_io import parse_sqlite, parse_xlsx, write_sqlite, write_template_xlsx
from pathwise.config import get_settings
from pathwise.data.components import (
    PROJECT_BUNDLE_FORMAT,
    ComponentLibrary,
    ProjectBundle,
    add_alternative,
    copy_component_into,
    extract_library_from_workbook,
    instantiate_into,
    library_to_workbook,
    load_component_library,
    place_technology,
    referenced_technology_ids,
    slice_library_to_technologies,
)
from pathwise.data.schema import template_columns
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


def _starter_ids() -> set[str]:
    """Ids of the bundled **starter** libraries (shipped with pathwise).

    These are read-only references: a user customises one by duplicating it into a
    library of their own. Everything else in the catalogue is user-owned.
    """
    seeds_dir = Path(get_settings().component_seeds_dir)
    if not seeds_dir.is_dir():
        return set()
    return {p.stem for p in (*seeds_dir.glob("*.json"), *seeds_dir.glob("*.sqlite"))}


def _guard_writable(lib_id: str) -> None:
    """Reject mutating a shipped starter — they are read-only (duplicate to edit)."""
    if lib_id in _starter_ids():
        raise HTTPException(
            status_code=403,
            detail=f"'{lib_id}' is a read-only starter — duplicate it into your own library",
        )


def _summary(
    lib_id: str, lib: ComponentLibrary, scope: str = "base", starters: set[str] | None = None
) -> dict[str, Any]:
    if starters is None:
        starters = _starter_ids()
    return {
        "id": lib_id,
        "label": lib.label or lib_id,
        "scope": scope,  # "base" (shared) or "session" (this scenario's own set)
        # "starter" = a shipped read-only reference; "user" = the user's own library.
        "origin": "starter" if (scope == "base" and lib_id in starters) else "user",
        "flows": len(lib.flows),
        "technologies": len(lib.technologies),
        "levers": len(lib.measures),
        "maccs": len(lib.maccs),
        "assets": len(lib.assets),
        "groups": len(lib.groups),
    }


_store = session_store
_session_libs = session_libs


def _resolve_library(session_id: str, library: str, scope: str) -> ComponentLibrary:
    """Load a component library by scope: ``session`` (this project's own) or
    ``base`` (the shared catalogue). Raises 404 if it doesn't exist."""
    if scope == "session":
        lib = _session_libs().get(session_id, library)
        if lib is None:
            raise HTTPException(status_code=404, detail=f"unknown session library '{library}'")
        return lib
    path = _lib_path(library)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"unknown component library '{library}'")
    return load_component_library(path)


@router.get("/component-libraries")
def list_component_libraries() -> list[dict[str, Any]]:
    """Every writable component library, summarised (id + label + counts)."""
    out: list[dict[str, Any]] = []
    starters = _starter_ids()
    for f in sorted(_components_dir().glob("*.sqlite")):
        try:
            out.append(_summary(f.stem, load_component_library(f), starters=starters))
        except Exception as exc:  # a malformed file should not break the list
            logger.warning("skipping unreadable component library %s: %s", f.name, exc)
    return out


#: The fillable sheets of a component library, in author order. Components are the
#: reusable building blocks only — streams, technology recipes, and levers/MACCs.
#: ``assets`` (placed instances) belong to the Facility layer, and ``groups``
#: (sector structure) is built as components are placed — both are omitted.
_LIBRARY_SHEETS = [
    "flows",
    "technologies",
    "io",
    "levers",
    "lever_blocks",
    "maccs",
]

#: MIME for the .xlsx template downloads.
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _library_template_columns() -> dict[str, list[str]]:
    cols = template_columns()
    return {s: cols[s] for s in _LIBRARY_SHEETS if cols.get(s)}


@router.get("/component-library/template.xlsx")
def download_library_template() -> Response:
    """A blank component-library template: one sheet per kind (streams,
    technologies, io, measures, …) with column headers, to fill in and import."""
    return Response(
        content=write_template_xlsx(_library_template_columns()),
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="pathwise_library_template.xlsx"'},
    )


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
    _guard_writable(lib_id)
    path.write_bytes(write_sqlite(library_to_workbook(library)))
    logger.info(
        "saved component library %s (%d assets, %d groups)",
        lib_id,
        len(library.assets),
        len(library.groups),
    )
    return _summary(lib_id, library)


@router.delete("/component-library/{lib_id}")
def delete_component_library(lib_id: str) -> dict[str, Any]:
    """Delete a component library file."""
    path = _lib_path(lib_id)
    _guard_writable(lib_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"unknown component library '{lib_id}'")
    path.unlink()
    return {"id": lib_id, "deleted": True}


def _parse_library_file(data: bytes, label: str) -> ComponentLibrary:
    """Parse an uploaded ``.xlsx`` / ``.sqlite`` (format sniffed) into a
    ComponentLibrary — pulling the component definitions out of whatever sheets it
    carries, so a library export OR a full model file both import."""
    wb = parse_sqlite(data) if data[:16] == b"SQLite format 3\x00" else parse_xlsx(data)
    return extract_library_from_workbook(wb, label=label)


@router.post("/component-library/{lib_id}/import")
async def import_component_library(lib_id: str, file: UploadFile) -> dict[str, Any]:
    """Import a component library from an uploaded ``.xlsx`` / ``.sqlite`` into the
    user's own ("My") libraries."""
    path = _lib_path(lib_id)  # validates the id
    _guard_writable(lib_id)  # never overwrite a shipped starter
    data = await file.read()
    try:
        lib = await run_in_threadpool(_parse_library_file, data, lib_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"could not parse library: {exc}") from exc
    path.write_bytes(write_sqlite(library_to_workbook(lib)))
    return _summary(lib_id, lib)


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


@router.post("/session/{session_id}/component-library/{lib_id}/import")
async def import_session_component_library(
    session_id: str, lib_id: str, file: UploadFile
) -> dict[str, Any]:
    """Import a component library from an uploaded ``.xlsx`` / ``.sqlite`` into this
    project's own set."""
    if not _LIB_ID.match(lib_id):
        raise HTTPException(status_code=422, detail=f"invalid library id '{lib_id}'")
    data = await file.read()
    try:
        lib = await run_in_threadpool(_parse_library_file, data, lib_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"could not parse library: {exc}") from exc
    _session_libs().put(session_id, lib_id, lib)
    return _summary(lib_id, lib, scope="session")


class CopyComponentInsert(BaseModel):
    """Body for ``POST /api/session/{sid}/component-library/{dst}/copy``.

    Hard-copy ``component_id`` (a ``kind`` of technology/stream/measure/macc) from
    the ``src_id`` library — ``src_scope`` ``base`` (shared) or ``session`` — into
    the destination session project ``dst`` (created empty if it doesn't exist).
    """

    src_scope: str
    src_id: str
    kind: str
    component_id: str


@router.post("/session/{session_id}/component-library/{lib_id}/copy")
def copy_into_project(session_id: str, lib_id: str, body: CopyComponentInsert) -> dict[str, Any]:
    """Drag-copy a component (+ its dependency closure) into a session project."""
    if not _LIB_ID.match(lib_id):
        raise HTTPException(status_code=422, detail=f"invalid library id '{lib_id}'")
    store = _session_libs()
    if body.src_scope == "session":
        src = store.get(session_id, body.src_id)
    else:
        src_path = _lib_path(body.src_id)
        src = load_component_library(src_path) if src_path.exists() else None
    if src is None:
        raise HTTPException(status_code=404, detail=f"unknown source library '{body.src_id}'")
    dst = store.get(session_id, lib_id) or ComponentLibrary()
    out = copy_component_into(dst, src, body.kind, body.component_id)
    store.put(session_id, lib_id, out)
    logger.info(
        "copied %s '%s' from %s/%s into project %s",
        body.kind,
        body.component_id,
        body.src_scope,
        body.src_id,
        lib_id,
    )
    return _summary(lib_id, out, scope="session")


# ── Project bundle (self-contained import / export) ───────────────────────────


def _project_name(model: dict[str, list[dict[str, Any]]]) -> str:
    """The project name, stored as the single ``project`` sheet row's ``name``."""
    rows = model.get("project") or []
    return str(rows[0].get("name", "")) if rows else ""


@router.get("/session/{session_id}/project/export")
def export_project(session_id: str) -> Response:
    """Download the whole project as one self-contained ``.pathwise.json`` bundle:
    the name, the full Facility + Network model, the project's own component
    libraries, and every referenced base component (sliced to the closure used) so
    it re-opens and re-edits on any host."""
    try:
        model = _store().get_model(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'") from exc

    sess_store = _session_libs()
    session_libraries: dict[str, ComponentLibrary] = {}
    for lib_id in sess_store.list_ids(session_id):
        lib = sess_store.get(session_id, lib_id)
        if lib is not None:
            session_libraries[lib_id] = lib

    refs = referenced_technology_ids(model)
    base_libraries: dict[str, ComponentLibrary] = {}
    for f in sorted(_components_dir().glob("*.sqlite")):
        try:
            sliced = slice_library_to_technologies(load_component_library(f), refs)
        except Exception as exc:  # a malformed base library shouldn't abort export
            logger.warning("skipping unreadable base library %s: %s", f.name, exc)
            continue
        if sliced.technologies:  # keep only libraries that actually contribute
            base_libraries[f.stem] = sliced

    name = _project_name(model)
    bundle = ProjectBundle(
        name=name,
        model=model,
        session_libraries=session_libraries,
        base_libraries=base_libraries,
    )
    safe = "".join(c for c in (name or "project") if c.isalnum() or c in "-_") or "project"
    return Response(
        content=bundle.model_dump_json(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe}.pathwise.json"'},
    )


@router.post("/session/{session_id}/project/import")
def import_project(session_id: str, bundle: ProjectBundle) -> dict[str, Any]:
    """Load a previously-exported project bundle into the session: replace the
    model, restore the project's own component libraries, and restore any
    referenced base libraries the host is missing (never overwriting an existing
    base library — the host's own copy may be richer than the sliced one)."""
    store = _store()
    if not store.exists(session_id):
        raise HTTPException(status_code=404, detail=f"unknown session '{session_id}'")
    if bundle.format != PROJECT_BUNDLE_FORMAT:
        raise HTTPException(status_code=422, detail="not a pathwise project bundle")

    # The project's own (session-scoped) libraries replace whatever this session had.
    sess_store = _session_libs()
    sess_store.delete_session(session_id)
    for lib_id, lib in bundle.session_libraries.items():
        if _LIB_ID.match(lib_id):
            sess_store.put(session_id, lib_id, lib)

    # Restore referenced base libraries the host lacks — never overwrite one it has.
    restored: list[str] = []
    for lib_id, lib in bundle.base_libraries.items():
        if not _LIB_ID.match(lib_id):
            continue
        path = _components_dir() / f"{lib_id}.sqlite"
        if not path.exists():
            path.write_bytes(write_sqlite(library_to_workbook(lib)))
            restored.append(lib_id)

    counts = store.put_model(session_id, bundle.model)
    logger.info(
        "imported project '%s' into %s: %d project libs, %d base libs restored",
        bundle.name,
        session_id,
        len(bundle.session_libraries),
        len(restored),
    )
    return {
        "sessionId": session_id,
        "name": bundle.name,
        "sheets": counts,
        "project_libraries": list(bundle.session_libraries.keys()),
        "restored_base_libraries": restored,
    }


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
    scope: str = "base"  # "base" (shared) | "session" (this project's own)


@router.post("/session/{session_id}/instantiate")
def instantiate_component(session_id: str, body: InstantiateInsert) -> dict[str, Any]:
    """Stamp a fresh component instance into the session's node hierarchy."""
    lib = _resolve_library(session_id, body.library, body.scope)
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

    Place ``technology`` from ``library`` as a fresh ASSET under ``parent_id``,
    with its ``capacity``; the technology's MACC measures come along.
    """

    library: str
    technology: str
    parent_id: str
    capacity: float = 1000.0
    instance_id: str | None = None
    scope: str = "base"  # "base" (shared) | "session" (this project's own)


@router.post("/session/{session_id}/place-technology")
def place_technology_route(session_id: str, body: PlaceTechnology) -> dict[str, Any]:
    """Add one technology as a asset node to the session's hierarchy."""
    lib = _resolve_library(session_id, body.library, body.scope)
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


# ── Network alternatives ──────────────────────────────────────────────────
# An "alternative" is another technology the optimiser may switch a asset to.
# It's a NETWORK choice (not baked into the Component library): adding one
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
    (from ``library`` in ``scope``) as a switch target for ``asset_id``."""

    library: str
    technology: str
    asset_id: str
    scope: str = "base"  # "base" | "session"
    capex_per_capacity: float = 0.0


@router.post("/session/{session_id}/alternative")
def add_alternative_route(session_id: str, body: AddAlternative) -> dict[str, Any]:
    """Make a technology an alternative the optimiser may switch the asset to."""
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
            for m in model.get("assets", [])
            if str(m.get("asset_id")) == body.asset_id
        ),
        None,
    )
    if not baseline:
        raise HTTPException(
            status_code=422, detail=f"asset '{body.asset_id}' has no baseline technology"
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
