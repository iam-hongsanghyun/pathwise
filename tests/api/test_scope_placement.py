"""Placing a SESSION (project-specific) component, not just a base one — the
Facility / Value-Chain pickers must be able to drop a project's own components."""

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


def _project_library() -> dict[str, Any]:
    return {
        "label": "Project",
        "commodities": [
            {"commodity_id": "ore", "kind": "material", "unit": "t"},
            {"commodity_id": "steel", "kind": "product", "unit": "t"},
        ],
        "technologies": [
            {
                "technology_id": "MY_BF",
                "io": [
                    {"target": "ore", "role": "input", "coefficient": 1.0},
                    {"target": "steel", "role": "output", "coefficient": 1.0, "is_product": True},
                ],
            }
        ],
        "measures": [],
        "maccs": [],
        "machines": [],
        "groups": [],
    }


def test_place_technology_resolves_session_scope() -> None:
    sid = client.post("/api/session").json()["sessionId"]
    assert (
        client.put(
            f"/api/session/{sid}/component-library/proj", json=_project_library()
        ).status_code
        == 200
    )
    client.post(
        "/api/session/model",
        json={
            "sessionId": sid,
            "model": {
                "nodes": [{"node_id": "co", "kind": "group", "level": "company", "label": "Acme"}]
            },
        },
    )

    # scope='base' can't see a session-only library
    miss = client.post(
        f"/api/session/{sid}/place-technology",
        json={"library": "proj", "technology": "MY_BF", "parent_id": "co", "scope": "base"},
    )
    assert miss.status_code == 404

    # scope='session' resolves the project's own library and places the machine
    res = client.post(
        f"/api/session/{sid}/place-technology",
        json={"library": "proj", "technology": "MY_BF", "parent_id": "co", "scope": "session"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["root"]
    model = client.get(f"/api/session/{sid}/model").json()["model"]
    assert any(m.get("baseline_technology") == "MY_BF" for m in model.get("machines", []))


def test_place_technology_defaults_to_base_scope() -> None:
    sid = client.post("/api/session").json()["sessionId"]
    client.post(
        "/api/session/model",
        json={
            "sessionId": sid,
            "model": {
                "nodes": [{"node_id": "co", "kind": "group", "level": "company", "label": "Acme"}]
            },
        },
    )
    # no scope field → base catalogue (the seeded 'steel' library)
    res = client.post(
        f"/api/session/{sid}/place-technology",
        json={"library": "steel", "technology": "BF_BOF", "parent_id": "co"},
    )
    assert res.status_code == 200, res.text
