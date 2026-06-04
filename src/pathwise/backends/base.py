"""Solver-backend abstraction.

A *backend* takes the in-memory workbook plus the scenario/options and returns
pathwise's result dict. The linopy backend is the reference adapter
(:mod:`pathwise.backends.linopy_backend`); this Protocol is the only contract a
future backend (e.g. a different solver or a heuristic) must satisfy. The seam
mirrors the reference ``ragnarok`` design.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pathwise.data.workbook import Workbook


class BackendError(Exception):
    """Raised when a requested backend is unknown or cannot fulfil a run."""


@runtime_checkable
class Backend(Protocol):
    """The contract every optimisation backend implements.

    Attributes:
        name: Stable machine id used in ``options["backend"]`` (e.g. ``"linopy"``).
        label: Human-readable name shown in the UI.
    """

    name: str
    label: str

    def capabilities(self) -> dict[str, Any]:
        """Return a JSON-serialisable description of what this backend supports."""
        ...

    def run(
        self,
        model: Workbook,
        scenario: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build, solve, and extract results for one case.

        Args:
            model: The in-memory workbook (``{sheet: rows[]}``).
            scenario: The run definition (a :class:`ScenarioConfig` as a dict).
            options: Run metadata (``domain``, ``backend``, solver overrides).

        Returns:
            pathwise's result dict (status, objective, outputs, summary).
        """
        ...
