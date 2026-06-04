"""P3 API: submit a run and poll to completion."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from pathwise.api.main import app
from tests.data.example import example_workbook

client = TestClient(app)


def _run_to_done(payload: dict, timeout_s: float = 60.0) -> dict:
    job = client.post("/api/run", json=payload).json()
    job_id = job["jobId"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        state = client.get(f"/api/run/{job_id}").json()
        if state["status"] in {"done", "error"}:
            return state
        time.sleep(0.1)
    raise AssertionError("run did not finish in time")


def test_run_returns_optimal_result() -> None:
    payload = {
        "model": example_workbook(),
        "scenario": {"domain": "process", "economics": {"base_year": 2025}},
        "options": {"domain": "process"},
    }
    state = _run_to_done(payload)
    assert state["status"] == "done"
    result = state["result"]
    assert result["status"] == "optimal"
    assert result["terminology"]["process"] == "Facility"


def test_unknown_job_404() -> None:
    assert client.get("/api/run/nope").status_code == 404
