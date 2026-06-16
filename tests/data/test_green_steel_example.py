"""The cross-border green-steel example solves and exercises the value chain.

Guards the shipped ``green_steel_chain.sqlite``: it must build, solve at both
``system`` and ``value_chain`` scope, meet demand, draw hydrogen from all three
producing geographies (the cross-border chain), and fire the iron-making
transition — i.e. the facility-transition + MACC + value-chain machinery all work
together on a non-trivial multi-geography model.

These are by far the heaviest solves in the suite, so: the (identical) system
solve is computed once and shared via a module fixture, and a coarser MIP gap is
used — the assertions are all qualitative (status / demand met / which flows and
transitions appear), so closing the last fraction of a percent of the gap only
burns time.
"""

from __future__ import annotations

from importlib.resources import files

import pytest

from pathwise.api.workbook_io import parse_sqlite
from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig

_WB = parse_sqlite((files("pathwise.assets.examples") / "green_steel_chain.sqlite").read_bytes())

# The whole module is heavy (a large multi-geography MILP); skip in fast runs
# with `-m "not slow"`. CI still runs it.
pytestmark = pytest.mark.slow

# Qualitative assertions don't need a tight optimality gap; a coarser one keeps
# the big multi-geography MILP fast.
_GAP = 0.05


def _scenario(scope: str, mode: str | None = None) -> ScenarioConfig:
    cfg: dict = {
        "economics": {"base_year": 2025},
        "optimisation_scope": scope,
        "solver": {"mip_gap": _GAP},
    }
    if mode:
        cfg["optimisation_mode"] = mode
    return ScenarioConfig.from_dict(cfg)


@pytest.fixture(scope="module")
def system_result() -> dict:
    """The system-scope joint solve — shared by the tests that read it."""
    return run_model(_WB, _scenario("system"))


def test_solves_system_and_meets_demand(system_result: dict) -> None:
    assert system_result["status"] == "optimal"
    assert not system_result["outputs"]["demand_slack"], "all car/ship demand must be met"


def test_solves_value_chain_scope() -> None:
    res = run_model(_WB, _scenario("value_chain", "valuechain"))
    assert res["status"] == "optimal"


def test_cross_border_hydrogen_and_transition(system_result: dict) -> None:
    out = system_result["outputs"]
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
