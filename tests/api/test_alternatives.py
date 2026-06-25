"""Value-chain alternatives — offering a asset an alternative technology.

An alternative is a value-chain choice (not baked into the Component library):
adding one merges the technology's recipe into the session and records a
transition the optimiser may switch the asset to.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from pathwise.api.main import app
from pathwise.data.components import ComponentLibrary, add_alternative

client = TestClient(app)


def _lib() -> ComponentLibrary:
    return ComponentLibrary.model_validate(
        {
            "label": "t",
            "flows": [
                {"flow_id": "scrap", "kind": "material", "unit": "t"},
                {"flow_id": "steel", "kind": "product", "unit": "t"},
            ],
            "technologies": [
                {
                    "technology_id": "EAF",
                    "lifespan": 25,
                    "capex": 500,
                    "opex": 18,
                    "io": [
                        {"target": "scrap", "role": "input", "coefficient": 1.05},
                        {
                            "target": "steel",
                            "role": "output",
                            "coefficient": 1.0,
                            "is_product": True,
                        },
                    ],
                    "maccs": [],
                }
            ],
            "measures": [],
            "maccs": [],
            "assets": [],
            "groups": [],
        }
    )


def test_add_alternative_merges_recipe_and_transition() -> None:
    model = {
        "technologies": [{"technology_id": "BOF", "lifespan": 25}],
        "assets": [{"asset_id": "mill/bof", "baseline_technology": "BOF"}],
    }
    out = add_alternative(model, _lib(), "EAF", from_technology="BOF")
    # The alternative is stamped as a per-asset INSTANCE (EAF@<node>) tracing
    # back to the component via source_technology.
    iid = "EAF@BOF"
    assert any(t["technology_id"] == iid for t in out["technologies"]), "recipe merged"
    assert any(r["technology_id"] == iid and r["role"] == "input" for r in out["io"]), "io merged"
    assert {
        "from_technology": "BOF",
        "to_technology": iid,
        "action": "replace",
        "capex_per_capacity": 0.0,
        "source_technology": "EAF",
    } in out["transitions"]
    # idempotent on the transition
    again = add_alternative(out, _lib(), "EAF", from_technology="BOF")
    assert sum(1 for r in again["transitions"] if r["to_technology"] == iid) == 1


def test_alternative_endpoint_on_imported_scenario() -> None:
    sid = client.post("/api/session").json()["sessionId"]
    client.post(f"/api/session/{sid}/example/green_steel_chain")
    # the pool of technologies to choose from
    techs = client.get(f"/api/session/{sid}/technologies").json()
    assert any(t["technology"] == "EAF" for t in techs)

    # offer EAF as an alternative to the BOF asset (from the scenario library)
    mid = "vc/korea/kr_steel/mill/bof"
    res = client.post(
        f"/api/session/{sid}/alternative",
        json={
            "library": "green_steel_chain",
            "technology": "EAF",
            "asset_id": mid,
            "scope": "session",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["from_technology"] == "BOF" and body["to_technology"] == "EAF"
    # the transition is now in the session model
    model = client.get(f"/api/session/{sid}/model").json()["model"]
    assert any(
        t.get("from_technology") == "BOF" and t.get("to_technology") == "EAF"
        for t in model.get("transitions", [])
    )
