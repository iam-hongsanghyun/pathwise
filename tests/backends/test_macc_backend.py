"""Greedy-MACC backend: cheapest-first deployment against an emission target.

The expected numbers below are hand-computed from the algorithm in
``pathwise.backends.macc_backend`` (see its module docstring), so this is a
true regression test of the greedy mechanics — ordering, carry-forward,
potential caps, CAPEX booking and the above-target residual — independent of
any one sector's data.
"""

from __future__ import annotations

import pytest

from pathwise.backends.macc_backend import MaccBackend
from pathwise.backends.registry import available_backends, get_backend

YEARS = [2025, 2026, 2027, 2028]

#: (bau, target) per year. BAU is flat 100; the target tightens each year.
TARGETS = {2025: (100, 100), 2026: (100, 90), 2027: (100, 80), 2028: (100, 60)}

#: Three options, deliberately ordered cheap < mid < exp so the greedy visits
#: them in that order. cheap/mid saturate at 5 each; exp caps at 25.
OPTIONS = {
    "cheap": {"cost": 1.0, "potential": 5.0, "capex": 10.0},
    "mid": {"cost": 2.0, "potential": 5.0, "capex": 20.0},
    "exp": {"cost": 3.0, "potential": 25.0, "capex": 100.0},
}


def _model(available_from: dict[str, int] | None = None) -> dict:
    curve = [
        {
            "option_id": k,
            "year": y,
            "potential": v["potential"],
            "cost": v["cost"],
            "capex": v["capex"],
        }
        for y in YEARS
        for k, v in OPTIONS.items()
    ]
    target = [{"year": y, "bau": b, "target": t} for y, (b, t) in TARGETS.items()]
    opts = [
        {"option_id": k, "label": k.title(), "available_from": (available_from or {}).get(k)}
        for k in OPTIONS
    ]
    return {"macc_target": target, "macc_curve": curve, "macc_options": opts}


def _run(model: dict) -> dict:
    return MaccBackend().run(model, {}, None)


def _by_year(res: dict) -> dict[int, dict]:
    return {r["year"]: r for r in res["outputs"]["macc"]["by_year"]}


def test_macc_backend_is_registered() -> None:
    assert get_backend("macc").name == "macc"
    assert any(b["name"] == "macc" for b in available_backends())


def test_greedy_reproduces_hand_computed_pathway() -> None:
    res = _run(_model())
    assert res["status"] == "optimal"
    rows = _by_year(res)

    # 2025: target == BAU, nothing required.
    assert rows[2025]["actual_emissions"] == pytest.approx(100.0)
    assert rows[2025]["cumulative_capex"] == pytest.approx(0.0)

    # 2026: need 10 → cheap(5) + mid(5); capex = 5*10 + 5*20 = 150.
    assert rows[2026]["actual_emissions"] == pytest.approx(90.0)
    assert rows[2026]["cumulative_capex"] == pytest.approx(150.0)
    assert rows[2026]["deployed"] == {"cheap": pytest.approx(5.0), "mid": pytest.approx(5.0)}

    # 2027: need 20, 10 already deployed → exp(+10); capex += 10*100 → 1150.
    assert rows[2027]["actual_emissions"] == pytest.approx(80.0)
    assert rows[2027]["cumulative_capex"] == pytest.approx(1150.0)

    # 2028: need 40, 20 deployed → exp grows by min(20, 25-10)=15 → total 35.
    # Residual sits ABOVE target (65 > 60): a shortfall of 5. capex += 15*100.
    assert rows[2028]["abated"] == pytest.approx(35.0)
    assert rows[2028]["actual_emissions"] == pytest.approx(65.0)
    assert rows[2028]["shortfall"] == pytest.approx(5.0)
    assert rows[2028]["cumulative_capex"] == pytest.approx(2650.0)

    # objective = final-year cumulative CAPEX; residual emission path surfaced.
    assert res["objective"] == pytest.approx(2650.0)
    assert res["summary"]["impacts"][-1]["total"] == pytest.approx(65.0)


def test_availability_gate_delays_an_option() -> None:
    # Lock the cheapest option out until 2027: in 2026 the greedy must fall back
    # to mid+exp to find its 10 units of abatement.
    res = _run(_model(available_from={"cheap": 2027}))
    rows = _by_year(res)
    # 2026 need 10: mid(5) + exp(5); capex = 5*20 + 5*100 = 600.
    assert rows[2026]["deployed"].get("cheap", 0.0) == pytest.approx(0.0)
    assert rows[2026]["cumulative_capex"] == pytest.approx(600.0)
    assert rows[2026]["actual_emissions"] == pytest.approx(90.0)


def test_missing_sheets_yield_invalid() -> None:
    res = MaccBackend().run({"macc_target": [{"year": 2025, "bau": 1, "target": 1}]}, {}, None)
    assert res["status"] == "invalid"
    assert res["validation"]["errors"]
