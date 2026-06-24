"""Model file round-trips: a project exports to .xlsx / .sqlite and re-imports
losslessly — the same model assembles and solves to the same answer.

Backs the Project tab's "Model file (spreadsheet / database)" export/import
(PyPSA-style). The IO is fully generic (one sheet/table per model sheet), so new
sheets — `units`, `markets`, `impact_prices` — round-trip with everything else.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any

import numpy as np

from pathwise.api.workbook_io import parse_sqlite, parse_xlsx, write_sqlite, write_xlsx
from pathwise.backends.registry import get_backend

_SC = {
    "economics": {"base_year": 2025},
    "horizon": {"start": 2025, "end": 2025},
    "optimisation_scope": "system",
    "optimisation_mode": "joint",
    "objective": "cost",
}


def _methanol() -> dict[str, Any]:
    return parse_sqlite(
        (files("pathwise.assets.examples") / "transport_methanol.sqlite").read_bytes()
    )


def _objective(model: dict[str, Any]) -> float:
    res = get_backend("linopy").run(model, _SC, {})
    assert res["status"] == "optimal"
    return float(res["objective"])


def test_xlsx_roundtrip_solves_identically() -> None:
    base = _methanol()
    rt = parse_xlsx(write_xlsx(base))
    # The market + impact sheets survive the spreadsheet round-trip.
    assert {"markets", "io", "impacts", "commodities"} <= set(rt)
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
