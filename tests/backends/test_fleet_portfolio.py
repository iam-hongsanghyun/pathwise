"""Layer 2 — fleet decarbonisation as a risk-vs-reward portfolio.

A carrier's re-engining options (HFO/LNG → ammonia on each lane) are exactly the
candidate transitions the portfolio backend treats as assets. Under Monte-Carlo
price shocks (fuel / carbon / capex volatility) it returns a risk-return portfolio
over those fleet investments — the "portfolio risk" half of Layer 2, on a fleet
model. (Stochastic discrete-event per-ship simulation and carrier competition stay
out of scope by design.)
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
}


def _model() -> dict[str, Any]:
    return parse_sqlite(
        (files("pathwise.assets.examples") / "shipping_carrier.sqlite").read_bytes()
    )


def test_portfolio_backend_scores_fleet_reengining_options() -> None:
    res = get_backend("portfolio").run(_model(), _SC, {})
    assert res["status"] == "optimal"
    pf = res["outputs"]["portfolio"]
    # Every asset is a re-engining transition to an ammonia ship-tech on some lane.
    assets = pf["assets"]
    assert len(assets) >= 2
    assert all("ammonia" in str(a["to_technology"]) for a in assets)
    # A real risk-return portfolio: weights sum to ~1, and risk/return are reported.
    assert abs(sum(float(a["weight"]) for a in assets) - 1.0) < 1e-6
    assert "expected_return" in pf and "risk" in pf and "cvar" in pf
    assert len(pf["frontier"]) > 0  # the risk-return frontier is populated
