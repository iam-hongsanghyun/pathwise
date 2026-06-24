"""The shipping-carrier fleet-transition example shows the policy balloon effect.

A carrier runs ~100 ships on KR↔AU/US/EU lanes (HFO/LNG, vintaged) and can
re-engine to ammonia from 2030. Each lane's emissions are priced by its
counterpart (EU highest → AU lowest). Under that per-region policy the high-price
lane (EU) decarbonises fully while the lax lane (AU) keeps burning fossil — the
balloon effect. With no carbon price nobody re-engines.
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
        (files("pathwise.assets.examples") / "shipping_carrier.sqlite").read_bytes()
    )


def _ammonia_kt(res: dict[str, Any], lane: str) -> float:
    """Total ammonia-ship throughput on a lane across the horizon [kt]."""
    tech = f"ship_{lane}_ammonia"
    return sum(
        float(r["value"])
        for r in res["outputs"].get("throughput", [])
        if str(r["technology"]) == tech
    )


def test_no_carbon_price_keeps_the_fleet_fossil() -> None:
    wb = {**_model(), "impact_prices": []}  # strip the per-region prices
    res = get_backend("linopy").run(wb, _SC, {})
    assert res["status"] == "optimal"
    total_ammonia = sum(_ammonia_kt(res, r) for r in ("au", "us", "eu"))
    assert total_ammonia < 1.0  # nobody re-engines without a price signal


def test_per_region_policy_drives_the_balloon_effect() -> None:
    res = get_backend("linopy").run(_model(), _SC, {})
    assert res["status"] == "optimal"
    eu, us, au = _ammonia_kt(res, "eu"), _ammonia_kt(res, "us"), _ammonia_kt(res, "au")
    # The high-price lane decarbonises far more than the low-price lane.
    assert eu > us > au
    # EU re-engines fully (its 3500 kt/yr demand × ~5 ammonia-era periods).
    assert eu >= 3500.0 * 5
    # AU (lowest price) stays largely fossil.
    assert au < eu * 0.1
