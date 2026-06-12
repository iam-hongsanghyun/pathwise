"""Output slate groups: the optimiser picks the co-product mix within bounds (L1)."""

from __future__ import annotations

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem, validate


def _sc() -> ScenarioConfig:
    return ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _solve(wb: dict) -> dict:
    return extract_results(solve(build(assemble_problem(wb, _sc()))))


def _wb(
    eth_min: float,
    eth_max: float,
    eth_sale: float,
    pro_sale: float,
) -> dict:
    """One cracker making an ethylene+propylene slate from naphtha.

    Total slate requirement = 1.0 t per t throughput (0.6 ethylene + 0.4
    propylene baseline). Demand pulls 50 t of ethylene; the propylene co-product
    is sellable. With zero discounting every coefficient is analytic.
    """
    return {
        "periods": [{"year": 2025}],
        "commodities": [
            {"commodity_id": "naphtha", "kind": "material", "price": 10.0},
            {"commodity_id": "ethylene", "kind": "product", "sale_price": eth_sale},
            {"commodity_id": "propylene", "kind": "byproduct", "sale_price": pro_sale},
        ],
        "technologies": [{"technology_id": "NCC", "opex": 1.0}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "NCC", "capacity": 1000}
        ],
        "io": [
            {"technology_id": "NCC", "target": "naphtha", "role": "input", "coefficient": 1.2},
            {
                "technology_id": "NCC",
                "target": "ethylene",
                "role": "output",
                "coefficient": 0.6,
                "is_product": True,
                "group": "slate",
                "share_min": eth_min,
                "share_max": eth_max,
            },
            {
                "technology_id": "NCC",
                "target": "propylene",
                "role": "output",
                "coefficient": 0.4,
                "group": "slate",
                "share_min": 1.0 - eth_max,
                "share_max": 1.0 - eth_min,
            },
        ],
        "demand": [{"company": "C", "commodity_id": "ethylene", "year": 2025, "amount": 50.0}],
        "impacts": [],
        "markets": [],
        "storage": [],
    }


def _produced(res: dict, commodity: str) -> float:
    return sum(s["produced"] for s in res["summary"]["commodity"] if s["commodity"] == commodity)


def test_slate_shifts_to_max_share_of_demanded_product() -> None:
    # Ethylene demand binds and propylene is worthless ⇒ the cheapest way to
    # make 50 t ethylene is to push its slate share to share_max = 0.8:
    # throughput x = 50 / 0.8 = 62.5 ; propylene = 0.2 · x = 12.5.
    res = _solve(_wb(eth_min=0.4, eth_max=0.8, eth_sale=0.0, pro_sale=0.0))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_produced(res, "ethylene"), 50.0, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(_produced(res, "propylene"), 12.5, rtol=1e-6, atol=1e-6)


def test_slate_shifts_to_valuable_coproduct() -> None:
    # Per unit throughput: cost 13 (opex 1 + 1.2·10 naphtha). At propylene
    # price 20, shifting the slate toward propylene pays (flip point p = 13)
    # but running beyond demand does not (flat-out point p = 26) — so ethylene
    # is pinned to its share_min = 0.5 while exactly meeting demand:
    # x = 50 / 0.5 = 100 ; propylene = 0.5 · 100 = 50.
    res = _solve(_wb(eth_min=0.5, eth_max=0.8, eth_sale=0.0, pro_sale=20.0))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_produced(res, "ethylene"), 50.0, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(_produced(res, "propylene"), 50.0, rtol=1e-6, atol=1e-6)


def test_degenerate_bounds_reproduce_fixed_yields() -> None:
    # lo = hi = baseline shares ⇒ identical to the fixed-yield model:
    # x = 50 / 0.6 ; propylene = 0.4 · x.
    res = _solve(_wb(eth_min=0.6, eth_max=0.6, eth_sale=0.0, pro_sale=0.0))
    assert res["status"] == "optimal"
    x = 50.0 / 0.6
    np.testing.assert_allclose(_produced(res, "ethylene"), 50.0, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(_produced(res, "propylene"), 0.4 * x, rtol=1e-6, atol=1e-6)


def test_shares_sum_to_requirement() -> None:
    # Whatever the split, total slate output = R_G · x = 1.0 · x and the
    # objective covers the naphtha + opex of that throughput.
    res = _solve(_wb(eth_min=0.4, eth_max=0.8, eth_sale=0.0, pro_sale=0.0))
    x = 50.0 / 0.8
    total = _produced(res, "ethylene") + _produced(res, "propylene")
    np.testing.assert_allclose(total, 1.0 * x, rtol=1e-6, atol=1e-6)
    # cost = x · (opex 1.0 + 1.2 naphtha · 10) = x · 13
    np.testing.assert_allclose(res["objective"], x * 13.0, rtol=1e-6, atol=1e-4)


def test_infeasible_share_bounds_rejected() -> None:
    wb = _wb(eth_min=0.4, eth_max=0.8, eth_sale=0.0, pro_sale=0.0)
    # Force Σ share_min = 0.9 + 0.4 > 1 on the slate group.
    wb["io"][1]["share_min"] = 0.9
    wb["io"][2]["share_min"] = 0.4
    report = validate(wb)
    assert not report.ok
    assert any("share_min values sum" in e for e in report.errors)
