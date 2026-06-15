"""The cross-border green-steel example solves and exercises the value chain.

Guards the shipped ``green_steel_chain.sqlite``: it must build, solve at both
``system`` and ``value_chain`` scope, meet demand, draw hydrogen from all three
producing geographies (the cross-border chain), and fire the iron-making
transition — i.e. the facility-transition + MACC + value-chain machinery all work
together on a non-trivial multi-geography model.
"""

from __future__ import annotations

from importlib.resources import files

from pathwise.api.workbook_io import parse_sqlite
from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig

_WB = parse_sqlite((files("pathwise.assets.examples") / "green_steel_chain.sqlite").read_bytes())


def _scenario(scope: str, mode: str | None = None) -> ScenarioConfig:
    cfg = {"economics": {"base_year": 2025}, "optimisation_scope": scope}
    if mode:
        cfg["optimisation_mode"] = mode
    return ScenarioConfig.from_dict(cfg)


def test_solves_system_and_meets_demand() -> None:
    res = run_model(_WB, _scenario("system"))
    assert res["status"] == "optimal"
    assert not res["outputs"]["demand_slack"], "all car/ship demand must be met"


def test_solves_value_chain_scope() -> None:
    res = run_model(_WB, _scenario("value_chain", "valuechain"))
    assert res["status"] == "optimal"


def test_cross_border_hydrogen_and_transition() -> None:
    res = run_model(_WB, _scenario("system"))
    out = res["outputs"]
    # hydrogen reaches Korean steel from all three producing geographies
    origins = {
        f["from"].split("/")[1]
        for f in out["flows"]
        if f["commodity"] == "hydrogen" and f["value"] > 1.0
    }
    assert {"australia", "qatar", "korea"} <= origins, origins
    # the mill transitions its iron-making (blast furnace → H2 direct reduction)
    assert any(t["to_technology"] == "H2_DRI" for t in out["transitions"])
    # MACC measures are adopted somewhere in the chain
    assert any(float(m.get("adoption", 0) or 0) > 1e-6 for m in out["measures"])
