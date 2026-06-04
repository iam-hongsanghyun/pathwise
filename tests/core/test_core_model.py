"""Analytical-optimum tests for the generic core.

Each test builds a tiny problem whose optimum is computable by hand, then
asserts the solver reproduces it (objective and key decisions). These are the
Phase-1 acceptance gate: the math is verified with zero sector code.
"""

from __future__ import annotations

import numpy as np

from pathwise.core import (
    Asset,
    CapexConvention,
    Carrier,
    MaccBlock,
    Measure,
    OptimisationProblem,
    Period,
    SolveOptions,
    Target,
    TargetType,
    Technology,
    Transition,
    build,
    solve,
)

RTOL = 1e-6


def _solve(problem: OptimisationProblem):
    return solve(build(problem))


def test_basic_fuel_cost() -> None:
    """One asset, one carrier: cost = energy * price."""
    prob = OptimisationProblem(
        periods=[Period(2025)],
        assets=[
            Asset(
                "a1",
                "g",
                capacity=100,
                baseline_technology="k1",
                feasible_technologies=frozenset({"k1"}),
                built_year=2020,
            )
        ],
        technologies=[Technology("k1", specific_energy=2.0, allowed_carriers=frozenset({"r1"}))],
        carriers=[Carrier("r1", price_default=3.0)],
        demand={("g", 2025): 10.0},
        options=SolveOptions(
            discount_rate=0.0,
            base_year=2025,
            include_transitions=False,
            include_new_build=False,
            include_measures=False,
        ),
    )
    res = _solve(prob)
    assert res.ok
    np.testing.assert_allclose(res.objective, 10.0 * 2.0 * 3.0, rtol=RTOL)


def test_intensity_target_forces_fuel_blend() -> None:
    """A 50 gCO2e/MJ cap forces a 50/50 dirty/clean blend; cost = 10*(1+x)."""
    tech = Technology("k1", specific_energy=1.0, allowed_carriers=frozenset({"dirty", "clean"}))
    prob = OptimisationProblem(
        periods=[Period(2025)],
        assets=[
            Asset(
                "a1",
                "g",
                capacity=100,
                baseline_technology="k1",
                feasible_technologies=frozenset({"k1"}),
                built_year=2020,
            )
        ],
        technologies=[tech],
        carriers=[
            Carrier("dirty", price_default=1.0, intensity_default=100.0),
            Carrier("clean", price_default=2.0, intensity_default=0.0),
        ],
        demand={("g", 2025): 10.0},
        targets=[Target("g", TargetType.INTENSITY_CAP, {2025: 50.0})],
        options=SolveOptions(
            discount_rate=0.0,
            base_year=2025,
            include_transitions=False,
            include_new_build=False,
            include_measures=False,
        ),
    )
    res = _solve(prob)
    assert res.ok
    # x_clean = 0.5 ⇒ cost = 10*(0.5*1 + 0.5*2) = 15.
    np.testing.assert_allclose(res.objective, 15.0, rtol=RTOL)


def test_transition_with_capex() -> None:
    """A zero cap in 2026 forces a retrofit to a clean technology; NPV CAPEX adds on."""
    prob = OptimisationProblem(
        periods=[Period(2025), Period(2026)],
        assets=[
            Asset(
                "a1",
                "g",
                capacity=100,
                size=1.0,
                baseline_technology="kd",
                feasible_technologies=frozenset({"kd", "kc"}),
                built_year=2010,
            )
        ],
        technologies=[
            Technology("kd", specific_energy=1.0, allowed_carriers=frozenset({"rd"})),
            Technology("kc", specific_energy=1.0, allowed_carriers=frozenset({"rc"})),
        ],
        carriers=[
            Carrier("rd", price_default=1.0, intensity_default=100.0),
            Carrier("rc", price_default=1.0, intensity_default=0.0),
        ],
        demand={("g", 2025): 10.0, ("g", 2026): 10.0},
        targets=[Target("g", TargetType.INTENSITY_CAP, {2026: 0.0})],
        transitions=[Transition("kd", "kc", capex_per_size=5.0, lifetime_years=30)],
        options=SolveOptions(
            discount_rate=0.0,
            base_year=2025,
            capex_convention=CapexConvention.NPV,
            include_new_build=False,
            include_measures=False,
            max_transitions_per_asset=1,
        ),
    )
    res = _solve(prob)
    assert res.ok
    # fuel 2025 (10) + fuel 2026 (10) + transition CAPEX (5).
    np.testing.assert_allclose(res.objective, 25.0, rtol=RTOL)
    # Clean in 2026, dirty in 2025.
    sol = res.context.u.solution
    np.testing.assert_allclose(
        sol.sel(asset="a1", technology="kc", period=2026).item(), 1.0, atol=1e-6
    )
    np.testing.assert_allclose(
        sol.sel(asset="a1", technology="kd", period=2025).item(), 1.0, atol=1e-6
    )


def test_macc_measure_adopted_under_carbon_price() -> None:
    """A 1 tCO2e abatement block (CAPEX 40) beats a 100 USD carbon bill."""
    prob = OptimisationProblem(
        periods=[Period(2025)],
        assets=[
            Asset(
                "a1",
                "g",
                capacity=2e6,
                baseline_technology="k1",
                feasible_technologies=frozenset({"k1"}),
                built_year=2010,
            )
        ],
        technologies=[Technology("k1", specific_energy=1.0, allowed_carriers=frozenset({"r1"}))],
        carriers=[Carrier("r1", price_default=0.0, intensity_default=1.0)],  # 1 gCO2e/MJ, free fuel
        demand={("g", 2025): 1.0e6},  # 1e6 MJ ⇒ 1e6 gCO2e = 1 tCO2e gross
        measures=[
            Measure(
                "m1",
                applicable_assets=frozenset({"a1"}),
                blocks=(MaccBlock(abatement=1.0, capex=40.0),),
                lifetime_years=30,
            )
        ],
        options=SolveOptions(
            discount_rate=0.0,
            base_year=2025,
            capex_convention=CapexConvention.NPV,
            carbon_price_by_year={2025: 100.0},
            include_transitions=False,
            include_new_build=False,
        ),
    )
    res = _solve(prob)
    assert res.ok
    # Adopt fully: carbon 0 + capex 40 = 40  (vs 100 if not adopted).
    np.testing.assert_allclose(res.objective, 40.0, rtol=RTOL)
    np.testing.assert_allclose(
        res.context.z.solution.sel(asset="a1", measure="m1", block=0, period=2025).item(),
        1.0,
        atol=1e-6,
    )


def test_macc_measure_rejected_when_capex_exceeds_carbon() -> None:
    """The same block at CAPEX 150 is not worth a 100 USD carbon bill."""
    prob = OptimisationProblem(
        periods=[Period(2025)],
        assets=[
            Asset(
                "a1",
                "g",
                capacity=2e6,
                baseline_technology="k1",
                feasible_technologies=frozenset({"k1"}),
                built_year=2010,
            )
        ],
        technologies=[Technology("k1", specific_energy=1.0, allowed_carriers=frozenset({"r1"}))],
        carriers=[Carrier("r1", price_default=0.0, intensity_default=1.0)],
        demand={("g", 2025): 1.0e6},
        measures=[
            Measure(
                "m1",
                applicable_assets=frozenset({"a1"}),
                blocks=(MaccBlock(abatement=1.0, capex=150.0),),
                lifetime_years=30,
            )
        ],
        options=SolveOptions(
            discount_rate=0.0,
            base_year=2025,
            capex_convention=CapexConvention.NPV,
            carbon_price_by_year={2025: 100.0},
            include_transitions=False,
            include_new_build=False,
        ),
    )
    res = _solve(prob)
    assert res.ok
    np.testing.assert_allclose(res.objective, 100.0, rtol=RTOL)


def test_new_build_to_cover_demand_shortfall() -> None:
    """Existing capacity (5) is short of demand (10); build a candidate to cover it."""
    prob = OptimisationProblem(
        periods=[Period(2025)],
        assets=[
            Asset(
                "a1",
                "g",
                capacity=5.0,
                baseline_technology="k1",
                feasible_technologies=frozenset({"k1"}),
                built_year=2010,
            ),
            Asset(
                "cand",
                "g",
                capacity=100.0,
                size=1.0,
                feasible_technologies=frozenset({"k1"}),
                is_candidate=True,
                build_capex_per_size=20.0,
                build_lifetime_years=30,
                build_lead_years=0,
            ),
        ],
        technologies=[Technology("k1", specific_energy=1.0, allowed_carriers=frozenset({"r1"}))],
        carriers=[Carrier("r1", price_default=1.0, intensity_default=0.0)],
        demand={("g", 2025): 10.0},
        options=SolveOptions(
            discount_rate=0.0,
            base_year=2025,
            capex_convention=CapexConvention.NPV,
            include_transitions=False,
            include_measures=True,
        ),
    )
    res = _solve(prob)
    assert res.ok
    # fuel for 10 units (1 each) + build CAPEX 20 = 30; no demand slack.
    np.testing.assert_allclose(res.objective, 30.0, rtol=RTOL)
    np.testing.assert_allclose(
        res.context.build.solution.sel(asset="cand", period=2025).item(), 1.0, atol=1e-6
    )


def test_overtight_target_uses_slack_not_infeasible() -> None:
    """An impossible cap (only dirty fuel available) yields slack, not infeasibility."""
    prob = OptimisationProblem(
        periods=[Period(2025)],
        assets=[
            Asset(
                "a1",
                "g",
                capacity=100,
                baseline_technology="k1",
                feasible_technologies=frozenset({"k1"}),
                built_year=2010,
            )
        ],
        technologies=[Technology("k1", specific_energy=1.0, allowed_carriers=frozenset({"dirty"}))],
        carriers=[Carrier("dirty", price_default=1.0, intensity_default=100.0)],
        demand={("g", 2025): 10.0},
        targets=[Target("g", TargetType.INTENSITY_CAP, {2025: 0.0})],
        options=SolveOptions(
            discount_rate=0.0,
            base_year=2025,
            slack_penalty=1e6,
            include_transitions=False,
            include_new_build=False,
            include_measures=False,
        ),
    )
    res = _solve(prob)
    assert res.ok  # feasible thanks to slack (not infeasible)
    # An impossible cap is resolved by slack somewhere (target or demand), never
    # by an infeasible model. Total slack used must be strictly positive.
    total_slack = float(res.context.slk_tgt.solution.sum().item()) + float(
        res.context.slk_dem.solution.sum().item()
    )
    assert total_slack > 0.0
