"""pathwise.backends — pluggable solver backends and registry."""

from __future__ import annotations

from pathwise.backends.base import Backend, BackendError
from pathwise.backends.linopy_backend import LinopyBackend
from pathwise.backends.registry import available_backends, get_backend, register_backend

__all__ = [
    "Backend",
    "BackendError",
    "LinopyBackend",
    "available_backends",
    "get_backend",
    "register_backend",
]
