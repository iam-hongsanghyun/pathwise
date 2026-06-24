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


def test_starters_are_read_only_and_tagged() -> None:
    # Shipped starters carry origin="starter" and reject writes (hard split).
    libs = {lib["id"]: lib for lib in client.get("/api/component-libraries").json()}
    assert libs["steel"]["origin"] == "starter"
    assert client.put("/api/component-library/steel", json={"label": "hijacked"}).status_code == 403
    assert client.delete("/api/component-library/steel").status_code == 403
    # The starter is untouched.
    assert client.get("/api/component-library/steel").json()["label"] != "hijacked"


def test_user_library_is_writable_and_tagged_user() -> None:
    client.put("/api/component-library/mine", json={"label": "Mine"})
    libs = {lib["id"]: lib for lib in client.get("/api/component-libraries").json()}
    assert libs["mine"]["origin"] == "user"
    assert client.delete("/api/component-library/mine").json()["deleted"] is True


def _lib_workbook() -> dict[str, Any]:
    return {
        "commodities": [{"commodity_id": "x", "kind": "product", "unit": "t"}],
        "technologies": [{"technology_id": "T"}],
        "io": [
            {
                "technology_id": "T",
                "target": "x",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            }
        ],
    }


def test_import_library_file_into_mine_xlsx_and_sqlite() -> None:
    from pathwise.api.workbook_io import write_sqlite, write_xlsx

    for ext, data in (
        ("xlsx", write_xlsx(_lib_workbook())),
        ("sqlite", write_sqlite(_lib_workbook())),
    ):
        lib_id = f"imp_{ext}"
        r = client.post(
            f"/api/component-library/{lib_id}/import",
            files={"file": (f"kit.{ext}", data, "application/octet-stream")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["origin"] == "user"
        assert r.json()["technologies"] == 1
        libs = {lib["id"]: lib for lib in client.get("/api/component-libraries").json()}
        assert libs[lib_id]["commodities"] == 1
        client.delete(f"/api/component-library/{lib_id}")


def test_import_library_file_into_project_session() -> None:
    from pathwise.api.workbook_io import write_xlsx

    sid = client.post("/api/session").json()["sessionId"]
    r = client.post(
        f"/api/session/{sid}/component-library/projkit/import",
        files={"file": ("kit.xlsx", write_xlsx(_lib_workbook()), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["scope"] == "session"
    libs = {lib["id"]: lib for lib in client.get(f"/api/session/{sid}/component-libraries").json()}
    assert libs["projkit"]["technologies"] == 1


def test_library_template_has_fillable_sheets_with_headers() -> None:
    import io

    import pandas as pd

    r = client.get("/api/component-library/template.xlsx")
    assert r.status_code == 200
    frames = pd.read_excel(io.BytesIO(r.content), sheet_name=None)
    for sheet in ["commodities", "technologies", "io", "measures", "maccs"]:
        assert sheet in frames, f"template missing {sheet} tab"
    # Machines are Facility-layer placed instances, not reusable components.
    assert "machines" not in frames
    # Header row matches the schema; no rows to fill from.
    assert "coefficient" in frames["io"].columns
    assert len(frames["technologies"].index) == 0
    # A filled-in template imports back (round-trip through extract_library).
    data = io.BytesIO()
    with pd.ExcelWriter(data, engine="openpyxl") as xw:
        pd.DataFrame([{"commodity_id": "x", "kind": "product", "unit": "t"}]).to_excel(
            xw, sheet_name="commodities", index=False
        )
    resp = client.post(
        "/api/component-library/from_template/import",
        files={"file": ("filled.xlsx", data.getvalue(), "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["commodities"] == 1
    client.delete("/api/component-library/from_template")


def test_import_cannot_overwrite_starter() -> None:
    from pathwise.api.workbook_io import write_xlsx

    r = client.post(
        "/api/component-library/steel/import",
        files={"file": ("kit.xlsx", write_xlsx(_lib_workbook()), "application/octet-stream")},
    )
    assert r.status_code == 403


def test_duplicate_starter_into_user_library() -> None:
    # The duplicate flow the UI uses: GET a starter, PUT it under a fresh id.
    src = client.get("/api/component-library/steel").json()
    src["label"] = "Steel (copy)"
    assert client.put("/api/component-library/my_steel", json=src).status_code == 200
    libs = {lib["id"]: lib for lib in client.get("/api/component-libraries").json()}
    assert libs["my_steel"]["origin"] == "user"  # the copy is editable
    assert libs["my_steel"]["technologies"] == libs["steel"]["technologies"]
    client.delete("/api/component-library/my_steel")


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
    machines = [m for m in wb["machines"] if str(m.get("source_technology")) == "BF_BOF"]
    assert {float(m["capacity"]) for m in machines} == {500.0, 700.0}
    # each placement is its OWN technology instance (distinct baseline ids)
    assert len({str(m["baseline_technology"]) for m in machines}) == 2


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
