"""The repo-derived sector examples (steel / shipping / petrochemical) solve.

Guards the shipped ``assets/examples/{steel,shipping,petrochemical}.sqlite`` —
each must build, solve at ``system`` scope, and meet demand. Heavy realistic
solves, so marked ``slow`` (skip with ``-m "not slow"``); regenerate them with
``scripts/build_sector_examples.py``.
"""

from __future__ import annotations

from importlib.resources import files

import pytest

from pathwise.api.workbook_io import parse_sqlite
from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("name", ["steel", "shipping", "petrochemical"])
def test_sector_example_solves_and_meets_demand(name: str) -> None:
    wb = parse_sqlite((files("pathwise.assets.examples") / f"{name}.sqlite").read_bytes())
    res = run_model(
        wb,
        ScenarioConfig.from_dict(
            {
                "economics": {"base_year": 2025},
                "optimisation_scope": "system",
                "solver": {"mip_gap": 0.02},
            }
        ),
    )
    assert res["status"] == "optimal"
    assert not res["outputs"]["demand_slack"]
    # Each example ships a baseline plus alternative options (technology
    # transitions and/or MACC measures) for the user to explore.
    assert wb.get("transitions") or wb.get("measures") or wb.get("io_t")
