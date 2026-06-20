"""copy_component_into: hard-copy a component + its dependency closure into a project."""

from __future__ import annotations

from pathwise.data.components import ComponentLibrary, copy_component_into


def _src() -> ComponentLibrary:
    return ComponentLibrary.model_validate(
        {
            "label": "base",
            "commodities": [
                {"commodity_id": "steel", "kind": "product", "unit": "t"},
                {"commodity_id": "elec", "kind": "energy", "unit": "MWh"},
                {"commodity_id": "scrap", "kind": "material", "unit": "t"},
                {"commodity_id": "unused", "kind": "material", "unit": "t"},
            ],
            "measures": [
                {
                    "measure_id": "eff1",
                    "type": "energy_efficiency",
                    "target": "elec",
                    "blocks": [{"reduction": 0.1, "capex_per_capacity": 5}],
                }
            ],
            "maccs": [{"macc_id": "M", "measures": ["eff1"]}],
            "technologies": [
                {
                    "technology_id": "EAF",
                    "opex": 3.0,
                    "io": [
                        {"target": "steel", "role": "output", "coefficient": 1, "is_product": True},
                        {"target": "elec", "role": "input", "coefficient": 2},
                        {"target": "scrap", "role": "input", "coefficient": 1.1},
                    ],
                    "maccs": ["M"],
                }
            ],
        }
    )


def _empty() -> ComponentLibrary:
    return ComponentLibrary.model_validate({"label": "project"})


def test_copy_technology_brings_its_closure() -> None:
    out = copy_component_into(_empty(), _src(), "technology", "EAF")
    assert {t.technology_id for t in out.technologies} == {"EAF"}
    assert {c.commodity_id for c in out.commodities} == {"steel", "elec", "scrap"}  # not "unused"
    assert {m.measure_id for m in out.measures} == {"eff1"}
    assert {g.macc_id for g in out.maccs} == {"M"}


def test_copy_is_a_deep_copy() -> None:
    src = _src()
    out = copy_component_into(_empty(), src, "technology", "EAF")
    out.technologies[0].opex = 999.0
    assert src.technology("EAF").opex == 3.0  # source untouched


def test_existing_dependency_is_reused_not_overwritten() -> None:
    dst = ComponentLibrary.model_validate(
        {
            "label": "p",
            "commodities": [{"commodity_id": "elec", "kind": "energy", "unit": "GJ", "price": 7.0}],
        }
    )
    out = copy_component_into(dst, _src(), "technology", "EAF")
    elec = [c for c in out.commodities if c.commodity_id == "elec"]
    assert len(elec) == 1 and elec[0].unit == "GJ" and elec[0].price == 7.0


def test_copy_stream_only() -> None:
    out = copy_component_into(_empty(), _src(), "stream", "steel")
    assert {c.commodity_id for c in out.commodities} == {"steel"}
    assert out.technologies == []


def test_copy_macc_brings_measures() -> None:
    out = copy_component_into(_empty(), _src(), "macc", "M")
    assert {g.macc_id for g in out.maccs} == {"M"}
    assert {m.measure_id for m in out.measures} == {"eff1"}
    assert {c.commodity_id for c in out.commodities} == {"elec"}  # measure target
