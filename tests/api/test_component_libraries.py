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
    assert libs["steel"]["technologies"] >= 3  # BF_BOF, BF_BOF_CCS, H2_DRI_ESF, Scrap_EAF
    assert libs["steel"]["maccs"] >= 1  # the blast-furnace MACC bundle


def test_get_one_library() -> None:
    steel = client.get("/api/component-library/steel").json()
    techs = {t["technology_id"] for t in steel["technologies"]}
    assert {"BF_BOF", "H2_DRI_ESF", "Scrap_EAF"} <= techs
    bf = next(t for t in steel["technologies"] if t["technology_id"] == "BF_BOF")
    assert bf["maccs"], "BF_BOF links a MACC bundle"
    assert {m["measure_id"] for m in steel["measures"]} >= {"bf_ccs"}
    macc = next(g for g in steel["maccs"] if g["macc_id"] == "bf_abate")
    assert "bf_ccs" in macc["measures"]


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


def test_place_technology_creates_independent_machines() -> None:
    # a session holding a root chain with one company group
    model = {
        "nodes": [
            {"node_id": "chain", "parent_id": None, "kind": "group", "level": "value_chain"},
            {"node_id": "chain/steel", "parent_id": "chain", "kind": "group", "level": "company"},
        ]
    }
    sid = client.post("/api/session/model", json={"model": model}).json()["sessionId"]

    r1 = client.post(
        f"/api/session/{sid}/place-technology",
        json={
            "library": "steel",
            "technology": "BF_BOF",
            "parent_id": "chain/steel",
            "capacity": 500,
        },
    ).json()
    r2 = client.post(
        f"/api/session/{sid}/place-technology",
        json={
            "library": "steel",
            "technology": "BF_BOF",
            "parent_id": "chain/steel",
            "capacity": 700,
        },
    ).json()
    assert r1["root"] and r2["root"] and r1["root"] != r2["root"], "two placements are independent"

    wb = client.get(f"/api/session/{sid}/model").json()["model"]
    machines = [m for m in wb["machines"] if str(m.get("baseline_technology")) == "BF_BOF"]
    assert {float(m["capacity"]) for m in machines} == {500.0, 700.0}
    # the BF_BOF MACC measures came along, scoped per machine
    assert any("bf_ccs" in str(m["measure_id"]) for m in wb.get("measures", []))


def test_place_unknown_technology_is_422() -> None:
    model = {"nodes": [{"node_id": "chain", "parent_id": None, "kind": "group", "level": "vc"}]}
    sid = client.post("/api/session/model", json={"model": model}).json()["sessionId"]
    resp = client.post(
        f"/api/session/{sid}/place-technology",
        json={"library": "steel", "technology": "nope", "parent_id": "chain"},
    )
    assert resp.status_code == 422
