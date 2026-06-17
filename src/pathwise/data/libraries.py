"""Auto-discovered, importable libraries — the sector-agnostic model catalogue.

A *library* is a single JSON workbook bundling **components** (streams /
technologies / measures) and a **value chain** (nodes / machines / connections /
demand / caps). They live under ``<libraries_dir>/<tier>/<id>.json`` where
``tier`` is the parent folder — ``base`` (reference-confirmed building blocks),
``example`` (illustrative models) or ``project`` (specific real projects).

There is **no index**: dropping a JSON file into a tier folder is enough — the
catalogue is discovered by globbing, and importing it builds the components (into
the session component library) and, when the workbook carries a node hierarchy,
the value chain (into the session model). This keeps pathwise sector-agnostic:
new sectors are data, not code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TIERS = ("base", "example", "project")


def _label(workbook: dict[str, Any], fallback: str) -> str:
    """A library's display label from its ``meta`` sheet, else the file stem."""
    for row in workbook.get("meta", []) or []:
        if row.get("key") == "label" and row.get("value"):
            return str(row["value"])
    return fallback


def _has_value_chain(workbook: dict[str, Any]) -> bool:
    """Whether the workbook carries a value-chain structure (a node hierarchy)."""
    return bool(workbook.get("nodes"))


def discover_libraries(root: str | Path) -> list[dict[str, Any]]:
    """Every library under ``root``: one entry per ``<tier>/<id>.json`` file.

    No index file — the catalogue IS the set of JSON files on disk, so adding a
    library is just adding a file. Returns ``{id, tier, label, has_value_chain,
    has_components}`` sorted by tier then id.
    """
    root = Path(root)
    out: list[dict[str, Any]] = []
    for tier in TIERS:
        for path in sorted((root / tier).glob("*.json")):
            try:
                wb = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            out.append(
                {
                    "id": path.stem,
                    "tier": tier,
                    "label": _label(wb, path.stem),
                    "has_value_chain": _has_value_chain(wb),
                    "has_components": bool(
                        wb.get("technologies") or wb.get("commodities") or wb.get("measures")
                    ),
                }
            )
    return out


def load_library_workbook(root: str | Path, tier: str, library_id: str) -> dict[str, Any]:
    """The raw workbook JSON for one library, or raise ``FileNotFoundError``."""
    safe = "".join(c for c in library_id if c.isalnum() or c in "-_.")
    if tier not in TIERS:
        raise FileNotFoundError(f"unknown tier '{tier}'")
    path = Path(root) / tier / f"{safe}.json"
    if not path.exists():
        raise FileNotFoundError(f"unknown library '{tier}/{library_id}'")
    wb: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return wb
