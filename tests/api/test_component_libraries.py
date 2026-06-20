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
    assert libs["steel"]["technologies"] >= 4  # BF_BOF, BF_BOF_FX, H2_DRI_ESF, EAF


def test_get_one_library() -> None:
    steel = client.get("/api/component-library/steel").json()
    techs = {t["technology_id"] for t in steel["technologies"]}
    # The systempathway steel port: 4 technologies (BF-BOF baseline + the
    # alternatives the optimiser may switch into). Fuels/feedstocks are commodities.
    assert {"BF_BOF", "BF_BOF_FX", "H2_DRI_ESF", "EAF"} <= techs
    bf = next(t for t in steel["technologies"] if t["technology_id"] == "BF_BOF")
    roles = {(r["role"], r["target"]) for r in bf["io"]}
    assert ("input", "Coal_BB") in roles and ("output", "steel") in roles


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


def test_place_unknown_technology_is_422() -> None:
    model = {"nodes": [{"node_id": "chain", "parent_id": None, "kind": "group", "level": "vc"}]}
    sid = client.post("/api/session/model", json={"model": model}).json()["sessionId"]
    resp = client.post(
        f"/api/session/{sid}/place-technology",
        json={"library": "steel", "technology": "nope", "parent_id": "chain"},
    )
    assert resp.status_code == 422


# ── Copy a component (+ its closure) into a project (the drag-to-copy engine) ──

_SESSION_LIB = {
    "label": "proj",
    "commodities": [
        {"commodity_id": "steel", "kind": "product", "unit": "t"},
        {"commodity_id": "elec", "kind": "energy", "unit": "MWh"},
    ],
    "measures": [
        {
            "measure_id": "eff1",
            "label": "Eff one",
            "type": "energy_efficiency",
            "target": "elec",
            "blocks": [{"reduction": 0.1, "capex_per_capacity": 5}],
        }
    ],
    "maccs": [{"macc_id": "M", "label": "Macc one", "measures": ["eff1"]}],
    "technologies": [
        {
            "technology_id": "EAFx",
            "io": [
                {"target": "steel", "role": "output", "coefficient": 1, "is_product": True},
                {"target": "elec", "role": "input", "coefficient": 2},
            ],
            "maccs": ["M"],
        }
    ],
}


def test_copy_technology_from_base_brings_closure() -> None:
    # Drag a base-library technology onto a project → copy it in with its streams.
    sid = "copy1"
    summary = client.post(
        f"/api/session/{sid}/component-library/proj/copy",
        json={"src_scope": "base", "src_id": "steel", "kind": "technology", "component_id": "EAF"},
    ).json()
    assert summary["technologies"] == 1  # the technology copied in
    body = client.get(f"/api/session/{sid}/component-library/proj").json()
    assert "EAF" in {t["technology_id"] for t in body["technologies"]}
    assert body["commodities"], "its input/output streams came along (closure)"


def test_copy_from_session_source_brings_full_closure() -> None:
    sid = "copy2"
    client.put(f"/api/session/{sid}/component-library/src", json=_SESSION_LIB)
    client.post(
        f"/api/session/{sid}/component-library/dst/copy",
        json={
            "src_scope": "session",
            "src_id": "src",
            "kind": "technology",
            "component_id": "EAFx",
        },
    )
    body = client.get(f"/api/session/{sid}/component-library/dst").json()
    assert {t["technology_id"] for t in body["technologies"]} == {"EAFx"}
    assert {c["commodity_id"] for c in body["commodities"]} == {"steel", "elec"}
    assert {m["measure_id"] for m in body["measures"]} == {"eff1"}  # via the MACC
    assert {g["macc_id"] for g in body["maccs"]} == {"M"}


def test_copy_stream_only() -> None:
    # Dragging a single stream copies just that commodity, no technologies.
    sid = "copy3"
    client.put(f"/api/session/{sid}/component-library/src", json=_SESSION_LIB)
    client.post(
        f"/api/session/{sid}/component-library/dst/copy",
        json={"src_scope": "session", "src_id": "src", "kind": "stream", "component_id": "steel"},
    )
    body = client.get(f"/api/session/{sid}/component-library/dst").json()
    assert {c["commodity_id"] for c in body["commodities"]} == {"steel"}
    assert body["technologies"] == []


def test_copy_unknown_source_is_404() -> None:
    resp = client.post(
        "/api/session/copy4/component-library/dst/copy",
        json={"src_scope": "base", "src_id": "nope", "kind": "technology", "component_id": "x"},
    )
    assert resp.status_code == 404
