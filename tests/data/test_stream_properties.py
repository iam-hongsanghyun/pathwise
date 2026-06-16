"""Physical stream properties (temperature, voltage, …) are carried as metadata."""

from __future__ import annotations

from pathwise.data import ScenarioConfig, assemble_problem
from pathwise.data.components import (
    ComponentLibrary,
    library_from_workbook,
    library_to_workbook,
)


def test_commodity_properties_assemble_onto_the_stream() -> None:
    wb = {
        "periods": [{"year": 2025, "duration_years": 1}],
        "commodities": [{"commodity_id": "steam", "kind": "energy", "unit": "GJ"}],
        "commodity_properties": [
            {"commodity_id": "steam", "property": "temperature_C", "value": 600},
            {"commodity_id": "steam", "property": "pressure_bar", "value": 120},
        ],
    }
    prob = assemble_problem(wb, ScenarioConfig.from_dict({}))
    assert prob.commodities["steam"].properties == {
        "temperature_C": 600.0,
        "pressure_bar": 120.0,
    }


def test_properties_round_trip_through_component_library() -> None:
    lib = ComponentLibrary.model_validate(
        {
            "label": "t",
            "commodities": [
                {
                    "commodity_id": "grid",
                    "kind": "energy",
                    "unit": "MWh",
                    "properties": {"voltage_kV": 154.0},
                }
            ],
        }
    )
    back = library_from_workbook(library_to_workbook(lib))
    assert back.commodities[0].properties == {"voltage_kV": 154.0}
