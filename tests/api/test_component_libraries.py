"""Component-library API: many writable libraries + drop fresh copies.

The writable catalogue the Component builder edits — seeded once from the
bundled starters, then full CRUD. The Value-Chain builder's ``/instantiate``
drops a fresh, non-shared copy of a component into a session node.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pathwise.api.main import app
from pathwise.config import get_settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PATHWISE_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_seeds_starters_on_first_access() -> None:
    libs = {lib["id"]: lib for lib in client.get("/api/component-libraries").json()}
    assert {"power", "steel"} <= set(libs), "starter libraries should seed a fresh install"
    assert libs["steel"]["machines"] >= 3  # bf, bof, eaf


def test_get_one_library() -> None:
    steel = client.get("/api/component-library/steel").json()
    names = {m["name"] for m in steel["machines"]}
    assert {"bf", "bof", "eaf"} <= names
    bf = next(m for m in steel["machines"] if m["name"] == "bf")
    assert bf["measures"], "bf carries a MACC measure (PCI)"


def test_put_create_get_delete() -> None:
    body = {
        "label": "My library",
        "technologies": [
            {"technology_id": "T", "io": [{"target": "x", "role": "output", "coefficient": 1}]}
        ],
        "machines": [{"name": "m1", "technology": "T", "capacity": 10}],
    }
    summary = client.put("/api/component-library/mylib", json=body).json()
    assert summary["id"] == "mylib" and summary["machines"] == 1
    assert any(lib["id"] == "mylib" for lib in client.get("/api/component-libraries").json())
    assert client.delete("/api/component-library/mylib").json()["deleted"] is True
    assert client.get("/api/component-library/mylib").status_code == 404


def test_invalid_library_id_rejected() -> None:
    assert client.get("/api/component-library/..%2Fevil").status_code in (404, 422)
    assert client.put("/api/component-library/bad id", json={"label": "x"}).status_code == 422


def test_instantiate_drops_fresh_copies_into_session() -> None:
    # a session holding a root chain with one company group
    model = {
        "nodes": [
            {"node_id": "chain", "parent_id": None, "kind": "group", "level": "value_chain"},
            {"node_id": "chain/steel", "parent_id": "chain", "kind": "group", "level": "company"},
        ]
    }
    sid = client.post("/api/session/model", json={"model": model}).json()["sessionId"]

    r1 = client.post(
        f"/api/session/{sid}/instantiate",
        json={"library": "steel", "component": "integrated_mill", "parent_id": "chain/steel"},
    ).json()
    r2 = client.post(
        f"/api/session/{sid}/instantiate",
        json={"library": "steel", "component": "integrated_mill", "parent_id": "chain/steel"},
    ).json()
    assert r1["root"] and r2["root"] and r1["root"] != r2["root"], "copies must be independent"

    nodes = client.get(f"/api/session/{sid}/model").json()["model"]["nodes"]
    ids = [n["node_id"] for n in nodes]
    assert len(ids) == len(set(ids)), "no shared node ids across fresh copies"
    mills = [n for n in nodes if str(n.get("parent_id")) == "chain/steel"]
    assert len(mills) == 2


def test_instantiate_unknown_component_is_422() -> None:
    model = {"nodes": [{"node_id": "chain", "parent_id": None, "kind": "group", "level": "vc"}]}
    sid = client.post("/api/session/model", json={"model": model}).json()["sessionId"]
    resp = client.post(
        f"/api/session/{sid}/instantiate",
        json={"library": "steel", "component": "nope", "parent_id": "chain"},
    )
    assert resp.status_code == 422
