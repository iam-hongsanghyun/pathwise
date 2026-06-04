"""Closed-form checks for discounting and capital-recovery helpers."""

from __future__ import annotations

import numpy as np
import pytest

from pathwise.core.finance import capital_recovery_factor, discount_factor


def test_discount_factor_base_year_is_one() -> None:
    assert discount_factor(2025, 2025, 0.08) == 1.0


def test_discount_factor_matches_formula() -> None:
    np.testing.assert_allclose(discount_factor(2030, 2025, 0.08), 1.08**-5, rtol=1e-12)


def test_crf_zero_rate_is_straight_line() -> None:
    # As rho -> 0, CRF -> 1/L.
    np.testing.assert_allclose(capital_recovery_factor(0.0, 20), 1.0 / 20, rtol=1e-12)


def test_crf_matches_textbook_value() -> None:
    # 8% over 20 years: standard annuity factor ~0.101852.
    np.testing.assert_allclose(capital_recovery_factor(0.08, 20), 0.10185221, rtol=1e-6)


def test_crf_rejects_nonpositive_lifetime() -> None:
    with pytest.raises(ValueError):
        capital_recovery_factor(0.08, 0)
