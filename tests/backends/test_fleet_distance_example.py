"""The fleet-distance example: a longer sea route needs more ships.

Same 1,200 kt to Sydney (near) and Rotterdam (far, via Suez). searoute gives the
sea distances; per-ship annual capacity falls with distance, so the far lane is
served by strictly more ships than the near one for identical demand.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Any

from pathwise.api.workbook_io import parse_sqlite
from pathwise.backends.registry import get_backend

_SC = {
    "economics": {"base_year": 2025},
    "horizon": {"start": 2025, "end": 2025},
    "optimisation_scope": "system",
    "optimisation_mode": "joint",
    "objective": "cost",
}


def _model() -> dict[str, Any]:
    return parse_sqlite((files("pathwise.assets.examples") / "fleet_distance.sqlite").read_bytes())


def _ships(res: dict[str, Any]) -> dict[str, int]:
    return {str(r["process"]): int(r["ships"]) for r in res["outputs"]["fleet"]}


def test_far_lane_needs_more_ships_than_near() -> None:
    res = get_backend("linopy").run(_model(), _SC, {})
    assert res["status"] == "optimal"
    ships = _ships(res)
    # Rotterdam (far) is ~2.3× the Sydney distance → strictly more ships, same demand.
    assert ships["p_eu"] > ships["p_au"]
    # Both demands are met (1,200 kt each).
    delivered = sum(float(r["value"]) for r in res["outputs"]["throughput"])
    assert abs(delivered - 2400.0) < 1e-6
