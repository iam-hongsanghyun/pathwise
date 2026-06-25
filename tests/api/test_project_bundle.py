"""Project bundle API: a self-contained export (name + model + project component
libraries + the referenced base components, sliced) that re-imports into any
session."""

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


def _new_session() -> str:
    return client.post("/api/session").json()["sessionId"]


def _seed(sid: str) -> None:
    """A minimal Facility/Value-Chain model: one asset running a BASE technology
    (BF_BOF from the seeded 'steel' library) + a named project."""
    model = {
        "nodes": [{"node_id": "n1", "kind": "group", "level": "company", "label": "Acme"}],
        "assets": [{"asset_id": "mac1", "baseline_technology": "BF_BOF", "capacity": 10}],
        "connections": [],
        "project": [{"name": "Acme Steel"}],
    }
    assert (
        client.post("/api/session/model", json={"sessionId": sid, "model": model}).status_code
        == 200
    )
    proj = {
        "label": "Project comps",
        "commodities": [{"commodity_id": "x", "kind": "material", "unit": "t"}],
        "technologies": [],
        "measures": [],
        "maccs": [],
        "assets": [],
        "groups": [],
    }
    assert client.put(f"/api/session/{sid}/component-library/proj", json=proj).status_code == 200


def test_export_is_self_contained() -> None:
    sid = _new_session()
    _seed(sid)
    res = client.get(f"/api/session/{sid}/project/export")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    bundle = res.json()
    assert bundle["format"] == "pathwise.project"
    assert bundle["name"] == "Acme Steel"
    # the project's own component library travels verbatim
    assert "proj" in bundle["session_libraries"]
    # the referenced base technology pulls in its base library, SLICED to just it
    assert "steel" in bundle["base_libraries"]
    assert {t["technology_id"] for t in bundle["base_libraries"]["steel"]["technologies"]} == {
        "BF_BOF"
    }


def test_import_restores_model_and_project_libraries() -> None:
    src = _new_session()
    _seed(src)
    bundle = client.get(f"/api/session/{src}/project/export").json()

    dst = _new_session()
    res = client.post(f"/api/session/{dst}/project/import", json=bundle)
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Acme Steel"

    model = client.get(f"/api/session/{dst}/model").json()["model"]
    assert model["assets"][0]["baseline_technology"] == "BF_BOF"
    assert model["project"][0]["name"] == "Acme Steel"

    libs = {x["id"]: x for x in client.get(f"/api/session/{dst}/component-libraries").json()}
    assert "proj" in libs and libs["proj"]["scope"] == "session"


def test_import_does_not_clobber_an_existing_base_library() -> None:
    src = _new_session()
    _seed(src)
    bundle = client.get(f"/api/session/{src}/project/export").json()

    dst = _new_session()
    res = client.post(f"/api/session/{dst}/project/import", json=bundle).json()
    # the host already has the full 'steel' base library, so it is NOT overwritten
    assert res["restored_base_libraries"] == []
    steel = client.get("/api/component-library/steel").json()
    assert {t["technology_id"] for t in steel["technologies"]} >= {"BF_BOF", "EAF", "H2_DRI_ESF"}


def test_import_rejects_non_bundle_json() -> None:
    dst = _new_session()
    bad = {"format": "something-else", "model": {}, "session_libraries": {}, "base_libraries": {}}
    assert client.post(f"/api/session/{dst}/project/import", json=bad).status_code == 422
