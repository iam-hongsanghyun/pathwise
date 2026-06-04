"""End-to-end backend tests: workbook + scenario → result dict."""

from __future__ import annotations

import numpy as np

from pathwise.backends import available_backends, get_backend
from tests.domains.shipping.test_shipping_pack import _shipping_workbook


def _scenario_dict() -> dict:
    return {
        "name": "tier1",
        "domain": "shipping",
        "selection": {"target_set": "Tier1"},
        "economics": {"discount_rate": 0.0, "base_period": 2025, "capex_convention": "npv"},
    }


def test_backend_registered() -> None:
    caps = {b["name"] for b in available_backends()}
    assert "linopy" in caps
    assert get_backend("linopy").capabilities()["solver"] == "HiGHS"


def test_run_end_to_end_result_shape() -> None:
    backend = get_backend("linopy")
    result = backend.run(_shipping_workbook(), _scenario_dict(), {"domain": "shipping"})

    assert result["status"] == "optimal"
    np.testing.assert_allclose(result["objective"], 10300.0, rtol=1e-6)

    # Decisions are surfaced.
    chosen = {
        (c["asset"], c["technology"], c["period"]) for c in result["outputs"]["chosen_technology"]
    }
    assert ("ship1", "HFO", 2025) in chosen
    assert ("ship1", "LNG", 2030) in chosen
    assert any(
        t["to_technology"] == "LNG" and t["period"] == 2030
        for t in result["outputs"]["transitions"]
    )

    # Summary present for every period; terminology echoed.
    years = {p["period"] for p in result["summary"]["periods"]}
    assert years == {2025, 2030}
    assert result["terminology"]["asset"] == "Ship"


def test_run_surfaces_terminology_and_no_slack_when_feasible() -> None:
    result = get_backend("linopy").run(_shipping_workbook(), _scenario_dict(), {})
    assert result["outputs"]["slack"] == []
