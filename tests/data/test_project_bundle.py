"""Project-bundle helpers: which technologies a model references, and slicing a
base library down to that closure for a self-contained export."""

from __future__ import annotations

from pathwise.data.components import (
    PROJECT_BUNDLE_FORMAT,
    ComponentLibrary,
    ProjectBundle,
    referenced_technology_ids,
    slice_library_to_technologies,
)


def _base_lib() -> ComponentLibrary:
    return ComponentLibrary.model_validate(
        {
            "label": "base",
            "flows": [
                {"flow_id": "ore", "kind": "material", "unit": "t"},
                {"flow_id": "scrap", "kind": "material", "unit": "t"},
                {"flow_id": "steel", "kind": "product", "unit": "t"},
            ],
            "technologies": [
                {
                    "technology_id": "BF",
                    "io": [
                        {"target": "ore", "role": "input", "coefficient": 1.0},
                        {
                            "target": "steel",
                            "role": "output",
                            "coefficient": 1.0,
                            "is_product": True,
                        },
                    ],
                },
                {
                    "technology_id": "EAF",
                    "io": [
                        {"target": "scrap", "role": "input", "coefficient": 1.0},
                        {
                            "target": "steel",
                            "role": "output",
                            "coefficient": 1.0,
                            "is_product": True,
                        },
                    ],
                },
                {
                    "technology_id": "UNUSED",
                    "io": [{"target": "steel", "role": "output", "coefficient": 1.0}],
                },
            ],
        }
    )


def test_referenced_ids_from_machines_and_transitions() -> None:
    model = {
        "assets": [
            {"asset_id": "m1", "baseline_technology": "BF"},
            {"asset_id": "m2", "baseline_technology": ""},  # blank baseline dropped
        ],
        "transitions": [{"from_technology": "BF", "to_technology": "EAF"}],
    }
    assert referenced_technology_ids(model) == {"BF", "EAF"}


def test_referenced_ids_tolerates_missing_sheets() -> None:
    assert referenced_technology_ids({}) == set()


def test_slice_keeps_only_referenced_plus_closure() -> None:
    sliced = slice_library_to_technologies(_base_lib(), {"BF"})
    assert [t.technology_id for t in sliced.technologies] == ["BF"]
    # BF's io-target flows come along; EAF-only "scrap" does not.
    assert {c.flow_id for c in sliced.flows} == {"ore", "steel"}


def test_slice_unknown_tech_yields_empty_library() -> None:
    sliced = slice_library_to_technologies(_base_lib(), {"NOPE"})
    assert sliced.technologies == [] and sliced.flows == []


def test_slice_does_not_mutate_source() -> None:
    src = _base_lib()
    before = src.model_dump()
    slice_library_to_technologies(src, {"BF", "EAF"})
    assert src.model_dump() == before


def test_bundle_defaults() -> None:
    bundle = ProjectBundle(name="Demo")
    assert bundle.format == PROJECT_BUNDLE_FORMAT
    assert bundle.version == 1
    assert bundle.session_libraries == {} and bundle.base_libraries == {}
