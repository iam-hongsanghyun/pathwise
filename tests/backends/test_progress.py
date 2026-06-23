"""Run-progress reporting: multi-solve backends publish completed/total counts.

The job store hands every backend a ``progress(done, total, label)`` callback;
backends that loop (the frontier ε-constraint sweep, the portfolio per-asset
reward pass) call it so the client can poll a live "12 / 40 runs" status. Single
solve backends accept the callback and never call it.
"""

from __future__ import annotations

import copy
import time
from importlib.resources import files
from typing import Any

from pathwise.api.jobs import JobStore
from pathwise.api.workbook_io import parse_sqlite
from pathwise.backends.registry import get_backend
from tests.data.example import example_workbook

_BASE_SCENARIO: dict[str, Any] = {
    "economics": {"base_year": 2025},
    "horizon": {"start": 2025, "end": 2025},
    "optimisation_scope": "system",
    "optimisation_mode": "joint",
}


def _methanol_model() -> dict[str, Any]:
    return parse_sqlite(
        (files("pathwise.assets.examples") / "transport_methanol.sqlite").read_bytes()
    )


def test_frontier_reports_one_tick_per_cap_point() -> None:
    """Each cap point is one full solve → one progress tick, done counting up to total."""
    calls: list[tuple[int, int, str]] = []
    scenario = {
        **_BASE_SCENARIO,
        "frontier": {"impact": "CO2", "from": 0.0, "to": 600000.0, "step": 200000.0},
    }
    res = get_backend("frontier").run(
        _methanol_model(),
        scenario,
        {},
        progress=lambda done, total, label: calls.append((done, total, label)),
    )

    n_points = len(res["outputs"]["frontier"]["points"])
    assert n_points >= 2
    # One tick per point, completed count marching 1..n, total stable at n.
    assert [done for done, _, _ in calls] == list(range(1, n_points + 1))
    assert all(total == n_points for _, total, _ in calls)
    # The label carries the swept impact + cap so the UI can show context.
    assert all("CO2" in label for _, _, label in calls)


def test_portfolio_reports_progress_over_assets() -> None:
    """The per-asset reward pass ticks once per asset, ending done == total."""
    wb = copy.deepcopy(example_workbook())
    # A second candidate switch so there are two assets to allocate across.
    wb["transitions"].append(
        {
            "from_technology": "EAF",
            "to_technology": "BF",
            "action": "replace",
            "capex_per_capacity": 200.0,
            "compatible": True,
        }
    )
    calls: list[tuple[int, int, str]] = []
    res = get_backend("portfolio").run(
        wb,
        {"domain": "process", "economics": {"base_year": 2025}, "portfolio": {"method": "mvo"}},
        {"domain": "process"},
        progress=lambda done, total, label: calls.append((done, total, label)),
    )

    assert res["status"] == "optimal"
    assert calls, "portfolio backend reported no progress"
    # Final tick marks every asset complete (two candidates → total 2).
    assert calls[-1][0] == calls[-1][1] == 2


def test_single_solve_backend_accepts_progress() -> None:
    """linopy solves once: it accepts the callback (protocol uniformity) but never calls it."""
    calls: list[tuple[int, int, str]] = []
    res = get_backend("linopy").run(
        _methanol_model(),
        {**_BASE_SCENARIO, "objective": "cost"},
        {},
        progress=lambda done, total, label: calls.append((done, total, label)),
    )
    assert res["status"] == "optimal"
    assert calls == []


def test_jobstore_threads_progress_into_state() -> None:
    """A job body's ``report`` calls land on the polled job state's ``progress`` field."""
    store = JobStore()

    def body(payload: dict[str, Any], report: Any) -> dict[str, Any]:
        report(1, 2, "half")
        report(2, 2, "all")
        return {"status": "done"}

    job_id = store.submit(body, {})
    state: dict[str, Any] | None = None
    for _ in range(500):
        state = store.get(job_id)
        if state and state["status"] == "done":
            break
        time.sleep(0.01)
    assert state is not None and state["status"] == "done"
    assert state["progress"] == {"done": 2, "total": 2, "label": "all"}
