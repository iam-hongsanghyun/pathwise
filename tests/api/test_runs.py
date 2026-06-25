"""Persisted run history: the store keeps runs across a refresh, and a cache
clear drops the un-exported ones while keeping the exported ones."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pathwise.api.main import app
from pathwise.api.routers._deps import runs_store
from pathwise.api.runs_store import RunStore
from pathwise.config import get_settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PATHWISE_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _result(obj: float = 1.0) -> dict[str, Any]:
    return {"status": "optimal", "objective": obj, "outputs": {}}


# ── RunStore unit ─────────────────────────────────────────────────────────────


def test_save_list_get_roundtrip(tmp_path: Any) -> None:
    store = RunStore(tmp_path / "runs.db")
    rid = store.save("s1", _result(42.0), backend="linopy")
    metas = store.list("s1")
    assert len(metas) == 1
    assert metas[0]["runId"] == rid and metas[0]["status"] == "optimal"
    assert metas[0]["objective"] == 42.0 and metas[0]["exported"] is False
    assert store.get(rid) == _result(42.0)
    assert store.get("nope") is None


def test_list_is_session_scoped_and_newest_first(tmp_path: Any) -> None:
    store = RunStore(tmp_path / "runs.db")
    a = store.save("s1", _result(1))
    b = store.save("s1", _result(2))
    store.save("s2", _result(3))
    ids = [m["runId"] for m in store.list("s1")]
    assert ids == [b, a]  # newest first
    assert len(store.list("s2")) == 1
    assert len(store.list()) == 3  # all sessions


def test_clear_keeps_exported(tmp_path: Any) -> None:
    store = RunStore(tmp_path / "runs.db")
    keep = store.save("s1", _result(1))
    drop = store.save("s1", _result(2))
    assert store.mark_exported(keep) is True
    assert store.mark_exported("nope") is False
    removed = store.clear(keep_exported=True)
    assert removed == 1
    ids = [m["runId"] for m in store.list("s1")]
    assert ids == [keep] and store.get(drop) is None
    # exported flag round-trips
    assert store.list("s1")[0]["exported"] is True
    # clear_all drops even exported
    assert store.clear_all() == 1
    assert store.list() == []


def test_eviction_keeps_exported_drops_oldest(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pathwise.api.runs_store._MAX_RUNS", 3)
    store = RunStore(tmp_path / "runs.db")
    pinned = store.save("s", _result(0))
    store.mark_exported(pinned)
    ids = [store.save("s", _result(i)) for i in range(1, 5)]  # 4 more → over cap of 3
    remaining = {m["runId"] for m in store.list()}
    assert pinned in remaining  # exported survives eviction
    assert ids[0] not in remaining  # the oldest non-exported was evicted
    assert len(remaining) == 3


def test_delete_one(tmp_path: Any) -> None:
    store = RunStore(tmp_path / "runs.db")
    rid = store.save("s", _result())
    assert store.delete(rid) is True
    assert store.delete(rid) is False
    assert store.get(rid) is None


# ── Endpoints ─────────────────────────────────────────────────────────────────


def test_endpoints_list_get_export_and_clear() -> None:
    store = runs_store()
    keep = store.save("sess", _result(10.0), backend="linopy")
    drop = store.save("sess", _result(20.0), backend="linopy")

    listed = client.get("/api/session/sess/runs").json()["runs"]
    assert {r["runId"] for r in listed} == {keep, drop}

    got = client.get(f"/api/runs/{keep}").json()
    assert got["objective"] == 10.0
    assert client.get("/api/runs/nope").status_code == 404

    # mark one exported, then clear-cache keeps it and drops the other
    assert client.post(f"/api/runs/{keep}/export").json()["exported"] is True
    cleared = client.post("/api/cache/clear").json()
    assert cleared["clearedRuns"] == 1
    survivors = {r["runId"] for r in store.list()}
    assert survivors == {keep}


def test_export_result_marks_run_exported() -> None:
    store = runs_store()
    rid = store.save("sess", _result(5.0))
    # the result the client posts back carries its runId → export marks it
    resp = client.post("/api/export/result", json={**_result(5.0), "runId": rid})
    assert resp.status_code == 200
    assert store.list("sess")[0]["exported"] is True
