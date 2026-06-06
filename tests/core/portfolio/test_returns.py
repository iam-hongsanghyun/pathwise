"""Per-asset reward computation against a hand-computed 2-technology problem."""

from __future__ import annotations

import numpy as np

from pathwise.core.entities import (
    Commodity,
    CommodityKind,
    Period,
    Process,
    Technology,
    Transition,
)
from pathwise.core.portfolio.assets import AssetLevel, enumerate_assets
from pathwise.core.portfolio.returns import RewardMode, returns_matrix
from pathwise.core.portfolio.scenarios import generate_scenarios
from pathwise.core.problem import Problem


def _problem(capex_per_capacity: float = 0.0, prod_sale: float = 0.0) -> Problem:
    """One facility (baseline A) that may switch to cheaper technology B.

    Single period, zero discounting (DF = 1), no shocks → analytic rewards.
    """
    a = Technology(
        technology_id="A",
        opex_by_year={2025: 10.0},
        input_intensity={"fuel": 2.0},
        output_yield={"prod": 1.0},
    )
    b = Technology(
        technology_id="B",
        opex_by_year={2025: 5.0},
        input_intensity={"fuel": 1.0},
        output_yield={"prod": 1.0},
    )
    return Problem(
        periods=[Period(2025, 1.0)],
        processes=[Process(process_id="P1", company="C", baseline_technology="A", capacity=100.0)],
        technologies={"A": a, "B": b},
        commodities={
            "fuel": Commodity("fuel", CommodityKind.ENERGY, price_by_year={2025: 3.0}),
            "prod": Commodity("prod", CommodityKind.PRODUCT, sale_price_by_year={2025: prod_sale}),
        },
        impacts={},
        transitions=[
            Transition(
                from_technology="A", to_technology="B", capex_per_capacity=capex_per_capacity
            )
        ],
        discount_rate=0.0,
        base_year=2025,
    )


def _certain() -> object:
    """A single scenario with no shocks (all multipliers ≡ 1)."""
    return generate_scenarios(0, 1, {})


def test_cost_reduction_reward_no_capex() -> None:
    prob = _problem()
    assets = enumerate_assets(prob, AssetLevel.FACILITY)
    assert len(assets) == 1
    # run(A) = 10*100 + 2*100*3 = 1600 ; run(B) = 5*100 + 1*100*3 = 800.
    R = returns_matrix(
        prob, assets, _certain(), RewardMode.COST_REDUCTION, normalize_by_capex=False
    )
    np.testing.assert_allclose(R[0, 0], 1600.0 - 800.0, rtol=0, atol=1e-9)


def test_profit_reward_no_capex() -> None:
    prob = _problem()
    assets = enumerate_assets(prob, AssetLevel.FACILITY)
    R = returns_matrix(prob, assets, _certain(), RewardMode.PROFIT, normalize_by_capex=False)
    # profit = revenue(0) - run(B) = -800.
    np.testing.assert_allclose(R[0, 0], -800.0, rtol=0, atol=1e-9)


def test_capex_subtracts_from_both_modes() -> None:
    prob = _problem(capex_per_capacity=2.0)  # transition_capex = 2 * 100 = 200.
    assets = enumerate_assets(prob, AssetLevel.FACILITY)
    cr = returns_matrix(
        prob, assets, _certain(), RewardMode.COST_REDUCTION, normalize_by_capex=False
    )
    pr = returns_matrix(prob, assets, _certain(), RewardMode.PROFIT, normalize_by_capex=False)
    np.testing.assert_allclose(cr[0, 0], 800.0 - 200.0, rtol=0, atol=1e-9)
    np.testing.assert_allclose(pr[0, 0], -800.0 - 200.0, rtol=0, atol=1e-9)


def test_profit_includes_product_revenue() -> None:
    prob = _problem(prod_sale=4.0)
    assets = enumerate_assets(prob, AssetLevel.FACILITY)
    R = returns_matrix(prob, assets, _certain(), RewardMode.PROFIT, normalize_by_capex=False)
    # run(B) net of sales = 800 - 1*100*4 = 400 ; profit = -400.
    np.testing.assert_allclose(R[0, 0], -400.0, rtol=0, atol=1e-9)


def test_matrix_shape_matches_scenarios_and_assets() -> None:
    prob = _problem()
    assets = enumerate_assets(prob, AssetLevel.FACILITY)
    R = returns_matrix(prob, assets, generate_scenarios(0, 64), RewardMode.COST_REDUCTION)
    assert R.shape == (64, len(assets))
