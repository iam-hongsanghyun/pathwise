"""Workbook schema — the model's table/column contract.

This module is a **thin reader**: the contract itself is *config*, not code, and
lives in :file:`schema.json` next to this file (UI labels, column types, tooltips
and the required-sheet list). Editing the contract means editing the JSON — no
Python change. The names below are kept so existing imports keep working.

The schema is consumed only by the editable-grid UI (served via ``/api/config``)
and by :mod:`pathwise.data.validation` (the required-sheet check). It is NOT used
to import a model: :func:`pathwise.api.workbook_io.parse_sqlite` reads whatever
tables a SQLite model holds, generically.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

_CONFIG: dict[str, Any] = json.loads(
    files("pathwise.data").joinpath("schema.json").read_text(encoding="utf-8")
)

#: Sheets that must be present for a run.
REQUIRED_SHEETS: list[str] = _CONFIG["requiredSheets"]

#: UI label overrides for generic concepts.
TERMINOLOGY: dict[str, str] = _CONFIG["terminology"]

#: Column descriptors per sheet (drives the frontend grid + tooltips/validation).
SCHEMA: dict[str, Any] = _CONFIG["sheets"]
