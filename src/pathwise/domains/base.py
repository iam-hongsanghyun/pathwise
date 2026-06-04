"""Domain-pack abstraction and registry.

A *domain pack* maps a sector's vocabulary and data layout onto the generic
process-network model. The core never imports a pack; a pack imports the data
schema + assembler. Adding a sector touches only its own subpackage plus one
:func:`register_domain` call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pathwise.core.problem import Problem
from pathwise.data.assemble import assemble_problem
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.validation import ValidationReport, validate
from pathwise.data.workbook import Workbook


class DomainError(Exception):
    """Raised when a requested domain is unknown."""


class DomainPack(ABC):
    """Contract every sector pack implements."""

    name: str
    label: str

    @abstractmethod
    def required_sheets(self) -> list[str]:
        """Workbook sheets that must be present."""

    @abstractmethod
    def schema(self) -> dict[str, Any]:
        """Workbook schema (sheets → column descriptors) for the UI."""

    @abstractmethod
    def terminology(self) -> dict[str, str]:
        """Label overrides (e.g. ``{"process": "Facility"}``)."""

    def capabilities(self) -> dict[str, Any]:
        """JSON-serialisable capability descriptor for the handshake."""
        return {
            "name": self.name,
            "label": self.label,
            "terminology": self.terminology(),
            "requiredSheets": self.required_sheets(),
            "schema": self.schema(),
        }

    def validate(self, workbook: Workbook) -> ValidationReport:
        """Validate a workbook for this domain (default: shared validator)."""
        return validate(workbook)

    def build_problem(self, workbook: Workbook, scenario: ScenarioConfig) -> Problem:
        """Translate a workbook + scenario into the core IR (default assembler)."""
        return assemble_problem(workbook, scenario)


_DOMAINS: dict[str, DomainPack] = {}


def register_domain(domain: DomainPack) -> None:
    """Register a domain pack under its ``name`` (last writer wins)."""
    _DOMAINS[domain.name.lower()] = domain


def get_domain(name: str | None = None) -> DomainPack:
    """Return the pack for ``name`` (or the sole pack if unambiguous)."""
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
    """Capability descriptors of every registered domain."""
    return [d.capabilities() for d in _DOMAINS.values()]
