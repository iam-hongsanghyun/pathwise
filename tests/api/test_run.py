"""P3 API: submit a run and poll to completion."""

from __future__ import annotations

import copy
import time
from typing import Any

from fastapi.testclient import TestClient

from pathwise.api.main import app
from tests.data.example import example_workbook

client = TestClient(app)


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


def test_config_lists_portfolio_backend() -> None:
    bundle = client.get("/api/config").json()
    names = {b["name"] for b in bundle["backends"]}
    assert {"linopy", "portfolio"} <= names


def test_portfolio_backend_run() -> None:
    payload = {
        "model": _workbook_two_candidates(),
        "scenario": {
            "domain": "process",
            "economics": {"base_year": 2025},
            "portfolio": {"method": "mvo", "n_scenarios": 500},
        },
        "options": {"domain": "process", "backend": "portfolio"},
    }
    state = _run_to_done(payload)
    assert state["status"] == "done"
    pf = state["result"]["outputs"]["portfolio"]
    assert pf["method"] == "mvo"
    assert abs(sum(a["weight"] for a in pf["assets"]) - 1.0) < 1e-4


def test_unknown_job_404() -> None:
    assert client.get("/api/run/nope").status_code == 404
