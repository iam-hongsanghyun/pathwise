"""Tests for the data layer: trajectories, workbook IO, scenario, validation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pathwise.data import (
    ScenarioConfig,
    ValidationReport,
    check_foreign_key,
    check_shares_sum_to_one,
    frames_to_workbook,
    impute_by_group_ratio,
    interpolate,
    read_workbook,
    workbook_to_frames,
    write_workbook,
)


# ── Trajectory interpolation ──────────────────────────────────────────────────
def test_interpolate_linear_between_points() -> None:
    out = interpolate({2020: 0.0, 2030: 100.0}, range(2020, 2031))
    np.testing.assert_allclose(out[2025], 50.0)
    np.testing.assert_allclose(out[2021], 10.0)


def test_interpolate_flat_extrapolation() -> None:
    out = interpolate({2025: 7.0}, [2023, 2025, 2040])
    assert out[2023] == 7.0 and out[2040] == 7.0


def test_interpolate_requires_points() -> None:
    with pytest.raises(ValueError):
        interpolate({}, [2025])


# ── Workbook round-trip ───────────────────────────────────────────────────────
def test_workbook_roundtrip(tmp_path) -> None:
    wb = {
        "assets": [{"asset_id": "a1", "capacity": 100.0}, {"asset_id": "a2", "capacity": 50.0}],
        "carriers": [{"carrier_id": "r1", "price": 1.5}],
    }
    path = tmp_path / "wb.xlsx"
    write_workbook(wb, path)
    loaded = read_workbook(path)
    assert set(loaded) == {"assets", "carriers"}
    assert loaded["assets"][0]["asset_id"] == "a1"
    np.testing.assert_allclose(loaded["assets"][1]["capacity"], 50.0)


def test_frames_workbook_conversion_normalises_nan() -> None:
    df = pd.DataFrame({"id": ["a", "b"], "val": [1.0, np.nan]})
    wb = frames_to_workbook({"t": df})
    assert wb["t"][1]["val"] is None
    frames = workbook_to_frames(wb)
    assert list(frames["t"]["id"]) == ["a", "b"]


# ── Scenario config ───────────────────────────────────────────────────────────
def test_scenario_defaults_and_validation() -> None:
    sc = ScenarioConfig.from_dict({"name": "t1", "domain": "shipping"})
    assert sc.economics.discount_rate == 0.08
    assert sc.solver.name == "highs"
    assert sc.features.include_measures is True


def test_scenario_rejects_bad_discount_rate() -> None:
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict({"economics": {"discount_rate": 1.5}})


# ── Validation helpers ────────────────────────────────────────────────────────
def test_foreign_key_and_shares_checks() -> None:
    report = ValidationReport()
    assets = pd.DataFrame({"asset_id": ["a1"], "technology_id": ["k_missing"]})
    check_foreign_key(assets, "technology_id", {"k1", "k2"}, "assets", report)
    assert not report.ok
    assert any("k_missing" in e for e in report.errors)

    mix = pd.DataFrame(
        {"technology_id": ["k1", "k1", "k2"], "share": [0.5, 0.4, 1.0]}
    )  # k1 sums to 0.9
    report2 = ValidationReport()
    check_shares_sum_to_one(mix, "technology_id", "share", "baseline_mix", report2)
    assert not report2.ok
    assert any("k1" in e for e in report2.errors)


# ── Imputation ────────────────────────────────────────────────────────────────
def test_impute_by_group_ratio_fills_missing() -> None:
    df = pd.DataFrame(
        {
            "asset_type": ["bulk", "bulk", "tank"],
            "activity": [10.0, 20.0, 5.0],
            "intensity": [100.0, 200.0, np.nan],  # tank row missing
        }
    )
    # tank has no complete row ⇒ overall median ratio = median(100/10, 200/20) = 10.
    filled, imputed = impute_by_group_ratio(df, "intensity", "activity", "asset_type")
    assert len(imputed) == 1
    np.testing.assert_allclose(filled.loc[2, "intensity"], 10.0 * 5.0)
