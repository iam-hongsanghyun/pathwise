"""The sector-pack independence gate.

Proves the architectural promise: a new sector registers and is selectable
without touching the core or the shipping pack, and the generic core never
imports any sector.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pathwise.domains  # noqa: F401  (ensures built-ins are registered)
from pathwise.domains.base import DomainPack, available_domains, get_domain, register_domain


class _SteelStub(DomainPack):
    """A minimal second sector, added without changing core/shipping."""

    name = "steel"
    label = "Steel"

    def required_sheets(self) -> list[str]:
        return ["assets", "technologies", "carriers", "periods"]

    def schema(self) -> dict[str, Any]:
        return {"assets": {"label": "Plants", "columns": {}}}

    def terminology(self) -> dict[str, str]:
        return {"asset": "Plant", "technology": "Route", "carrier": "Reductant"}


def test_new_sector_registers_and_is_selectable() -> None:
    register_domain(_SteelStub())
    names = {d["name"] for d in available_domains()}
    assert {"shipping", "steel"} <= names
    assert get_domain("steel").terminology()["asset"] == "Plant"
    # Registering steel does not perturb shipping.
    assert get_domain("shipping").terminology()["asset"] == "Ship"


def test_core_never_imports_a_sector() -> None:
    """No module under pathwise.core may import pathwise.domains."""
    core_dir = Path(__file__).resolve().parents[2] / "src" / "pathwise" / "core"
    offenders = []
    for py in core_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "pathwise.domains" in text or "import domains" in text:
            offenders.append(str(py))
    assert not offenders, f"core must not depend on any sector: {offenders}"
