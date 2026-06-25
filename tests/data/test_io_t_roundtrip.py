"""Per-year io coefficients (``io_t``) round-trip through the component library.

The model + assembler already supported time-varying coefficients; the component
library projection dropped them. These cover the closed round-trip and that a
placed technology carries its io_t into the network workbook.
"""

from __future__ import annotations

from pathwise.data.components import (
    ComponentLibrary,
    library_from_workbook,
    library_to_workbook,
    place_technology,
)

_LIB = {
    "label": "t",
    "flows": [
        {"flow_id": "elec", "kind": "energy", "unit": "MWh"},
        {"flow_id": "steel", "kind": "product", "unit": "t"},
    ],
    "technologies": [
        {
            "technology_id": "EAF",
            "io": [
                {"target": "steel", "role": "output", "coefficient": 1, "is_product": True},
                {"target": "elec", "role": "input", "coefficient": 2.0},
                {"target": "CO2", "role": "impact", "coefficient": 0.5},
            ],
            "input_intensity_by_year": {"elec": {2030: 1.5, 2040: 1.0}},
            "direct_impact_by_year": {"CO2": {2040: 0.2}},
        }
    ],
}


def test_io_t_round_trips_through_component_library() -> None:
    back = library_from_workbook(library_to_workbook(ComponentLibrary.model_validate(_LIB)))
    t = back.technologies[0]
    assert t.input_intensity_by_year == {"elec": {2030: 1.5, 2040: 1.0}}
    assert t.direct_impact_by_year == {"CO2": {2040: 0.2}}
    assert t.output_yield_by_year == {}  # none authored


def test_no_io_t_emits_no_sheet() -> None:
    lib = ComponentLibrary.model_validate(
        {
            **_LIB,
            "technologies": [
                {
                    **_LIB["technologies"][0],
                    "input_intensity_by_year": {},
                    "direct_impact_by_year": {},
                }
            ],
        }
    )
    assert "io_t" not in library_to_workbook(lib)  # trajectory-free stays byte-identical


def test_place_technology_carries_io_t_into_the_workbook() -> None:
    lib = ComponentLibrary.model_validate(_LIB)
    wb = place_technology({}, lib, "EAF", parent_id="root", capacity=100)
    iot = wb.get("io_t", [])
    assert any(
        r["target"] == "elec"
        and r["role"] == "input"
        and r["year"] == 2030
        and r["coefficient"] == 1.5
        for r in iot
    )
    assert any(r["target"] == "CO2" and r["role"] == "impact" and r["year"] == 2040 for r in iot)
