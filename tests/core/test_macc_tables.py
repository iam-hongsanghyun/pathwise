"""MACC tables: catalogue measures bundled into named MACCs, deployed by link.

The model: ``measures`` is a catalogue (no target needed), ``maccs`` rows
{macc, measure_id} build named bundles (a measure may sit in several), and
``macc_links`` rows {macc, facility|technology} deploy a bundle. Direct
``facility``/``technology`` columns on a measure remain a one-off shortcut.
"""

from __future__ import annotations

from pathwise.data import ScenarioConfig, assemble_problem


def _wb() -> dict:
    """Two facilities on technology T plus one on technology U."""
    return {
        "periods": [{"year": 2025}],
        "commodities": [
            {"commodity_id": "fuel", "kind": "energy", "price": 10.0},
            {"commodity_id": "widget", "kind": "product"},
        ],
        "technologies": [{"technology_id": "T"}, {"technology_id": "U"}],
        "io": [
            {"technology_id": "T", "target": "fuel", "role": "input", "coefficient": 2},
            {
                "technology_id": "T",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
            {"technology_id": "U", "target": "fuel", "role": "input", "coefficient": 3},
            {
                "technology_id": "U",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "processes": [
            {"process_id": "Big", "company": "C", "baseline_technology": "T", "capacity": 100},
            {"process_id": "Small", "company": "C", "baseline_technology": "T", "capacity": 10},
            {"process_id": "Other", "company": "C", "baseline_technology": "U", "capacity": 50},
        ],
        # Catalogue: neither measure names a facility or technology directly.
        "measures": [
            {"measure_id": "fuel_saver", "type": "energy_efficiency", "target": "fuel"},
            {"measure_id": "co2_scrub", "type": "energy_efficiency", "target": "fuel"},
        ],
        "measure_blocks": [
            {"measure_id": "fuel_saver", "block": 0, "reduction": 0.2, "capex": 100.0},
            {"measure_id": "co2_scrub", "block": 0, "reduction": 0.1, "capex": 50.0},
        ],
        # fuel_saver is reused in BOTH bundles; co2_scrub only in the U one.
        "maccs": [
            {"macc": "T pack", "measure_id": "fuel_saver"},
            {"macc": "U pack", "measure_id": "fuel_saver"},
            {"macc": "U pack", "measure_id": "co2_scrub"},
        ],
        "macc_links": [
            {"macc": "T pack", "technology": "T"},
            {"macc": "U pack", "facility": "Other"},
        ],
        "demand": [{"company": "C", "commodity_id": "widget", "year": 2025, "amount": 160}],
        "impacts": [],
        "markets": [],
        "storage": [],
    }


def _problem(wb: dict):
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return assemble_problem(wb, sc)


def test_macc_deploys_to_technology_and_facility() -> None:
    prob = _problem(_wb())
    ids = sorted(m.measure_id for m in prob.measures)
    # fuel_saver: T pack→{Big, Small} ∪ U pack→{Other}; co2_scrub: {Other} only.
    assert ids == [
        "co2_scrub",
        "fuel_saver @ Big",
        "fuel_saver @ Other",
        "fuel_saver @ Small",
    ]
    assert {m.applies_to for m in prob.measures if m.measure_id.startswith("fuel_saver")} == {
        "Big",
        "Small",
        "Other",
    }


def test_catalogue_measure_without_links_creates_no_instances() -> None:
    wb = _wb()
    wb["maccs"] = []
    wb["macc_links"] = []
    prob = _problem(wb)
    assert prob.measures == [], "catalogue-only measures are inert until deployed"


def test_direct_facility_and_technology_columns() -> None:
    wb = _wb()
    wb["maccs"] = []
    wb["macc_links"] = []
    wb["measures"][0]["facility"] = "Other"
    wb["measures"][1]["technology"] = "T"
    prob = _problem(wb)
    ids = sorted(m.measure_id for m in prob.measures)
    assert ids == ["co2_scrub @ Big", "co2_scrub @ Small", "fuel_saver"]


def test_duplicate_membership_does_not_double_instances() -> None:
    wb = _wb()
    # Linking both bundles to the SAME technology must not duplicate pairs.
    wb["macc_links"] = [
        {"macc": "T pack", "technology": "T"},
        {"macc": "U pack", "technology": "T"},
    ]
    prob = _problem(wb)
    pairs = [(m.measure_id, m.applies_to) for m in prob.measures]
    assert len(pairs) == len(set(pairs))
    assert sorted(m.applies_to for m in prob.measures if "fuel_saver" in m.measure_id) == [
        "Big",
        "Small",
    ]
