"""Per-session component libraries — a scenario's OWN component catalogue.

The shared *base* component libraries (``<data_dir>/component_libraries``) are
global and reusable. A *scenario* often needs its own components, and editing
them must not pollute the shared catalogue — so each session gets an isolated set
of component libraries here, one **SQLite** file per library under
``<data_dir>/session_libraries/<session_id>/<lib_id>.sqlite`` (the same
sheets-in-SQLite form the base libraries and examples use).

Together they give the "two sets" the builder shows: **base** (global) +
**session** (per-scenario).
"""

from __future__ import annotations

from pathlib import Path

from pathwise.api.workbook_io import parse_sqlite, write_sqlite
from pathwise.data.components import ComponentLibrary, library_from_workbook, library_to_workbook


def _safe(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "-_.")


class SessionLibraryStore:
    """Component libraries scoped to one session (isolated SQLite files)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _dir(self, session_id: str, *, create: bool = False) -> Path:
        d = self.root / _safe(session_id)
        if create:
            d.mkdir(parents=True, exist_ok=True)
        return d

    def list_ids(self, session_id: str) -> list[str]:
        """Library ids held for a session (alphabetical)."""
        d = self._dir(session_id)
        return sorted(p.stem for p in d.glob("*.sqlite")) if d.is_dir() else []

    def get(self, session_id: str, lib_id: str) -> ComponentLibrary | None:
        """A session library, or None if absent."""
        p = self._dir(session_id) / f"{_safe(lib_id)}.sqlite"
        return library_from_workbook(parse_sqlite(p.read_bytes())) if p.exists() else None

    def put(self, session_id: str, lib_id: str, library: ComponentLibrary) -> None:
        """Create/overwrite a session library (stored as SQLite)."""
        d = self._dir(session_id, create=True)
        (d / f"{_safe(lib_id)}.sqlite").write_bytes(write_sqlite(library_to_workbook(library)))

    def delete(self, session_id: str, lib_id: str) -> bool:
        """Remove one session library; return whether it existed."""
        p = self._dir(session_id) / f"{_safe(lib_id)}.sqlite"
        if p.exists():
            p.unlink()
            return True
        return False

    def delete_session(self, session_id: str) -> None:
        """Drop every library for a session (called when the session is cleared)."""
        d = self._dir(session_id)
        if d.is_dir():
            for p in d.glob("*.sqlite"):
                p.unlink()
            d.rmdir()
