"""Blend-group fuel mix: optimiser shifts the mix within share bounds (B1)."""

from __future__ import annotations

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _sc() -> ScenarioConfig:
    return ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _solve(wb: dict) -> dict:
    return extract_results(solve(build(assemble_problem(wb, _sc()))))


def _wb(coal_min: float, coal_max: float, coal_price: float, h2_price: float) -> dict:
    # One facility making `widget`; technology T burns a coal+H2 energy blend with
    # a total requirement of 2 energy/unit (1 coal + 1 H2 baseline). The optimiser
    # picks the cheaper fuel within the share bounds.
    return {
        "periods": [{"year": 2025}],
        "commodities": [
            {"commodity_id": "coal", "kind": "energy", "price": coal_price},
            {"commodity_id": "h2", "kind": "energy", "price": h2_price},
            {"commodity_id": "widget", "kind": "product"},
        ],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 100}
        ],
        "io": [
            {
                "technology_id": "T",
                "target": "coal",
                "role": "input",
                "coefficient": 1,
                "group": "fuel",
                "share_min": coal_min,
                "share_max": coal_max,
            },
            {
                "technology_id": "T",
                "target": "h2",
                "role": "input",
                "coefficient": 1,
                "group": "fuel",
                "share_min": 0,
                "share_max": 1,
            },
            {
                "technology_id": "T",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "demand": [{"company": "C", "commodity_id": "widget", "year": 2025, "amount": 50}],
    }


def test_blend_picks_cheapest_within_bounds() -> None:
    # Coal cheap (1) vs H2 dear (10); coal allowed up to 80% of the mix.
    # Group total = 2 energy/unit × 50 = 100 energy. Coal ≤ 0.8 ⇒ 80 coal, 20 H2.
    res = _solve(_wb(coal_min=0.0, coal_max=0.8, coal_price=1.0, h2_price=10.0))
    assert res["status"] == "optimal"
    # 80 coal × $1 + 20 h2 × $10 = 80 + 200 = 280.
    np.testing.assert_allclose(res["objective"], 280.0, rtol=1e-6)
    comm = {
        (r["commodity"], r["period"]): r["consumed"] for r in res["summary"]["commodity"]
    }
    np.testing.assert_allclose(comm[("coal", 2025)], 80.0, rtol=1e-6)
    np.testing.assert_allclose(comm[("h2", 2025)], 20.0, rtol=1e-6)


def test_blend_min_share_forces_expensive_fuel() -> None:
    # H2 cheap now, but coal must be at least 30% of the mix (must-burn floor).
    res = _solve(_wb(coal_min=0.3, coal_max=1.0, coal_price=10.0, h2_price=1.0))
    assert res["status"] == "optimal"
    # 30 coal × $10 + 70 h2 × $1 = 300 + 70 = 370.
    np.testing.assert_allclose(res["objective"], 370.0, rtol=1e-6)
    comm = {
        (r["commodity"], r["period"]): r["consumed"] for r in res["summary"]["commodity"]
    }
    np.testing.assert_allclose(comm[("coal", 2025)], 30.0, rtol=1e-6)
    np.testing.assert_allclose(comm[("h2", 2025)], 70.0, rtol=1e-6)
