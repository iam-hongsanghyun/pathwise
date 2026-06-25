"""Model file round-trips: a project exports to .xlsx / .sqlite and re-imports
losslessly — the same model assembles and solves to the same answer.

Backs the Project tab's "Model file (spreadsheet / database)" export/import
(PyPSA-style). The IO is fully generic (one sheet/table per model sheet), so new
sheets — `units`, `markets`, `impact_prices` — round-trip with everything else.
"""

from __future__ import annotations

import io
from importlib.resources import files
from typing import Any

import numpy as np
import pandas as pd

from pathwise.api.workbook_io import (
    parse_sqlite,
    parse_xlsx,
    write_sqlite,
    write_template_xlsx,
    write_xlsx,
)
from pathwise.backends.registry import get_backend
from pathwise.data.aliases import normalize_workbook
from pathwise.data.schema import template_columns

_SC = {
    "economics": {"base_year": 2025},
    "horizon": {"start": 2025, "end": 2025},
    "optimisation_scope": "system",
    "optimisation_mode": "joint",
    "objective": "cost",
}


def _methanol() -> dict[str, Any]:
    # The bundled .sqlite predates the rename (old sheet/column names); normalise to
    # the current vocabulary, matching how the app loads it (the session store does).
    return normalize_workbook(
        parse_sqlite((files("pathwise.assets.examples") / "transport_methanol.sqlite").read_bytes())
    )


def _objective(model: dict[str, Any]) -> float:
    res = get_backend("linopy").run(model, _SC, {})
    assert res["status"] == "optimal"
    return float(res["objective"])


def test_xlsx_roundtrip_solves_identically() -> None:
    base = _methanol()
    rt = parse_xlsx(write_xlsx(base))
    # The market + impact sheets survive the spreadsheet round-trip.
    assert {"markets", "io", "impacts", "flows"} <= set(rt)
    np.testing.assert_allclose(_objective(rt), _objective(base), rtol=1e-9)


def test_sqlite_roundtrip_solves_identically() -> None:
    base = _methanol()
    rt = parse_sqlite(write_sqlite(base))
    np.testing.assert_allclose(_objective(rt), _objective(base), rtol=1e-9)


def test_new_sheets_roundtrip_through_xlsx() -> None:
    # A registry (`units`) + an ETS market + a carbon price all survive .xlsx.
    model: dict[str, Any] = {
        "units": [{"unit": "kt", "dimension": "mass", "factor_to_base": 1000.0}],
        "markets": [
            {
                "market_id": "ets_kr",
                "target": "CO2",
                "company": "all",
                "allocation": 100.0,
                "price": 90.0,
            }
        ],
        "impact_prices": [{"impact_id": "CO2", "year": 2025, "price": 50.0}],
    }
    rt = parse_xlsx(write_xlsx(model))
    assert rt["units"][0]["unit"] == "kt"
    assert float(rt["units"][0]["factor_to_base"]) == 1000.0
    assert rt["markets"][0]["market_id"] == "ets_kr"
    assert float(rt["markets"][0]["allocation"]) == 100.0
    assert float(rt["impact_prices"][0]["price"]) == 50.0


def test_blank_template_has_entity_and_temporal_tabs_with_headers() -> None:
    cols = template_columns()
    frames = pd.read_excel(io.BytesIO(write_template_xlsx(cols)), sheet_name=None)
    # Each entity is its own tab.
    for sheet in ["technologies", "levers", "flows", "markets", "io", "impacts", "demand"]:
        assert sheet in frames, f"missing entity tab {sheet}"
    # Temporal data lives in _t / _t__field tabs.
    assert "io_t" in frames and "markets_t__price" in frames
    assert any(s.endswith("_t") or "_t__" in s for s in frames)
    # Header row matches the schema, with no data rows to fill in from.
    assert list(frames["markets"].columns) == cols["markets"]
    assert len(frames["technologies"].index) == 0
