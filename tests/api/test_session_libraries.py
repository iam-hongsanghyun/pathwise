"""Per-session component libraries + the scenario import split.

Importing a scenario must (1) keep the value-chain STRUCTURE in the session model
and (2) populate the session's OWN component library with the component DETAILS,
distinct from the shared base libraries.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from pathwise.api.main import app
from pathwise.api.workbook_io import parse_sqlite, write_sqlite
from pathwise.data.components import (
    ComponentLibrary,
    extract_library_from_workbook,
    library_from_workbook,
    library_to_workbook,
    load_component_library,
)

client = TestClient(app)


def test_technology_available_years_round_trip() -> None:
    from pathwise.data.library import _tech_row

    lib = ComponentLibrary.model_validate(
        {
            "label": "t",
            "commodities": [{"commodity_id": "x", "kind": "material", "unit": "t"}],
            "technologies": [
                {
                    "technology_id": "T",
                    "lifespan": 20,
                    "introduction_year": 2030,
                    "phase_out_year": 2050,
                    "io": [{"target": "x", "role": "output", "coefficient": 1.0}],
                    "maccs": [],
                }
            ],
            "measures": [],
            "maccs": [],
            "machines": [],
            "groups": [],
        }
    )
    # carried into the workbook technologies sheet (so the optimiser sees them)
    row = _tech_row(lib.technologies[0])
    assert row["introduction_year"] == 2030 and row["phase_out_year"] == 2050
    # and survive the SQLite library round-trip
    back = library_from_workbook(parse_sqlite(write_sqlite(library_to_workbook(lib))))
    assert back.technologies[0].introduction_year == 2030
    assert back.technologies[0].phase_out_year == 2050


def test_library_sqlite_round_trip_is_lossless() -> None:
    from importlib.resources import files

    for name in ("green_steel", "power", "steel"):
        src = files("pathwise.assets.component_libraries") / f"{name}.json"
        lib = load_component_library(src)
        back = library_from_workbook(parse_sqlite(write_sqlite(library_to_workbook(lib))))
        assert back.model_dump() == lib.model_dump(), f"{name} did not round-trip through SQLite"


def _new_session() -> str:
    return client.post("/api/session").json()["sessionId"]


def test_extract_library_recovers_streams_techs_measures() -> None:
    wb = {
        "commodities": [
            {"commodity_id": "elec", "kind": "energy", "unit": "MWh", "sector": "power"},
            {"commodity_id": "steel", "kind": "product", "unit": "t", "sector": "steel"},
        ],
        "technologies": [{"technology_id": "EAF", "lifespan": 25, "capex": 500, "opex": 18}],
        "io": [
            {"technology_id": "EAF", "target": "elec", "role": "input", "coefficient": 0.6},
            {
                "technology_id": "EAF",
                "target": "steel",
                "role": "output",
                "coefficient": 1.0,
                "is_product": True,
            },
        ],
        # per-facility measure (instantiated form) + its blocks
        "measures": [
            {
                "measure_id": "mill/eaf · eaf_eff",
                "type": "energy_efficiency",
                "target": "elec",
                "lifetime": 15,
            }
        ],
        "measure_blocks": [
            {"measure_id": "mill/eaf · eaf_eff", "block": 0, "reduction": 0.05, "capex": 1000.0}
        ],
        # structure sheets must be ignored by extraction
        "nodes": [{"node_id": "mill", "kind": "group"}],
        "connections": [{"from_node": "a", "to_node": "b", "commodity_id": "elec"}],
    }
    lib = extract_library_from_workbook(wb, label="Demo")
    assert lib.label == "Demo"
    assert {c.commodity_id for c in lib.commodities} == {"elec", "steel"}
    assert next(c for c in lib.commodities if c.commodity_id == "elec").sector == "power"
    assert [t.technology_id for t in lib.technologies] == ["EAF"]
    assert len(lib.technologies[0].io) == 2
    # the per-facility measure is de-instantiated to a reusable template id
    assert [m.measure_id for m in lib.measures] == ["eaf_eff"]
    assert lib.measures[0].blocks[0].reduction == 0.05


def test_import_splits_into_session_library() -> None:
    sid = _new_session()
    res = client.post(f"/api/session/{sid}/example/green_steel_chain").json()
    # structure stays in the session model
    assert res["sheets"]["nodes"] >= 1 and res["sheets"]["connections"] >= 1
    # a session library was created from the import
    lib_id = res["library_id"]
    assert lib_id

    libs = client.get(f"/api/session/{sid}/component-libraries").json()
    assert any(x["id"] == lib_id and x["scope"] == "session" for x in libs)

    body = client.get(f"/api/session/{sid}/component-library/{lib_id}").json()
    # green_steel ships a faithful library → streams carry their owning sector
    assert len(body["technologies"]) >= 5
    sectors = {c["commodity_id"]: c.get("sector") for c in body["commodities"]}
    assert sectors.get("electricity") == "power" and sectors.get("steel") == "steel"


def test_session_library_crud_isolated_per_session() -> None:
    a, b = _new_session(), _new_session()
    lib = {
        "label": "Mine",
        "commodities": [{"commodity_id": "ore", "kind": "material", "unit": "t"}],
        "technologies": [],
        "measures": [],
        "maccs": [],
        "machines": [],
        "groups": [],
    }
    assert client.put(f"/api/session/{a}/component-library/mine", json=lib).status_code == 200
    # visible in session a, NOT in session b (isolation)
    assert [x["id"] for x in client.get(f"/api/session/{a}/component-libraries").json()] == ["mine"]
    assert client.get(f"/api/session/{b}/component-libraries").json() == []
    # delete
    assert client.delete(f"/api/session/{a}/component-library/mine").json()["deleted"] is True
    assert client.get(f"/api/session/{a}/component-libraries").json() == []
