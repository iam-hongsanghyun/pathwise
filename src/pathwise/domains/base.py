"""Sector-pack abstraction and registry.

A *domain pack* maps one sector's vocabulary and data layout onto the generic
optimisation model. The generic core never imports a pack; a pack imports only
the core IR, the generic assembler, and this base. Adding a sector therefore
touches only its own subpackage plus one :func:`register_domain` call.

The default :meth:`DomainPack.build_problem` delegates to the domain-agnostic
:func:`pathwise.data.assemble.assemble_problem`, so most packs only need to
declare their schema, terminology, and required sheets. A pack may override
``build_problem``/``validate``/``extract`` for sector-specific behaviour.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pathwise.core.problem import OptimisationProblem
from pathwise.data.assemble import assemble_problem
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.validation import ValidationReport, require_sheets
from pathwise.data.workbook import Workbook, workbook_to_frames


class DomainError(Exception):
    """Raised when a requested domain is unknown."""


class DomainPack(ABC):
    """Contract every sector pack implements.

    Subclasses set :attr:`name`/:attr:`label` and implement :meth:`schema`,
    :meth:`terminology`, and :meth:`required_sheets`. The remaining methods have
    domain-agnostic defaults.
    """

    name: str
    label: str

    @abstractmethod
    def required_sheets(self) -> list[str]:
        """Return the workbook sheets that must be present for a run."""

    @abstractmethod
    def schema(self) -> dict[str, Any]:
        """Return the workbook schema (sheets → column descriptors) for the UI."""

    @abstractmethod
    def terminology(self) -> dict[str, str]:
        """Return label overrides (e.g. ``{"asset": "Ship", "technology": "Engine"}``)."""

    def capabilities(self) -> dict[str, Any]:
        """Return a JSON-serialisable capability descriptor for ``GET /api/domains``."""
        return {
            "name": self.name,
            "label": self.label,
            "terminology": self.terminology(),
            "requiredSheets": self.required_sheets(),
            "schema": self.schema(),
        }

    def validate(self, workbook: Workbook) -> ValidationReport:
        """Validate a workbook for this domain (default: required-sheet check)."""
        report = ValidationReport()
        frames = workbook_to_frames(workbook)
        require_sheets(frames, self.required_sheets(), report)
        return report

    def build_problem(self, workbook: Workbook, scenario: ScenarioConfig) -> OptimisationProblem:
        """Translate a workbook + scenario into the core IR (default: generic assembler)."""
        return assemble_problem(workbook, scenario)


_DOMAINS: dict[str, DomainPack] = {}


def register_domain(domain: DomainPack) -> None:
    """Register a domain pack under its ``name`` (last writer wins)."""
    _DOMAINS[domain.name.lower()] = domain


def get_domain(name: str | None = None) -> DomainPack:
    """Return the pack for ``name``.

    Args:
        name: Domain id; if ``None`` the single registered domain is returned
            when unambiguous.

    Raises:
        DomainError: If ``name`` is unknown, or ``None`` with multiple domains.
    """
    if name is None:
        if len(_DOMAINS) == 1:
            return next(iter(_DOMAINS.values()))
        raise DomainError("a domain name is required when multiple are registered")
    pack = _DOMAINS.get(name.strip().lower())
    if pack is None:
        available = ", ".join(sorted(_DOMAINS)) or "(none)"
        raise DomainError(f"Unknown domain '{name}'. Available: {available}.")
    return pack


def available_domains() -> list[dict[str, Any]]:
    """Return the capability descriptor of every registered domain."""
    return [d.capabilities() for d in _DOMAINS.values()]


def clear_domains() -> None:
    """Remove all registered domains (test helper)."""
    _DOMAINS.clear()
