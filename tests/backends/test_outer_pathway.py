"""End-to-end bilevel runs: outer pathway search over the inner solve."""

from __future__ import annotations

import copy

import numpy as np

from pathwise.backends import get_backend
from tests.domains.shipping.test_shipping_pack import _shipping_workbook

# At the upper-bound (Tier1) pathway the inner solve costs 10300 (see
# test_shipping_pack); with no carbon price the cost is monotone in the cap, so
# the cost-optimal pathway sits at the upper bound and the bilevel run must
# reproduce the single-level Tier1 objective.
_SINGLE_LEVEL_TIER1 = 10300.0


def _scenario(outer: dict | None = None) -> dict:
    sc: dict = {
        "name": "tier1",
        "domain": "shipping",
        "selection": {"target_set": "Tier1"},
        "economics": {"discount_rate": 0.0, "base_period": 2025, "capex_convention": "npv"},
    }
    if outer is not None:
        sc["outer"] = outer
    return sc


def _two_group_workbook() -> dict:
    wb = copy.deepcopy(_shipping_workbook())
    wb["assets"].append(
        {
            "asset_id": "ship2",
            "group": "OpB",
            "capacity": 1e9,
            "size": 1000,
            "technology_id": "HFO",
            "built_year": 2010,
            "activity": 100.0,
        }
    )
    wb["targets"].extend(
        [
            {
                "target_set": "Tier1",
                "group": "OpB",
                "target_type": "intensity_cap",
                "year": 2025,
                "limit": 90.0,
            },
            {
                "target_set": "Tier1",
                "group": "OpB",
                "target_type": "intensity_cap",
                "year": 2030,
                "limit": 50.0,
            },
        ]
    )
    return wb


def test_bilevel_sweep_matches_single_level_at_upper_bound() -> None:
    backend = get_backend("linopy")
    result = backend.run(
        _shipping_workbook(),
        _scenario({"enabled": True, "method": "sweep", "sweep_steps": 6}),
        {"domain": "shipping"},
    )

    assert result["status"] == "optimal"
    ps = result["pathway_search"]
    assert ps["enabled"] and ps["method"] == "sweep"
    assert len(ps["frontier"]) == 6
    assert ps["evaluations"] == 6

    # Cheapest rung is the loosest cap (Tier1) ⇒ pathway == upper bounds.
    limits = {p["year"]: p["limit"] for p in ps["pathway"]}
    assert limits == {2025: 90.0, 2030: 50.0}
    np.testing.assert_allclose(ps["objective"], _SINGLE_LEVEL_TIER1, rtol=1e-6)
    np.testing.assert_allclose(result["objective"], _SINGLE_LEVEL_TIER1, rtol=1e-6)

    # Every candidate stays within [floor, upper].
    for p in ps["pathway"]:
        y = p["year"]
        floor = {b["year"]: b["limit"] for b in ps["bounds"]["floor"]}[y]
        upper = {b["year"]: b["limit"] for b in ps["bounds"]["upper"]}[y]
        assert floor <= p["limit"] <= upper


def test_bilevel_anneal_runs_and_is_optimal() -> None:
    result = get_backend("linopy").run(
        _shipping_workbook(),
        _scenario({"enabled": True, "method": "anneal", "max_iterations": 15, "seed": 1}),
        {},
    )
    assert result["status"] == "optimal"
    assert result["pathway_search"]["method"] == "anneal"
    assert result["pathway_search"]["evaluations"] > 0
    # The upper bound is optimal, so SA cannot beat the single-level cost.
    np.testing.assert_allclose(result["objective"], _SINGLE_LEVEL_TIER1, rtol=1e-6)


def test_bilevel_broadcasts_pathway_to_all_groups() -> None:
    result = get_backend("linopy").run(
        _two_group_workbook(),
        _scenario({"enabled": True, "method": "sweep", "sweep_steps": 4}),
        {},
    )
    assert result["status"] == "optimal"
    assert result["pathway_search"]["groups"] == ["OpA", "OpB"]


def test_disabled_outer_matches_single_level_and_omits_block() -> None:
    backend = get_backend("linopy")
    single = backend.run(_shipping_workbook(), _scenario(), {})
    explicit_off = backend.run(_shipping_workbook(), _scenario({"enabled": False}), {})

    assert "pathway_search" not in single
    assert "pathway_search" not in explicit_off
    np.testing.assert_allclose(single["objective"], _SINGLE_LEVEL_TIER1, rtol=1e-6)
    np.testing.assert_allclose(explicit_off["objective"], single["objective"], rtol=1e-12)


def test_bilevel_aborts_cleanly_without_target_set() -> None:
    # No targets at all ⇒ outer search cannot derive an upper bound.
    wb = copy.deepcopy(_shipping_workbook())
    wb["targets"] = []
    result = get_backend("linopy").run(wb, _scenario({"enabled": True, "method": "sweep"}), {})
    assert result["status"] == "invalid"
    assert any("upper bound" in e for e in result["validation"]["errors"])
