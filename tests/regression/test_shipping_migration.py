"""Integration gate: migrate the real legacy workbook and solve on real data.

This is the acceptance test that the new engine runs end-to-end on the existing
shipping dataset. It does not assert bit-parity with the legacy Pyomo model
(the formulations differ deliberately — discounted CAPEX, per-asset balance with
slack instead of fleet aggregation, externalised carbon pricing); it asserts the
migrated data builds a feasible, sensible model.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pathwise.backends import get_backend
from pathwise.data.workbook import Workbook

_REFERENCE = Path("/Users/sanghyun/github/shipping_optimiser/data/Reference.xlsx")
_OPERATOR = "KSS Line"

pytestmark = pytest.mark.skipif(
    not _REFERENCE.exists(), reason="legacy Reference.xlsx not available"
)


def _migrate() -> Workbook:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    from migrate_shipping_to_generic import migrate

    return migrate(_REFERENCE)


def _filter_operator(wb: Workbook, operator: str) -> Workbook:
    """Return a copy of ``wb`` restricted to a single operator (assets + targets)."""
    out = dict(wb)
    out["assets"] = [a for a in wb["assets"] if a["group"] == operator]
    out["targets"] = [t for t in wb.get("targets", []) if t["group"] == operator]
    return out


def test_migration_produces_required_sheets() -> None:
    wb = _migrate()
    for sheet in (
        "assets",
        "technologies",
        "carriers",
        "carrier_compatibility",
        "periods",
        "targets",
    ):
        assert wb.get(sheet), f"missing/empty {sheet}"


def test_solve_real_operator_subset_is_feasible() -> None:
    wb = _filter_operator(_migrate(), _OPERATOR)
    assert wb["assets"], f"no ships for {_OPERATOR}"

    scenario = {
        "name": "tier1-kss",
        "domain": "shipping",
        "selection": {"target_set": "Tier1"},
        "economics": {"discount_rate": 0.08, "base_period": 2025, "capex_convention": "annuity"},
        "horizon": {"start": 2025, "end": 2030},
        "solver": {"time_limit_s": 120, "mip_gap": 0.01},
    }
    result = get_backend("linopy").run(wb, scenario, {"domain": "shipping"})

    assert result["status"] == "optimal", result.get("termination")
    assert result["objective"] is not None and result["objective"] >= 0.0

    periods = {p["period"] for p in result["summary"]["periods"]}
    assert periods == {2025, 2026, 2027, 2028, 2029, 2030}
    # Every modelled ship is assigned a technology in the base year.
    base = [c for c in result["outputs"]["chosen_technology"] if c["period"] == 2025]
    assert len(base) == len(wb["assets"])
