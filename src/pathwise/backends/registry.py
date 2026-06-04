"""Solver-backend registry."""

from __future__ import annotations

from typing import Any, Protocol

from pathwise.backends.linopy_backend import LinopyBackend
from pathwise.data.workbook import Workbook


class Backend(Protocol):
    """A solver backend: turns a model + scenario into a result dict."""

    name: str
    label: str

    def capabilities(self) -> dict[str, Any]: ...

    def run(
        self, model: Workbook, scenario: dict[str, Any], options: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


_BACKENDS: dict[str, Backend] = {}


def register_backend(backend: Backend) -> None:
    """Register a backend under its ``name``."""
    _BACKENDS[backend.name.lower()] = backend


def get_backend(name: str | None = None) -> Backend:
    """Return the backend for ``name`` (default: ``linopy``)."""
    return _BACKENDS[(name or "linopy").lower()]


def available_backends() -> list[dict[str, Any]]:
    """Capability descriptors of every registered backend."""
    return [b.capabilities() for b in _BACKENDS.values()]


register_backend(LinopyBackend())
