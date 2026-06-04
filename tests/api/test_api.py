"""API tests via FastAPI TestClient: discovery, validate, run→poll→done."""

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


def test_health_and_status(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"
    status = client.get("/api/status").json()
    assert status["ready"] is True and status["buildId"]


def test_config_lists_domains_and_backends(client: TestClient) -> None:
    cfg = client.get("/api/config").json()
    assert any(d["name"] == "shipping" for d in cfg["domains"])
    assert any(b["name"] == "linopy" for b in cfg["backends"])
    assert cfg["buildId"]


def test_domain_schema_endpoint(client: TestClient) -> None:
    resp = client.get("/api/domains/shipping/schema")
    assert resp.status_code == 200
    body = resp.json()
    assert body["terminology"]["asset"] == "Ship"
    assert "assets" in body["schema"]
    assert client.get("/api/domains/nope/schema").status_code == 404


def test_validate_endpoint(client: TestClient) -> None:
    good = client.post(
        "/api/validate", json={"model": _shipping_workbook(), "scenario": _scenario()}
    ).json()
    assert good["ok"] is True

    bad_wb = _shipping_workbook()
    bad_wb["assets"][0]["technology_id"] = "NUCLEAR"
    bad = client.post("/api/validate", json={"model": bad_wb, "scenario": _scenario()}).json()
    assert bad["ok"] is False and bad["errors"]


def test_run_poll_and_export(client: TestClient) -> None:
    submit = client.post(
        "/api/run",
        json={
            "model": _shipping_workbook(),
            "scenario": _scenario(),
            "options": {"domain": "shipping"},
        },
    ).json()
    job_id = submit["jobId"]
    assert submit["status"] == "running"

    # Poll until the job finishes (tiny model — finishes fast).
    deadline = time.time() + 60
    state = client.get(f"/api/run/{job_id}").json()
    while state["status"] == "running" and time.time() < deadline:
        time.sleep(0.1)
        state = client.get(f"/api/run/{job_id}").json()

    assert state["status"] == "done", state
    result = state["result"]
    np.testing.assert_allclose(result["objective"], 10300.0, rtol=1e-6)

    # Export the result to xlsx.
    export = client.post("/api/export/xlsx", json=result)
    assert export.status_code == 200
    assert export.content[:2] == b"PK"  # xlsx is a zip


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/api/run/deadbeef").status_code == 404
