"""MACC tables: catalogue levers bundled into named MACCs, deployed by link.

The model: ``levers`` is a catalogue (no target needed), ``maccs`` rows
{macc, lever_id} build named bundles (a lever may sit in several), and
``macc_links`` rows {macc, facility|technology|commodity|storage} deploy a
bundle: a commodity (stream) reaches every facility whose baseline technology
consumes it, a storage reaches the consumers of its stored stream. Direct
``facility``/``technology`` columns on a lever remain a one-off shortcut.
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
        # Catalogue: neither lever names a facility or technology directly.
        "levers": [
            {"lever_id": "fuel_saver", "type": "energy_efficiency", "target": "fuel"},
            {"lever_id": "co2_scrub", "type": "energy_efficiency", "target": "fuel"},
        ],
        "lever_blocks": [
            {"lever_id": "fuel_saver", "block": 0, "reduction": 0.2, "capex": 100.0},
            {"lever_id": "co2_scrub", "block": 0, "reduction": 0.1, "capex": 50.0},
        ],
        # fuel_saver is reused in BOTH bundles; co2_scrub only in the U one.
        "maccs": [
            {"macc": "T pack", "lever_id": "fuel_saver"},
            {"macc": "U pack", "lever_id": "fuel_saver"},
            {"macc": "U pack", "lever_id": "co2_scrub"},
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
    ids = sorted(m.lever_id for m in prob.levers)
    # fuel_saver: T pack→{Big, Small} ∪ U pack→{Other}; co2_scrub: {Other} only.
    assert ids == [
        "co2_scrub",
        "fuel_saver @ Big",
        "fuel_saver @ Other",
        "fuel_saver @ Small",
    ]
    assert {m.applies_to for m in prob.levers if m.lever_id.startswith("fuel_saver")} == {
        "Big",
        "Small",
        "Other",
    }


def test_catalogue_lever_without_links_creates_no_instances() -> None:
    wb = _wb()
    wb["maccs"] = []
    wb["macc_links"] = []
    prob = _problem(wb)
    assert prob.levers == [], "catalogue-only levers are inert until deployed"


def test_direct_facility_and_technology_columns() -> None:
    wb = _wb()
    wb["maccs"] = []
    wb["macc_links"] = []
    wb["levers"][0]["facility"] = "Other"
    wb["levers"][1]["technology"] = "T"
    prob = _problem(wb)
    ids = sorted(m.lever_id for m in prob.levers)
    assert ids == ["co2_scrub @ Big", "co2_scrub @ Small", "fuel_saver"]


def test_macc_deploys_via_stream() -> None:
    wb = _wb()
    # Both baseline technologies (T, U) consume fuel → all three facilities.
    wb["macc_links"] = [{"macc": "T pack", "commodity": "fuel"}]
    prob = _problem(wb)
    assert sorted(m.applies_to for m in prob.levers if m.lever_id.startswith("fuel_saver")) == [
        "Big",
        "Other",
        "Small",
    ]


def test_macc_deploys_via_storage() -> None:
    wb = _wb()
    # A store resolves through its stream to the stream's consumers.
    wb["storage"] = [{"storage_id": "tank", "commodity_id": "fuel"}]
    wb["macc_links"] = [{"macc": "T pack", "storage": "tank"}]
    prob = _problem(wb)
    assert sorted(m.applies_to for m in prob.levers if m.lever_id.startswith("fuel_saver")) == [
        "Big",
        "Other",
        "Small",
    ]


def test_macc_storage_link_without_store_is_inert() -> None:
    wb = _wb()
    wb["macc_links"] = [{"macc": "T pack", "storage": "missing_tank"}]
    prob = _problem(wb)
    assert all(not m.lever_id.startswith("fuel_saver") for m in prob.levers)


def test_duplicate_membership_does_not_double_instances() -> None:
    wb = _wb()
    # Linking both bundles to the SAME technology must not duplicate pairs.
    wb["macc_links"] = [
        {"macc": "T pack", "technology": "T"},
        {"macc": "U pack", "technology": "T"},
    ]
    prob = _problem(wb)
    pairs = [(m.lever_id, m.applies_to) for m in prob.levers]
    assert len(pairs) == len(set(pairs))
    assert sorted(m.applies_to for m in prob.levers if "fuel_saver" in m.lever_id) == [
        "Big",
        "Small",
    ]
