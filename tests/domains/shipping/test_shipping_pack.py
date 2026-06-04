"""Shipping pack: workbook → problem → solve, plus validation."""

from __future__ import annotations

import numpy as np

from pathwise.core import build, solve
from pathwise.data import ScenarioConfig, Workbook
from pathwise.domains.base import get_domain


def _shipping_workbook() -> Workbook:
    """A tiny shipping workbook in the generic schema."""
    return {
        "periods": [
            {"year": 2025, "duration_years": 1, "activity_multiplier": 1},
            {"year": 2030, "duration_years": 1, "activity_multiplier": 1},
        ],
        "assets": [
            {
                "asset_id": "ship1",
                "group": "OpA",
                "capacity": 1e9,
                "size": 1000,
                "technology_id": "HFO",
                "built_year": 2010,
                "activity": 100.0,
            }
        ],
        "technologies": [
            {"technology_id": "HFO", "specific_energy": 1.0},
            {"technology_id": "LNG", "specific_energy": 1.0},
        ],
        "carriers": [
            {"carrier_id": "hfo", "intensity": 90.0, "cost": 1.0},
            {"carrier_id": "lng", "intensity": 40.0, "cost": 2.0},
        ],
        "carrier_compatibility": [
            {"technology_id": "HFO", "carrier_id": "hfo"},
            {"technology_id": "LNG", "carrier_id": "lng"},
        ],
        "baseline_mix": [
            {"technology_id": "HFO", "carrier_id": "hfo", "share": 1.0},
            {"technology_id": "LNG", "carrier_id": "lng", "share": 1.0},
        ],
        "transitions": [
            {
                "from_technology_id": "HFO",
                "to_technology_id": "LNG",
                "capex_per_size": 10.0,
                "lifetime": 20,
            }
        ],
        "targets": [
            {
                "target_set": "Tier1",
                "group": "OpA",
                "target_type": "intensity_cap",
                "year": 2025,
                "limit": 90.0,
            },
            {
                "target_set": "Tier1",
                "group": "OpA",
                "target_type": "intensity_cap",
                "year": 2030,
                "limit": 50.0,
            },
        ],
    }


def _scenario() -> ScenarioConfig:
    return ScenarioConfig.from_dict(
        {
            "name": "tier1",
            "domain": "shipping",
            "selection": {"target_set": "Tier1"},
            "economics": {"discount_rate": 0.0, "base_period": 2025, "capex_convention": "npv"},
        }
    )


def test_shipping_pack_registered() -> None:
    pack = get_domain("shipping")
    assert pack.label == "Shipping Fleet"
    assert pack.terminology()["asset"] == "Ship"
    assert "assets" in pack.schema()


def test_shipping_validation_passes_on_good_workbook() -> None:
    pack = get_domain("shipping")
    report = pack.validate(_shipping_workbook())
    assert report.ok, report.errors


def test_shipping_validation_flags_bad_engine_reference() -> None:
    pack = get_domain("shipping")
    wb = _shipping_workbook()
    wb["assets"][0]["technology_id"] = "NUCLEAR"  # not in technologies
    report = pack.validate(wb)
    assert not report.ok
    assert any("NUCLEAR" in e for e in report.errors)


def test_shipping_build_and_solve_forces_transition() -> None:
    pack = get_domain("shipping")
    problem = pack.build_problem(_shipping_workbook(), _scenario())
    res = solve(build(problem))
    assert res.ok
    # fuel 2025 (HFO, 100) + fuel 2030 (LNG, 200) + transition CAPEX (10*1000) = 10300.
    np.testing.assert_allclose(res.objective, 10300.0, rtol=1e-6)
    u = res.context.u.solution
    assert u.sel(asset="ship1", technology="LNG", period=2030).item() == 1.0
    assert u.sel(asset="ship1", technology="HFO", period=2025).item() == 1.0
