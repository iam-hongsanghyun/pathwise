"""Storage + Station component kinds: round-trip, copy closure, and placement.

A library can hold storage/station components alongside technologies; each round-trips
losslessly through the SQLite-style workbook, copies into a project with its flow
closure, and PLACES as a scope-bound ``storage`` / ``stations`` row the engine reads.
"""

from __future__ import annotations

from pathwise.data import ScenarioConfig, assemble_problem
from pathwise.data.components import (
    ComponentLibrary,
    copy_component_into,
    library_from_workbook,
    library_to_workbook,
    place_station,
    place_storage,
)


def _lib() -> ComponentLibrary:
    return ComponentLibrary.model_validate(
        {
            "label": "base",
            "flows": [
                {"flow_id": "h2", "kind": "energy", "unit": "t"},
                {"flow_id": "elec", "kind": "energy", "unit": "MWh"},
                {"flow_id": "bunker", "kind": "energy", "unit": "t", "price": 1.0},
                {"flow_id": "spare", "kind": "material", "unit": "t"},
            ],
            "storages": [
                {
                    "storage_id": "h2_tank",
                    "flow_id": "h2",
                    "max_capacity": 500.0,
                    "capex_per_capacity": 12.0,
                    "fixed_opex_per_capacity": 0.5,
                    "charge_efficiency": 0.95,
                    "discharge_efficiency": 0.93,
                    "standing_loss": 0.01,
                    "energy_flow": "elec",
                    "energy_per_throughput": 0.2,
                }
            ],
            "stations": [
                {
                    "station_id": "bunkering",
                    "refuel_flow": "bunker",
                    "refuel_capacity": 9000.0,
                    "refuel_fee": 2.0,
                    "capex": 100.0,
                    "fixed_opex": 5.0,
                }
            ],
        }
    )


def _empty() -> ComponentLibrary:
    return ComponentLibrary.model_validate({"label": "project"})


def test_storage_station_round_trip() -> None:
    lib = _lib()
    back = library_from_workbook(library_to_workbook(lib))
    s = back.storage("h2_tank")
    assert s is not None
    assert s.flow_id == "h2"
    assert abs(s.charge_efficiency - 0.95) < 1e-9
    assert s.energy_flow == "elec" and abs(s.energy_per_throughput - 0.2) < 1e-9
    st = back.station("bunkering")
    assert st is not None
    assert st.refuel_flow == "bunker"
    assert abs(st.refuel_fee - 2.0) < 1e-9 and abs(st.refuel_capacity - 9000.0) < 1e-9


def test_copy_storage_brings_its_flows() -> None:
    out = copy_component_into(_empty(), _lib(), "storage", "h2_tank")
    assert {s.storage_id for s in out.storages} == {"h2_tank"}
    assert {c.flow_id for c in out.flows} == {"h2", "elec"}  # stored + running-energy, not "spare"


def test_copy_station_brings_its_fuel() -> None:
    out = copy_component_into(_empty(), _lib(), "station", "bunkering")
    assert {s.station_id for s in out.stations} == {"bunkering"}
    assert {c.flow_id for c in out.flows} == {"bunker"}


def test_copy_is_a_deep_copy() -> None:
    src = _lib()
    out = copy_component_into(_empty(), src, "storage", "h2_tank")
    out.storages[0].capex_per_capacity = 999.0
    assert src.storage("h2_tank").capex_per_capacity == 12.0  # source untouched


def test_place_storage_creates_a_node_under_parent() -> None:
    wb = place_storage({}, _lib(), "h2_tank", parent_id="vc/kr")
    rows = wb["storage"]
    assert len(rows) == 1
    assert rows[0]["company"] == "vc/kr"
    assert rows[0]["storage_id"] == "vc/kr/h2_tank"
    assert rows[0]["flow_id"] == "h2"
    assert {c["flow_id"] for c in wb["flows"]} == {"h2", "elec"}  # closure merged
    # Storage is a NODE in the hierarchy (not a scope row): a leaf under its parent.
    node = next(n for n in wb["nodes"] if n["node_id"] == "vc/kr/h2_tank")
    assert node["parent_id"] == "vc/kr" and node["kind"] == "asset" and node["level"] == "storage"


def test_place_storage_uniquifies_id() -> None:
    wb = place_storage({}, _lib(), "h2_tank", parent_id="vc/kr")
    wb = place_storage(wb, _lib(), "h2_tank", parent_id="vc/kr")
    ids = [r["storage_id"] for r in wb["storage"]]
    assert ids == ["vc/kr/h2_tank", "vc/kr/h2_tank-2"]


def test_place_station_creates_a_node_under_parent() -> None:
    wb = place_station({}, _lib(), "bunkering", parent_id="vc/kr")
    rows = wb["stations"]
    assert len(rows) == 1
    assert rows[0]["company"] == "vc/kr"
    assert rows[0]["station_id"] == "vc/kr/bunkering"
    assert rows[0]["refuel_flow"] == "bunker"
    assert abs(rows[0]["refuel_fee"] - 2.0) < 1e-9
    node = next(n for n in wb["nodes"] if n["node_id"] == "vc/kr/bunkering")
    assert node["parent_id"] == "vc/kr" and node["kind"] == "asset" and node["level"] == "station"


def test_placed_storage_assembles_into_the_problem() -> None:
    # A placed storage row reaches the engine: assemble picks it up as a Storage.
    wb = {
        "meta": [{"key": "base_year", "value": 2025}],
        "periods": [{"year": 2025}],
        "flows": [{"flow_id": "h2", "kind": "energy", "unit": "t"}],
    }
    wb = place_storage(wb, _lib(), "h2_tank", parent_id="all")
    sc = ScenarioConfig.from_dict(
        {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
    )
    prob = assemble_problem(wb, sc)
    placed = [s for s in prob.storages if s.flow_id == "h2"]
    assert len(placed) == 1
    assert abs(placed[0].charge_efficiency - 0.95) < 1e-9


def test_draft_technology_without_io_round_trips() -> None:
    # A half-authored technology (no flows yet) is a valid DRAFT: it must save and
    # reload, so the library — and the user's other work — persists.
    lib = ComponentLibrary.model_validate(
        {
            "label": "draft",
            "technologies": [{"technology_id": "WIP", "io": []}],
            "measures": [
                {"lever_id": "L", "type": "energy_efficiency", "target": "x", "blocks": []}
            ],
        }
    )
    back = library_from_workbook(library_to_workbook(lib))
    t = back.technology("WIP")
    assert t is not None and t.io == []
    m = back.lever("L")
    assert m is not None and m.blocks == []


def _lib_full() -> ComponentLibrary:
    return ComponentLibrary.model_validate(
        {
            "label": "base",
            "flows": [
                {"flow_id": "elec", "kind": "energy", "unit": "MWh", "price": 50.0},
                {"flow_id": "steel", "kind": "product", "unit": "t"},
            ],
            "technologies": [
                {
                    "technology_id": "EAF",
                    "io": [
                        {"target": "steel", "role": "output", "coefficient": 1, "is_product": True},
                        {"target": "elec", "role": "input", "coefficient": 2},
                    ],
                    "maccs": ["M"],
                }
            ],
            "measures": [
                {
                    "lever_id": "eff",
                    "type": "energy_efficiency",
                    "target": "elec",
                    "blocks": [{"reduction": 0.1, "capex_per_capacity": 5.0}],
                }
            ],
            "maccs": [{"macc_id": "M", "label": "M", "measures": ["eff"]}],
        }
    )


def test_place_component_is_uniform_node_plus_copy() -> None:
    from pathwise.data.components import place_component

    lib = _lib_full()
    # Flow → node (level=flow, component link) + flow copied into the model.
    wb = place_component({}, lib, "flow", "elec", parent_id="co")
    fn = next(n for n in wb["nodes"] if n["component"] == "elec")
    assert fn["kind"] == "asset" and fn["level"] == "flow"
    assert any(f["flow_id"] == "elec" for f in wb["flows"])
    # Lever → node + lever def + its blocks copied (the System hard copy).
    wb = place_component(wb, lib, "lever", "eff", parent_id="co")
    ln = next(n for n in wb["nodes"] if n["component"] == "eff")
    assert ln["level"] == "lever"
    assert any(m["lever_id"] == "eff" for m in wb["levers"])
    assert any(b["lever_id"] == "eff" for b in wb["lever_blocks"])
    # MACC → node + macc row + its member lever copied.
    wb = place_component(wb, lib, "macc", "M", parent_id="co")
    assert next(n for n in wb["nodes"] if n["component"] == "M")["level"] == "macc"
    assert any(g["macc_id"] == "M" for g in wb["maccs"])
