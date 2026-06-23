"""The shared variant compiler used by both the optimise and simulate backends."""

from __future__ import annotations

from pathwise.backends.variants import compile_variant, find_variant, read_model_variants


def _model() -> dict:
    return {
        "periods": [{"year": 2025}, {"year": 2030}],
        "variants": [{"variant_id": "v1", "label": "Green"}],
        "variant_interventions": [
            {
                "variant_id": "v1",
                "kind": "tech",
                "target": "m1",
                "value": "EAF",
                "forced_year": 2030,
            },
            {"variant_id": "v1", "kind": "tech_cost", "target": "EAF", "field": "opex", "value": 9},
            {
                "variant_id": "v1",
                "kind": "io_coef",
                "target": "EAF",
                "field": "scrap",
                "value": 0.8,
                "forced_year": 2030,
            },
            {
                "variant_id": "v1",
                "kind": "stream_cap",
                "target": "scrap",
                "field": "max_purchase",
                "value": 50,
            },
        ],
    }


def test_read_model_variants_maps_each_kind() -> None:
    [v] = read_model_variants(_model())
    assert v["variant_id"] == "v1" and v["label"] == "Green"
    # tech → a forced timed switch (not an override)
    assert v["forced"] == {"m1": ("EAF", 2030)}
    ops = {o["op"] for o in v["overrides"]}
    assert ops == {"set_tech_cost", "set_io_coef", "set_stream_cap"}

    by_op = {o["op"]: o for o in v["overrides"]}
    assert by_op["set_tech_cost"] == {
        "op": "set_tech_cost",
        "technology": "EAF",
        "field": "opex",
        "value": 9.0,
    }
    # io_coef carried a forced_year ⇒ a year-scoped edit
    assert by_op["set_io_coef"] == {
        "op": "set_io_coef",
        "technology": "EAF",
        "commodity": "scrap",
        "value": 0.8,
        "year": 2030,
    }
    assert by_op["set_stream_cap"]["field"] == "max_purchase"


def test_blank_forced_year_defaults_to_first_modelled_year() -> None:
    [v] = read_model_variants(_model())
    # the bare stream_cap row (no forced_year) is static — no 'year' key
    assert "year" not in {**{o["op"]: o for o in v["overrides"]}["set_stream_cap"]}
    # the tech switch with no year would default to 2025 (first period); here it had 2030
    assert v["forced"]["m1"][1] == 2030


def test_find_variant_and_compile() -> None:
    model = _model()
    model["technologies"] = [{"technology_id": "EAF", "opex": 1}]
    model["io"] = [{"technology_id": "EAF", "target": "scrap", "role": "input", "coefficient": 1.0}]
    model["commodities"] = [{"commodity_id": "scrap", "max_purchase": 999}]
    v = find_variant(model, "v1")
    assert v is not None
    edited, forced = compile_variant(model, v)
    assert forced == {"m1": ("EAF", 2030)}
    # overrides were applied to the edited workbook (input untouched)
    assert edited["technologies"][0]["opex"] == 9.0
    assert model["technologies"][0]["opex"] == 1  # original intact
    assert edited["commodities"][0]["max_purchase"] == 50.0
    assert find_variant(model, "nope") is None
