"""Greedy-MACC backend: cheapest-first deployment of the model's *levers*.

The MACC mode is a solve method over the framework value-chain model — it reads
the model's levers (abatement without a technology change) and an emission cap,
not a bolt-on schema. The expected numbers are hand-computed from the algorithm
in ``pathwise.backends.macc_backend`` (see its module docstring).
"""

from __future__ import annotations

import pytest

from pathwise.backends.macc_backend import MaccBackend
from pathwise.backends.registry import available_backends, get_backend

YEARS = [2025, 2026, 2027, 2028]

#: Emission cap (target) per year — BAU is a flat 100, the cap tightens.
TARGET = {2025: 100, 2026: 90, 2027: 80, 2028: 60}

#: Three abatement levers on the one facility. Each block: reduction (× the
#: facility's 100 tCO2 baseline = potential), capex, opex; lifetime 20.
#: rank = (capex/20 + opex)/potential → cheap 0.5 < mid 1.0 < exp 5.0.
#: book (capex/potential) → cheap 10, mid 20, exp 100.
LEVERS = [
    {"id": "cheap", "reduction": 0.05, "capex": 50, "opex": 0},  # pot 5, rank .5, book 10
    {"id": "mid", "reduction": 0.05, "capex": 100, "opex": 0},  # pot 5, rank 1.0, book 20
    {"id": "exp", "reduction": 0.25, "capex": 2500, "opex": 0},  # pot 25, rank 5.0, book 100
]


def _model() -> dict:
    return {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [{"commodity_id": "widget", "kind": "product", "unit": "t"}],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}],
        "technologies": [{"technology_id": "T", "actions": "continue"}],
        "processes": [
            {"process_id": "F", "company": "C", "baseline_technology": "T", "capacity": 100}
        ],
        "io": [
            {
                "technology_id": "T",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            }
        ],
        # Facility baseline emission = 100 tCO2/yr (capacity 100 × 1.0).
        "process_impacts": [{"process_id": "F", "impact_id": "CO2", "factor": 1.0}],
        "levers": [
            {
                "lever_id": m["id"],
                "type": "emission_reduction",
                "target": "CO2",
                "facility": "F",
                "lifetime": 20,
            }
            for m in LEVERS
        ],
        "lever_blocks": [
            {
                "lever_id": m["id"],
                "block": 0,
                "reduction": m["reduction"],
                "capex": m["capex"],
                "opex": m["opex"],
            }
            for m in LEVERS
        ],
        "impact_caps": [
            {"company": "all", "impact_id": "CO2", "year": y, "limit": v} for y, v in TARGET.items()
        ],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 100} for y in YEARS
        ],
    }


def _run(model: dict) -> dict:
    return MaccBackend().run(model, {"economics": {"base_year": 2025}}, None)


def _by_year(res: dict) -> dict[int, dict]:
    return {r["year"]: r for r in res["outputs"]["macc"]["by_year"]}


def test_macc_backend_is_registered() -> None:
    assert get_backend("macc").name == "macc"
    assert any(b["name"] == "macc" for b in available_backends())


def test_greedy_reproduces_hand_computed_pathway() -> None:
    res = _run(_model())
    assert res["status"] == "optimal", res.get("validation")
    rows = _by_year(res)

    # 2025: cap == BAU, nothing required.
    assert rows[2025]["actual_emissions"] == pytest.approx(100.0)
    assert rows[2025]["cumulative_capex"] == pytest.approx(0.0)

    # 2026: need 10 → cheap(5) + mid(5); capex = 5*10 + 5*20 = 150.
    assert rows[2026]["actual_emissions"] == pytest.approx(90.0)
    assert rows[2026]["cumulative_capex"] == pytest.approx(150.0)

    # 2027: need 20, 10 deployed → exp(+10); capex += 10*100 → 1150.
    assert rows[2027]["actual_emissions"] == pytest.approx(80.0)
    assert rows[2027]["cumulative_capex"] == pytest.approx(1150.0)

    # 2028: need 40, 20 deployed → exp grows by min(20, 25-10)=15 → total 35.
    # Residual sits ABOVE target (65 > 60): shortfall 5. capex += 15*100.
    assert rows[2028]["abated"] == pytest.approx(35.0)
    assert rows[2028]["actual_emissions"] == pytest.approx(65.0)
    assert rows[2028]["shortfall"] == pytest.approx(5.0)
    assert rows[2028]["cumulative_capex"] == pytest.approx(2650.0)

    assert res["objective"] == pytest.approx(2650.0)
    assert res["summary"]["impacts"][-1]["total"] == pytest.approx(65.0)


def test_no_levers_is_invalid() -> None:
    model = _model()
    model["levers"] = []
    model["lever_blocks"] = []
    res = _run(model)
    assert res["status"] == "invalid"
    assert any("lever" in e.lower() for e in res["validation"]["errors"])


def test_no_cap_is_invalid() -> None:
    model = _model()
    model["impact_caps"] = []
    res = _run(model)
    assert res["status"] == "invalid"
    assert any("cap" in e.lower() for e in res["validation"]["errors"])
