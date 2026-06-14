"""Value-chain cascade: an upstream policy reshapes the downstream pathway.

The driving requirement: a carbon policy on an *upstream* stage (electricity)
must raise the price the *downstream* stage (steel) pays for it and change the
steel plant's chosen pathway. Plus unit tests for the lag shift, the price
signal, the injection, and the topological ordering.
"""

from __future__ import annotations

import pytest

from pathwise.core.valuechain import (
    _inject_price,
    _price_signal,
    _shift,
    marginal_price,
    run_value_chain,
    sweep_value_chain,
)
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.valuechain import CouplingLink, Stage, ValueChainSpec

SC = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _electricity_wb(co2_price: float) -> dict:
    """A grid stage: fuel → electricity, with a carbon price (the policy knob).

    Unit cost of electricity = 2 fuel/MWh · 10 + 2 fuel · 0.5 tCO2 · co2_price
    = 20 + co2_price per MWh.
    """
    return {
        "periods": [{"year": 2025, "duration_years": 1}, {"year": 2030, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "fuel", "kind": "energy", "price": 10.0},
            {"commodity_id": "electricity", "kind": "product"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}],
        "impact_prices": [
            {"impact_id": "CO2", "year": 2025, "price": co2_price},
            {"impact_id": "CO2", "year": 2030, "price": co2_price},
        ],
        "commodity_impacts": [{"commodity_id": "fuel", "impact_id": "CO2", "factor": 0.5}],
        "technologies": [{"technology_id": "gen"}],
        "io": [
            {"technology_id": "gen", "target": "fuel", "role": "input", "coefficient": 2},
            {
                "technology_id": "gen",
                "target": "electricity",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "processes": [
            {
                "process_id": "Plant",
                "company": "Grid",
                "baseline_technology": "gen",
                "capacity": 2000,
            }
        ],
        "demand": [
            {"company": "Grid", "commodity_id": "electricity", "year": y, "amount": 1000}
            for y in (2025, 2030)
        ],
    }


def _steel_wb() -> dict:
    """A mill that buys electricity; may switch to a half-electricity tech.

    Arc uses 4 MWh/t; Arc_HR uses 2 MWh/t for a one-off 120/cap switch (=12,000).
    Switching pays once the electricity price exceeds 60/MWh
    (200·price saved > 12,000), so a stiff upstream carbon policy flips it.
    """
    return {
        "periods": [{"year": 2025, "duration_years": 1}, {"year": 2030, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "electricity", "kind": "energy"},
            {"commodity_id": "steel", "kind": "product"},
        ],
        "technologies": [{"technology_id": "Arc"}, {"technology_id": "Arc_HR"}],
        "io": [
            {"technology_id": "Arc", "target": "electricity", "role": "input", "coefficient": 4},
            {
                "technology_id": "Arc",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
            {"technology_id": "Arc_HR", "target": "electricity", "role": "input", "coefficient": 2},
            {
                "technology_id": "Arc_HR",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "transitions": [
            {
                "from_technology": "Arc",
                "to_technology": "Arc_HR",
                "action": "replace",
                "capex_per_capacity": 120.0,
            }
        ],
        "processes": [
            {
                "process_id": "Mill",
                "company": "SteelCo",
                "baseline_technology": "Arc",
                "capacity": 100,
            }
        ],
        "demand": [
            {"company": "SteelCo", "commodity_id": "steel", "year": y, "amount": 100}
            for y in (2025, 2030)
        ],
    }


def _spec(lag: int = 0) -> ValueChainSpec:
    return ValueChainSpec(
        id="vc",
        label="elec → steel",
        stages=[Stage(id="elec"), Stage(id="steel")],
        links=[
            CouplingLink(
                from_stage="elec",
                to_stage="steel",
                commodity="electricity",
                signals=["price"],
                lag_years=lag,
            )
        ],
    )


def _injected(res: dict) -> float:
    return res["couplings"][0]["by_year"][0]["value"]


def _switched(res: dict) -> bool:
    trans = res["stages"]["steel"]["outputs"]["transitions"]
    return any(t["to_technology"] == "Arc_HR" for t in trans)


def test_upstream_carbon_policy_raises_downstream_price_and_flips_pathway() -> None:
    spec = _spec()
    low = run_value_chain(spec, {"elec": _electricity_wb(10.0), "steel": _steel_wb()}, SC)
    high = run_value_chain(spec, {"elec": _electricity_wb(200.0), "steel": _steel_wb()}, SC)

    assert low["status"] == "optimal" and high["status"] == "optimal"
    # Stricter upstream carbon policy ⇒ higher electricity price injected downstream.
    assert _injected(high) > _injected(low)
    assert _injected(low) == pytest.approx(30.0)  # 20 + 10
    assert _injected(high) == pytest.approx(220.0)  # 20 + 200
    # …which flips the steel plant's pathway: it switches to the efficient tech.
    assert not _switched(low), "cheap electricity ⇒ keep the electricity-heavy baseline"
    assert _switched(high), "expensive electricity ⇒ switch to the half-electricity tech"


def test_carbon_intensity_signal_couples_into_downstream_emissions() -> None:
    # Electricity emits 1,000 tCO2 for 1,000 MWh ⇒ CI = 1.0 tCO2/MWh, injected
    # into steel's electricity input so the mill's emissions reflect the grid.
    spec = ValueChainSpec(
        id="vc",
        stages=[Stage(id="elec"), Stage(id="steel")],
        links=[
            CouplingLink(
                from_stage="elec",
                to_stage="steel",
                commodity="electricity",
                signals=["carbon_intensity"],
                impact="CO2",
            )
        ],
    )
    steel = _steel_wb()
    steel["impacts"] = [{"impact_id": "CO2", "unit": "tCO2"}]
    res = run_value_chain(spec, {"elec": _electricity_wb(0.0), "steel": steel}, SC)

    assert res["status"] == "optimal"
    ci = [c for c in res["couplings"] if c["signal"] == "carbon_intensity"]
    assert ci and ci[0]["by_year"][0]["value"] == pytest.approx(1.0)
    # Mill stays on Arc (no carbon price downstream): 4 MWh/t · 100 t · 1.0 = 400 tCO2.
    steel_co2 = {
        r["period"]: r["total"]
        for r in res["stages"]["steel"]["summary"]["impacts"]
        if r["impact"] == "CO2"
    }
    assert steel_co2[2025] == pytest.approx(400.0)


def test_feedback_sizes_upstream_to_downstream_consumption() -> None:
    # The grid starts with a wrong demand guess (10); two-way feedback drives it
    # to the steel mill's actual electricity consumption (4 MWh/t · 100 t = 400).
    elec = _electricity_wb(10.0)
    elec["demand"] = [
        {"company": "Grid", "commodity_id": "electricity", "year": y, "amount": 10.0}
        for y in (2025, 2030)
    ]
    spec = ValueChainSpec(
        id="vc",
        stages=[Stage(id="elec"), Stage(id="steel")],
        links=[
            CouplingLink(
                from_stage="elec",
                to_stage="steel",
                commodity="electricity",
                signals=["price"],
                feedback=True,
            )
        ],
    )
    res = run_value_chain(spec, {"elec": elec, "steel": _steel_wb()}, SC, iterations=6, damping=1.0)

    assert res["status"] == "optimal"
    prod = {
        r["period"]: r["produced"]
        for r in res["stages"]["elec"]["summary"]["commodity"]
        if r["commodity"] == "electricity"
    }
    assert prod[2025] == pytest.approx(400.0, abs=1.0)
    assert res["iterations"] <= 6, "the fixed point should converge well within the cap"


def test_uncertainty_sweep_spreads_downstream_outcomes() -> None:
    # Three upstream carbon-policy draws ⇒ a distribution of downstream steel cost.
    spec = _spec()
    draws = [{"elec": _electricity_wb(c), "steel": _steel_wb()} for c in (0.0, 100.0, 200.0)]
    res = sweep_value_chain(spec, draws, SC)

    assert len(res["runs"]) == 3
    steel_cost = res["distribution"]["steel"]["cost"]
    assert steel_cost["max"] > steel_cost["min"], "upstream uncertainty must spread downstream"
    assert steel_cost["min"] <= steel_cost["mean"] <= steel_cost["max"]


def test_profit_objective_stage_composes_in_cascade() -> None:
    # A downstream profit-maximiser (with a sale price) sells up to its demand.
    steel = _steel_wb()
    steel["company_config"] = [{"company": "SteelCo", "objective": "profit"}]
    for c in steel["commodities"]:
        if c["commodity_id"] == "steel":
            c["sale_price"] = 10000.0
    res = run_value_chain(_spec(), {"elec": _electricity_wb(10.0), "steel": steel}, SC)

    assert res["status"] == "optimal"
    produced = {
        r["period"]: r["produced"]
        for r in res["stages"]["steel"]["summary"]["commodity"]
        if r["commodity"] == "steel"
    }
    assert produced[2025] == pytest.approx(100.0)


def test_marginal_price_equals_known_marginal_cost() -> None:
    # Linear grid: marginal cost = 2 fuel · 10 + 2 fuel · 0.5 · co2 = 20 + co2.
    mp = marginal_price(_electricity_wb(10.0), SC, "electricity")
    assert mp[2025] == pytest.approx(30.0, abs=0.5)
    assert mp[2030] == pytest.approx(30.0, abs=0.5)


def test_marginal_price_signal_couples_downstream() -> None:
    spec = ValueChainSpec(
        id="vc",
        stages=[Stage(id="elec"), Stage(id="steel")],
        links=[
            CouplingLink(
                from_stage="elec",
                to_stage="steel",
                commodity="electricity",
                signals=["marginal_price"],
            )
        ],
    )
    res = run_value_chain(spec, {"elec": _electricity_wb(10.0), "steel": _steel_wb()}, SC)
    mp = [c for c in res["couplings"] if c["signal"] == "marginal_price"]
    assert mp and mp[0]["by_year"][0]["value"] == pytest.approx(30.0, abs=0.5)


def test_lag_shift_offsets_and_holds_flat() -> None:
    # Price known at 2025/2030 upstream; a 5-yr lag pushes it to 2030/2035.
    out = _shift({2025: 10.0, 2030: 20.0}, 5, [2025, 2030, 2035])
    assert out == {2025: 10.0, 2030: 10.0, 2035: 20.0}  # flat-hold before the first shifted point


def test_price_signal_is_cost_over_production() -> None:
    result = {
        "summary": {
            "periods": [{"period": 2025, "cost": 40000.0}],
            "commodity": [{"commodity": "electricity", "period": 2025, "produced": 1000.0}],
        }
    }
    assert _price_signal(result, "electricity") == {2025: 40.0}


def test_inject_price_upserts_without_clobbering_other_columns() -> None:
    wb = {"commodities_t__price": [{"year": 2025, "fuel": 10.0}]}
    _inject_price(wb, "electricity", {2025: 30.0, 2030: 35.0})
    rows = {int(r["year"]): r for r in wb["commodities_t__price"]}
    assert rows[2025] == {"year": 2025, "fuel": 10.0, "electricity": 30.0}
    assert rows[2030] == {"year": 2030, "electricity": 35.0}


def test_topological_order_is_upstream_first() -> None:
    spec = ValueChainSpec(
        id="c",
        stages=[Stage(id="a"), Stage(id="b"), Stage(id="c")],
        links=[
            CouplingLink(from_stage="a", to_stage="b", commodity="x"),
            CouplingLink(from_stage="b", to_stage="c", commodity="y"),
        ],
    )
    order = spec.order()
    assert order.index("a") < order.index("b") < order.index("c")


def test_shipped_asset_loads_runs_and_couples() -> None:
    import json
    from pathlib import Path

    from pathwise.config import get_settings
    from pathwise.data.valuechain import load_value_chain

    vdir = Path(get_settings().value_chains_dir)
    spec = load_value_chain(vdir / "elec_steel.json")
    workbooks = {
        s.id: json.loads((vdir / s.model).read_text(encoding="utf-8")) for s in spec.stages
    }
    res = run_value_chain(spec, workbooks, SC)

    assert res["status"] == "optimal"
    assert res["couplings"], "the electricity price should flow downstream to steel"
    # The shipped chain prices CO2 at 150 ⇒ electricity ~170/MWh ⇒ the mill switches.
    assert any(
        t["to_technology"] == "Arc_HR" for t in res["stages"]["steel"]["outputs"]["transitions"]
    )


def test_cyclic_chain_is_rejected() -> None:
    with pytest.raises(ValueError, match="cycle"):
        ValueChainSpec(
            id="c",
            stages=[Stage(id="a"), Stage(id="b")],
            links=[
                CouplingLink(from_stage="a", to_stage="b", commodity="x"),
                CouplingLink(from_stage="b", to_stage="a", commodity="y"),
            ],
        )
