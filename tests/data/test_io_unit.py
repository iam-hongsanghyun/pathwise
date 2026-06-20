"""The optional per-row IO `unit` round-trips and is honoured at assembly.

The unit survives the library ↔ workbook projection (PR1); at assembly (PR3) a
declared unit that differs from the target stream's unit is converted to it.
"""

from __future__ import annotations

import numpy as np

from pathwise.data import ScenarioConfig, assemble_problem
from pathwise.data.components import (
    ComponentLibrary,
    library_from_workbook,
    library_to_workbook,
)

_LIB = {
    "label": "t",
    "commodities": [
        {"commodity_id": "steel", "kind": "product", "unit": "t"},
        {"commodity_id": "elec", "kind": "energy", "unit": "MWh"},
    ],
    "technologies": [
        {
            "technology_id": "EAF",
            "io": [
                {"target": "steel", "role": "output", "coefficient": 1.0, "is_product": True},
                {"target": "elec", "role": "input", "coefficient": 2.5, "unit": "GJ"},
            ],
        }
    ],
}


def test_io_unit_round_trips_through_component_library() -> None:
    lib = ComponentLibrary.model_validate(_LIB)
    back = library_from_workbook(library_to_workbook(lib))
    io = {(r.target, r.role): r for r in back.technologies[0].io}
    # A declared unit survives; an undeclared one stays absent (= the stream's unit).
    assert io[("elec", "input")].unit == "GJ"
    assert io[("steel", "output")].unit is None


def test_io_unit_is_emitted_to_the_workbook_only_when_set() -> None:
    lib = ComponentLibrary.model_validate(_LIB)
    wb = library_to_workbook(lib)
    rows = {(r["target"], r["role"]): r for r in wb["io"]}
    assert rows[("elec", "input")]["unit"] == "GJ"
    # Undeclared rows carry no unit value (None or absent — never a stray string).
    assert rows[("steel", "output")].get("unit") is None


def test_library_with_io_units_assembles_and_converts() -> None:
    # _LIB authors elec at 2.5 GJ against an MWh stream; assembly converts to MWh.
    wb = library_to_workbook(ComponentLibrary.model_validate(_LIB))
    wb["periods"] = [{"year": 2025, "duration_years": 1}]
    prob = assemble_problem(wb, ScenarioConfig.from_dict({}))
    np.testing.assert_allclose(
        prob.technologies["EAF"].input_intensity["elec"], 2.5 / 3.6, rtol=1e-9
    )
