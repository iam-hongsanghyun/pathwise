"""Session API: the backend owns the working model (ragnarok pattern)."""

from __future__ import annotations

import io
import time
from collections.abc import Iterator
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pathwise.api.main import app
from pathwise.config import get_settings
from tests.data.example import example_workbook

client = TestClient(app)


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PATHWISE_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _new_session() -> str:
    return str(client.post("/api/session").json()["sessionId"])


def test_patch_sheet_malformed_op_returns_422() -> None:
    sid = _new_session()
    # A "set" op missing its required "row" key must be a clean 422, not a 500
    # leaking a KeyError traceback.
    r = client.patch(
        f"/api/session/{sid}/sheet/flows",
        json={"ops": [{"op": "set", "column": "x", "value": 1}]},
    )
    assert r.status_code == 422


def test_cache_clear_open_when_no_admin_token() -> None:
    # Local-first default: no token configured ⇒ the destructive endpoint is open.
    assert client.post("/api/cache/clear").status_code == 200


def test_cache_clear_requires_admin_token_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATHWISE_ADMIN_TOKEN", "s3cret")
    get_settings.cache_clear()
    assert client.post("/api/cache/clear").status_code == 403  # missing
    assert client.post("/api/cache/clear", headers={"X-Admin-Token": "no"}).status_code == 403
    assert client.post("/api/cache/clear", headers={"X-Admin-Token": "s3cret"}).status_code == 200


def test_value_chain_list_and_run() -> None:
    chains = client.get("/api/value-chains").json()
    assert any(c["id"] == "elec_steel" for c in chains), "shipped value chain missing from index"
    res = client.post("/api/value-chain/elec_steel/run", json={}).json()
    assert res["status"] == "optimal"
    assert res["couplings"], "the run should report the electricity price flowing to steel"


def test_create_session_has_core_sheets() -> None:
    sid = _new_session()
    model = client.get(f"/api/session/{sid}/model").json()["model"]
    assert {"periods", "flows", "processes", "demand"} <= set(model)


def test_ingest_page_and_patch() -> None:
    res = client.post("/api/session/model", json={"model": example_workbook()}).json()
    sid = res["sessionId"]
    assert res["sheets"]["processes"] == 2

    page = client.get(f"/api/session/{sid}/sheet/processes", params={"limit": 1}).json()
    assert page["total"] == 2 and len(page["rows"]) == 1 and "process_id" in page["columns"]

    ops = [
        {"op": "set", "row": 0, "column": "capacity", "value": 1234},
        {"op": "addRow", "row": {"process_id": "F3", "company": "Acme"}},
    ]
    out = client.patch(f"/api/session/{sid}/sheet/processes", json={"ops": ops}).json()
    assert out["total"] == 3
    model = client.get(f"/api/session/{sid}/model").json()["model"]
    assert model["processes"][0]["capacity"] == 1234
    assert model["processes"][2]["process_id"] == "F3"

    out = client.patch(
        f"/api/session/{sid}/sheet/processes", json={"ops": [{"op": "deleteRows", "rows": [2]}]}
    ).json()
    assert out["total"] == 2


def test_upload_and_export_roundtrip() -> None:
    sid = _new_session()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for sheet, rows in example_workbook().items():
            pd.DataFrame(rows).to_excel(xw, sheet_name=sheet[:31], index=False)

    res = client.post(
        f"/api/session/{sid}/workbook",
        files={"file": ("model.xlsx", buf.getvalue(), "application/octet-stream")},
    ).json()
    assert res["sheets"]["processes"] == 2

    export = client.get(f"/api/session/{sid}/export")
    assert export.status_code == 200
    parsed = pd.ExcelFile(io.BytesIO(export.content))
    assert "processes" in parsed.sheet_names


def test_examples_are_sqlite_node_hierarchies() -> None:
    # every shipped example is a SQLite workbook in the new node-hierarchy form
    examples = client.get("/api/examples").json()
    assert {"value_chain_ccgt", "steel", "shipping", "petrochemical"} <= {e["id"] for e in examples}
    assert all(str(e["file"]).endswith(".sqlite") for e in examples)
    for e in examples:
        sid = _new_session()
        res = client.post(f"/api/session/{sid}/example/{e['id']}").json()
        assert res["sheets"].get("nodes", 0) >= 1, f"{e['id']} should be a node hierarchy"
        assert res["sheets"].get("assets", 0) >= 1


def test_load_sqlite_value_chain_example() -> None:
    sid = _new_session()
    res = client.post(f"/api/session/{sid}/example/value_chain_ccgt").json()
    assert res["sheets"]["nodes"] >= 1
    model = client.get(f"/api/session/{sid}/model").json()["model"]
    assert any(str(n["node_id"]).endswith("/ccgt") for n in model["nodes"]), "the CCGT group"


def test_run_by_session_id() -> None:
    res = client.post("/api/session/model", json={"model": example_workbook()}).json()
    sid = res["sessionId"]
    job = client.post(
        "/api/run",
        json={
            "sessionId": sid,
            "scenario": {"domain": "process", "economics": {"base_year": 2025}},
            "options": {"domain": "process"},
        },
    ).json()
    deadline = time.time() + 60
    while time.time() < deadline:
        state = client.get(f"/api/run/{job['jobId']}").json()
        if state["status"] in {"done", "error"}:
            break
        time.sleep(0.1)
    assert state["status"] == "done"
    assert state["result"]["status"] == "optimal"


def test_unknown_session_404() -> None:
    assert client.get("/api/session/nope/model").status_code == 404
    assert client.get("/api/session/nope/sheet/processes").status_code == 404


def test_clear_session_resets_to_core_sheets() -> None:
    res = client.post("/api/session/model", json={"model": example_workbook()}).json()
    sid = res["sessionId"]
    out = client.post(f"/api/session/{sid}/clear").json()
    assert all(n == 0 for n in out["sheets"].values())
    model = client.get(f"/api/session/{sid}/model").json()["model"]
    assert model["processes"] == [] and "periods" in model
    assert client.post("/api/session/nope/clear").status_code == 404
