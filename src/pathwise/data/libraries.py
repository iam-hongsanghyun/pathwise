"""Auto-discovered, importable libraries — the sector-agnostic model catalogue.

A *library* is a single **SQLite** workbook bundling **components** (streams /
technologies / measures) and a **value chain** (nodes / machines / connections /
demand / caps). They live under ``<libraries_dir>/<tier>/<id>.sqlite`` where
``tier`` is the parent folder — ``base`` (reference-confirmed building blocks),
``example`` (illustrative models) or ``project`` (specific real projects). A
legacy ``<id>.json`` is still read if no ``.sqlite`` is present, so externally
supplied JSON workbooks import unchanged.

There is **no index**: dropping a file into a tier folder is enough — the
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
#: Workbook suffixes a library may ship as, in preference order.
_SUFFIXES = (".sqlite", ".db", ".json")


def _read_workbook(path: Path) -> dict[str, Any]:
    """Parse a library workbook from SQLite (preferred) or JSON, by suffix."""
    if path.suffix in (".sqlite", ".db"):
        from pathwise.api.workbook_io import parse_sqlite

        return parse_sqlite(path.read_bytes())
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


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
    """Every library under ``root``: one entry per ``<tier>/<id>`` workbook.

    No index file — the catalogue IS the set of workbook files on disk, so adding
    a library is just adding a file. A ``.sqlite`` wins over a same-stem ``.json``.
    Returns ``{id, tier, label, has_value_chain, has_components}`` sorted by tier
    then id.
    """
    root = Path(root)
    out: list[dict[str, Any]] = []
    for tier in TIERS:
        tier_dir = root / tier
        # One entry per stem; prefer SQLite when both formats are present.
        by_stem: dict[str, Path] = {}
        for suffix in _SUFFIXES:
            for path in tier_dir.glob(f"*{suffix}"):
                by_stem.setdefault(path.stem, path)
        for _stem, path in sorted(by_stem.items()):
            try:
                wb = _read_workbook(path)
            except (json.JSONDecodeError, OSError, ValueError):
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
    """The raw workbook for one library (SQLite preferred), or ``FileNotFoundError``."""
    safe = "".join(c for c in library_id if c.isalnum() or c in "-_.")
    if tier not in TIERS:
        raise FileNotFoundError(f"unknown tier '{tier}'")
    tier_dir = Path(root) / tier
    for suffix in _SUFFIXES:
        path = tier_dir / f"{safe}{suffix}"
        if path.exists():
            return _read_workbook(path)
    raise FileNotFoundError(f"unknown library '{tier}/{library_id}'")
