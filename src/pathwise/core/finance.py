"""Discounting and capital-cost annualisation helpers.

Pure numerical functions (no solver objects) so they can be unit-tested in
isolation against closed-form values.
"""

from __future__ import annotations


def discount_factor(year: int, base_year: int, discount_rate: float) -> float:
    r"""Present-value discount factor for a cash flow in ``year``.

    Algorithm:
        $$ DF_t = (1 + \rho)^{-(t - t_0)} $$

        ASCII::

            DF_t = (1 + rho) ** -(year - base_year)

    Args:
        year: Year of the cash flow.
        base_year: Reference year ``t0`` where ``DF = 1``.
        discount_rate: Discount rate ``ρ`` [1/yr], ``ρ ≥ 0``.

    Returns:
        The dimensionless discount factor in ``(0, 1]`` for ``year ≥ base_year``.
    """
    return (1.0 + discount_rate) ** (-(year - base_year))


def capital_recovery_factor(discount_rate: float, lifetime_years: int) -> float:
    r"""Annuity factor converting a lump-sum CAPEX into a level yearly payment.

    Algorithm:
        $$ CRF = \frac{\rho\,(1+\rho)^{L}}{(1+\rho)^{L} - 1} $$

        ASCII::

            CRF = rho * (1+rho)**L / ((1+rho)**L - 1)

        As ``ρ → 0`` this tends to ``1 / L`` (straight-line amortisation), which
        is returned exactly for ``ρ = 0`` to avoid a 0/0.

    Args:
        discount_rate: Discount rate ``ρ`` [1/yr], ``ρ ≥ 0``.
        lifetime_years: Economic lifetime ``L`` [yr], ``L ≥ 1``.

    Returns:
        The capital recovery factor [1/yr].

    Raises:
        ValueError: If ``lifetime_years < 1``.
    """
    if lifetime_years < 1:
        raise ValueError(f"lifetime_years must be >= 1, got {lifetime_years}")
    if discount_rate == 0.0:
        return 1.0 / lifetime_years
    growth = (1.0 + discount_rate) ** lifetime_years
    return discount_rate * growth / (growth - 1.0)
