"""JobStore: cancellation is sticky and the store stays bounded."""

from __future__ import annotations

import pytest

import pathwise.api.jobs as jobs_mod
from pathwise.api.jobs import JobStore


def test_cancel_is_not_overwritten_by_a_late_completion() -> None:
    # A worker thread finishing just after a DELETE must not resurrect the job:
    # a late _set(status="done") on a cancelled job is ignored.
    store = JobStore()
    jid = "j1"
    store._jobs[jid] = {"jobId": jid, "status": "running", "result": None}
    assert store.cancel(jid)
    store._set(jid, status="done", result={"ok": True})
    state = store.get(jid)
    assert state is not None and state["status"] == "cancelled"


def test_store_evicts_oldest_terminal_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    # Submitting beyond the cap evicts an old terminal job rather than growing
    # without bound; running jobs are never evicted.
    monkeypatch.setattr(jobs_mod, "_MAX_JOBS", 2)
    store = JobStore()
    store._jobs["old0"] = {"jobId": "old0", "status": "done", "result": None}
    store._jobs["old1"] = {"jobId": "old1", "status": "done", "result": None}
    store.submit(lambda _payload: {}, {})  # trivial job → exceeds the cap of 2
    assert len(store._jobs) <= 2
