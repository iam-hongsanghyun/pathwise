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
    from pathwise.data.templates import _tech_row

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
        src = files("pathwise.assets.component_seeds") / f"{name}.sqlite"
        lib = load_component_library(src)
        back = library_from_workbook(parse_sqlite(write_sqlite(library_to_workbook(lib))))
        assert back.model_dump() == lib.model_dump(), f"{name} did not round-trip through SQLite"


def test_no_trajectory_library_keeps_legacy_sheets() -> None:
    """A library with no per-year data must not gain trajectory sheets, and its
    scalar columns must be untouched (backwards-compatible storage)."""
    lib = ComponentLibrary.model_validate(
        {
            "label": "scalar",
            "commodities": [{"commodity_id": "x", "kind": "material", "unit": "t", "price": 3.0}],
            "technologies": [
                {
                    "technology_id": "T",
                    "capex": 100.0,
                    "opex": 2.0,
                    "io": [{"target": "x", "role": "output", "coefficient": 1.0}],
                }
            ],
            "measures": [],
            "maccs": [],
            "machines": [],
            "groups": [],
        }
    )
    wb = library_to_workbook(lib)
    assert "commodity_prices" not in wb
    assert "technologies_prices" not in wb
    assert "lever_blocks_t" not in wb
    assert "notes" not in wb["technologies"][0]  # blank notes don't add a column
    assert wb["technologies"][0]["capex"] == 100.0
    assert wb["commodities"][0]["price"] == 3.0


def test_trajectories_and_notes_round_trip() -> None:
    """Per-year capex/opex/price trajectories, per-block trajectories, entity
    notes and sector notes all survive the base/session SQLite round-trip."""
    lib = ComponentLibrary.model_validate(
        {
            "label": "traj",
            "commodities": [
                {
                    "commodity_id": "power",
                    "kind": "energy",
                    "unit": "MWh",
                    "price": 50.0,
                    "price_by_year": {2025: 50.0, 2030: 40.0, 2050: 20.0},
                    "sale_price_by_year": {2030: 0.0},  # an explicit zero must survive
                    "sector": "power",
                    "notes": "grid average; ref [1]",
                },
                {"commodity_id": "steel", "kind": "product", "unit": "t"},
            ],
            "technologies": [
                {
                    "technology_id": "EAF",
                    "lifespan": 25,
                    "capex": 200.0,
                    "opex": 5.0,
                    "capex_by_year": {2025: 200.0, 2040: 150.0},
                    "opex_by_year": {2025: 5.0},
                    "io": [
                        {"target": "power", "role": "input", "coefficient": 0.5},
                        {
                            "target": "steel",
                            "role": "output",
                            "coefficient": 1.0,
                            "is_product": True,
                        },
                    ],
                    "maccs": ["m1"],
                    "notes": "BAT plant; ref [2]",
                }
            ],
            "measures": [
                {
                    "lever_id": "ee1",
                    "type": "energy_efficiency",
                    "target": "power",
                    "lifetime": 10,
                    "blocks": [
                        {
                            "reduction": 0.1,
                            "capex_per_capacity": 1.0,
                            "capex_per_capacity_by_year": {2025: 1.0, 2040: 0.5},
                        },
                        {
                            "reduction": 0.2,
                            "capex_per_capacity": 2.0,
                            "opex_per_capacity_by_year": {2030: 0.3},
                        },
                    ],
                    "notes": "two-step efficiency curve",
                }
            ],
            "maccs": [{"macc_id": "m1", "label": "MACC", "measures": ["ee1"], "notes": "bundle"}],
            "machines": [],
            "groups": [],
            # "steel": "" — an explicit empty sector note is distinct from absent
            # and must survive (present-or-absent dict, no "" default).
            "notes_by_sector": {"power": "power sector overview", "steel": ""},
        }
    )
    back = library_from_workbook(parse_sqlite(write_sqlite(library_to_workbook(lib))))
    assert back.model_dump() == lib.model_dump()


def _new_session() -> str:
    return client.post("/api/session").json()["sessionId"]


def test_extract_library_recovers_streams_techs_levers() -> None:
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
        # per-facility lever (instantiated form) + its blocks
        "levers": [
            {
                "lever_id": "mill/eaf · eaf_eff",
                "type": "energy_efficiency",
                "target": "elec",
                "lifetime": 15,
            }
        ],
        "lever_blocks": [
            {"lever_id": "mill/eaf · eaf_eff", "block": 0, "reduction": 0.05, "capex": 1000.0}
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
    # the per-facility lever is de-instantiated to a reusable template id
    assert [m.lever_id for m in lib.measures] == ["eaf_eff"]
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
