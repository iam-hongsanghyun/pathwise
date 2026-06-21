"""Shared router dependencies: session-store factories.

Both the session and component-library routers open the same on-disk stores
under the configured ``data_dir``; defining the factories once keeps them from
drifting apart.
"""

from __future__ import annotations

from pathlib import Path

from pathwise.api.session_library_store import SessionLibraryStore
from pathwise.api.session_store import SessionStore
from pathwise.config import get_settings


def session_store() -> SessionStore:
    """The session model store (``<data_dir>/sessions``)."""
    return SessionStore(Path(get_settings().data_dir) / "sessions")


def session_libs() -> SessionLibraryStore:
    """The session-scoped component-library store (``<data_dir>/session_libraries``)."""
    return SessionLibraryStore(Path(get_settings().data_dir) / "session_libraries")
