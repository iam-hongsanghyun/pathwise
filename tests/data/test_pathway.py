"""Workbook pathway transforms: groups, upper bounds, broadcast rewrite."""

from __future__ import annotations

import numpy as np
import pytest

from pathwise.data.pathway import (
    apply_pathway,
    clamp_pathway,
    derive_upper_bounds,
    sector_groups,
)


def _workbook() -> dict:
    return {
        "assets": [
            {"asset_id": "s1", "group": "OpB"},
            {"asset_id": "s2", "group": "OpA"},
            {"asset_id": "s3", "group": "OpA"},
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
                "group": "OpB",
                "target_type": "intensity_cap",
                "year": 2025,
                "limit": 80.0,
            },
            {
                "target_set": "Tier1",
                "group": "OpA",
                "target_type": "intensity_cap",
                "year": 2035,
                "limit": 40.0,
            },
            # An absolute cap and a different set must survive untouched.
            {
                "target_set": "Tier1",
                "group": "OpA",
                "target_type": "absolute_cap",
                "year": 2030,
                "limit": 1000.0,
            },
            {
                "target_set": "Tier2",
                "group": "OpA",
                "target_type": "intensity_cap",
                "year": 2025,
                "limit": 70.0,
            },
        ],
    }


def test_sector_groups_sorted_unique() -> None:
    assert sector_groups(_workbook()) == ["OpA", "OpB"]


def test_derive_upper_bounds_takes_per_year_max_and_interpolates() -> None:
    years = [2025, 2030, 2035]
    upper = derive_upper_bounds(_workbook(), "Tier1", years)
    assert upper[2025] == 90.0  # max(90, 80)
    assert upper[2035] == 40.0
    np.testing.assert_allclose(upper[2030], 65.0)  # linear midpoint of 90 → 40


def test_derive_upper_bounds_raises_without_intensity_targets() -> None:
    with pytest.raises(ValueError, match="no intensity-cap targets"):
        derive_upper_bounds({"targets": []}, "Tier1", [2025])


def test_apply_pathway_broadcasts_and_preserves_other_rows() -> None:
    wb = _workbook()
    original_len = len(wb["targets"])
    out = apply_pathway(wb, "Tier1", ["OpA", "OpB"], {2025: 50.0, 2035: 20.0})

    # Input is not mutated.
    assert len(wb["targets"]) == original_len

    rows = out["targets"]
    tier1_intensity = [
        r for r in rows if r["target_set"] == "Tier1" and r["target_type"] == "intensity_cap"
    ]
    # One row per (group, year): 2 groups × 2 years.
    assert len(tier1_intensity) == 4
    assert {(r["group"], r["year"], r["limit"]) for r in tier1_intensity} == {
        ("OpA", 2025, 50.0),
        ("OpA", 2035, 20.0),
        ("OpB", 2025, 50.0),
        ("OpB", 2035, 20.0),
    }
    # Absolute cap and the Tier2 set are preserved.
    assert any(r["target_type"] == "absolute_cap" for r in rows)
    assert any(r["target_set"] == "Tier2" for r in rows)


def test_clamp_pathway() -> None:
    assert clamp_pathway([5.0, 15.0, -2.0], floor=[0.0, 0.0, 0.0], upper=[10.0, 10.0, 10.0]) == [
        5.0,
        10.0,
        0.0,
    ]
