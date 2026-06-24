"""The fleet-reallocation example shows a shared ship pool moving across lanes.

A carrier owns ONE pool of 85 interchangeable ships split across three lanes
(KR↔AU/US/EU). Total demand is flat at 8 500 kt/yr but migrates from EU to AU
over 2025→2050, so the Layer-1b MILP steams ships off the shrinking EU lane and
onto the growing AU lane while the pool stays fully used every year.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any

from pathwise.api.workbook_io import parse_sqlite
from pathwise.backends.registry import get_backend

_SC = {
    "economics": {"base_year": 2025},
    "horizon": {"start": 2025, "end": 2050},
    "optimisation_scope": "system",
    "optimisation_mode": "joint",
    "objective": "cost",
}


def _model() -> dict[str, Any]:
    return parse_sqlite(
        (files("pathwise.assets.examples") / "fleet_reallocation.sqlite").read_bytes()
    )


def _ships(res: dict[str, Any]) -> dict[tuple[str, int], int]:
    """{(lane_process, year): ships} from the fleet output."""
    return {(str(r["process"]), int(r["period"])): int(r["ships"]) for r in res["outputs"]["fleet"]}


def test_pool_reallocates_from_eu_to_au() -> None:
    res = get_backend("linopy").run(_model(), _SC, {})
    assert res["status"] == "optimal"
    s = _ships(res)
    # AU grows, EU shrinks, US holds — the pool follows the demand migration.
    assert s[("p_au", 2050)] > s[("p_au", 2025)]
    assert s[("p_eu", 2050)] < s[("p_eu", 2025)]
    assert s[("p_us", 2025)] == s[("p_us", 2050)]
    # The shared pool is fully used in both the first and last year (85 ships).
    for year in (2025, 2050):
        assert sum(v for (_, y), v in s.items() if y == year) == 85


def test_all_demand_is_met() -> None:
    res = get_backend("linopy").run(_model(), _SC, {})
    assert res["status"] == "optimal"
    delivered = sum(float(r["value"]) for r in res["outputs"]["throughput"])
    assert abs(delivered - 8500.0 * 6) < 1e-6  # 8 500 kt/yr × 6 periods, all served
