"""End-to-end tests for the portfolio backend."""

from __future__ import annotations

import copy
from typing import Any

from pathwise.backends.registry import available_backends, get_backend
from tests.data.example import example_workbook


def _scenario(**portfolio: Any) -> dict[str, Any]:
    return {
        "domain": "process",
        "economics": {"base_year": 2025},
        "portfolio": portfolio,
    }


def _workbook_two_candidates() -> dict[str, Any]:
    """Example workbook with a second candidate switch (EAF→BF on F2)."""
    wb = copy.deepcopy(example_workbook())
    wb["transitions"].append(
        {
            "from_technology": "EAF",
            "to_technology": "BF",
            "action": "replace",
            "capex_per_capacity": 200.0,
            "compatible": True,
        }
    )
    return wb


def test_portfolio_backend_is_registered() -> None:
    names = {b["name"] for b in available_backends()}
    assert "portfolio" in names


def test_run_returns_portfolio_block() -> None:
    res = get_backend("portfolio").run(
        _workbook_two_candidates(), _scenario(method="mvo"), {"domain": "process"}
    )
    assert res["status"] == "optimal"
    pf = res["outputs"]["portfolio"]
    weights = [a["weight"] for a in pf["assets"]]
    assert len(weights) == 2
    assert abs(sum(weights) - 1.0) < 1e-4
    # The existing MILP output arrays are present and empty (frontend non-break).
    assert res["outputs"]["throughput"] == []
    assert res["summary"]["periods"] == []


def test_seeded_run_is_reproducible() -> None:
    wb, sc = _workbook_two_candidates(), _scenario(method="cvar", n_scenarios=500)
    a = get_backend("portfolio").run(wb, sc, {"domain": "process"})
    b = get_backend("portfolio").run(wb, sc, {"domain": "process"})
    assert a["outputs"]["portfolio"]["assets"] == b["outputs"]["portfolio"]["assets"]


def test_too_few_assets_is_invalid() -> None:
    # The stock example has a single candidate transition (F1: BF→EAF).
    res = get_backend("portfolio").run(
        example_workbook(), _scenario(method="mvo"), {"domain": "process"}
    )
    assert res["status"] == "invalid"
    assert any("at least two" in e for e in res["validation"]["errors"])


def test_mvo_frontier_is_populated() -> None:
    res = get_backend("portfolio").run(
        _workbook_two_candidates(), _scenario(method="mvo"), {"domain": "process"}
    )
    pf = res["outputs"]["portfolio"]
    assert pf["frontier"]
    assert all("return" in p and "risk" in p for p in pf["frontier"])
