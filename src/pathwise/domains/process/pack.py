"""The default ``process`` domain pack."""

from __future__ import annotations

from typing import Any

from pathwise.data.schema import REQUIRED_SHEETS, SCHEMA, TERMINOLOGY
from pathwise.domains.base import DomainPack


class ProcessDomain(DomainPack):
    """Generic process-network domain (facilities, streams, impacts, levers)."""

    name = "process"
    label = "Process network"

    def required_sheets(self) -> list[str]:
        return list(REQUIRED_SHEETS)

    def schema(self) -> dict[str, Any]:
        return SCHEMA

    def terminology(self) -> dict[str, str]:
        return TERMINOLOGY
