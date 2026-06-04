"""Backend registry — selects the solver backend for a run.

A run picks its backend via ``options["backend"]`` (default ``"linopy"``).
Adding a future backend is a one-line :func:`register_backend` call.
"""

from __future__ import annotations

from typing import Any

from pathwise.backends.base import Backend, BackendError
from pathwise.backends.linopy_backend import LinopyBackend

DEFAULT_BACKEND = "linopy"

_BACKENDS: dict[str, Backend] = {}


def register_backend(backend: Backend) -> None:
    """Register a backend under its ``name`` (last writer wins)."""
    _BACKENDS[backend.name.lower()] = backend


# Reference adapter is always available.
register_backend(LinopyBackend())


def get_backend(name: str | None = None) -> Backend:
    """Return the backend for ``name``, defaulting to linopy.

    Raises:
        BackendError: If ``name`` is given but not registered.
    """
    key = (name or DEFAULT_BACKEND).strip().lower() or DEFAULT_BACKEND
    backend = _BACKENDS.get(key)
    if backend is None:
        available = ", ".join(sorted(_BACKENDS)) or "(none)"
        raise BackendError(f"Unknown backend '{name}'. Available: {available}.")
    return backend


def available_backends() -> list[dict[str, Any]]:
    """Return the capability descriptor of every registered backend."""
    return [b.capabilities() for b in _BACKENDS.values()]
