"""API tests via FastAPI TestClient: the minimal contract (config + run)."""

from __future__ import annotations

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pathwise.api.main import app
from tests.domains.shipping.test_shipping_pack import _shipping_workbook


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _scenario() -> dict:
    return {
        "name": "tier1",
        "domain": "shipping",
        "selection": {"target_set": "Tier1"},
        "economics": {"discount_rate": 0.0, "base_period": 2025, "capex_convention": "npv"},
    }


def _run_to_done(client: TestClient, model: dict, scenario: dict) -> dict:
    submit = client.post(
        "/api/run", json={"model": model, "scenario": scenario, "options": {"domain": "shipping"}}
    ).json()
    assert submit["status"] == "running"
    job_id = submit["jobId"]
    deadline = time.time() + 60
    state = client.get(f"/api/run/{job_id}").json()
    while state["status"] == "running" and time.time() < deadline:
        time.sleep(0.1)
        state = client.get(f"/api/run/{job_id}").json()
    assert state["status"] == "done", state
    return state["result"]


def test_health_and_status(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"
    status = client.get("/api/status").json()
    assert status["ready"] is True and status["buildId"]


def test_config_handshake_has_backend_truths_only(client: TestClient) -> None:
    cfg = client.get("/api/config").json()
    assert any(d["name"] == "shipping" for d in cfg["domains"])
    assert any(b["name"] == "linopy" for b in cfg["backends"])
    assert cfg["server"]["maxSolverTimeLimitS"] > 0
    assert cfg["buildId"]
    # No user-definable model defaults leak from the backend handshake.
    assert "defaults" not in cfg


def test_run_returns_entire_result(client: TestClient) -> None:
    result = _run_to_done(client, _shipping_workbook(), _scenario())
    assert result["status"] == "optimal"
    np.testing.assert_allclose(result["objective"], 10300.0, rtol=1e-6)
    assert result["validation"]["errors"] == []
    chosen = {
        (c["asset"], c["technology"], c["period"]) for c in result["outputs"]["chosen_technology"]
    }
    assert ("ship1", "LNG", 2030) in chosen
    assert {p["period"] for p in result["summary"]["periods"]} == {2025, 2030}


def test_invalid_workbook_surfaces_in_result_not_a_round_trip(client: TestClient) -> None:
    bad = _shipping_workbook()
    bad["assets"][0]["technology_id"] = "NUCLEAR"  # dangling reference
    result = _run_to_done(client, bad, _scenario())
    assert result["status"] == "invalid"
    assert result["objective"] is None
    assert any("NUCLEAR" in e for e in result["validation"]["errors"])


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/api/run/deadbeef").status_code == 404
