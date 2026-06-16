"""The ``volume`` coupling signal: upstream supply caps downstream purchase.

An upstream stage produces a limited quantity of a shared commodity; a ``volume``
link feeds that produced quantity in as a ceiling on the downstream stage's
external purchase of it. With the ceiling binding, the downstream stage can no
longer buy its way to full demand.
"""

from __future__ import annotations

import pytest

from pathwise.core.valuechain import run_value_chain
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.valuechain import CouplingLink, Stage, ValueChainSpec

SC = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _upstream() -> dict:
    """Makes 50 t of ``mid`` (its own demand) — the volume available downstream."""
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        # ``mid`` is this stage's product (so its demand pulls production); it is
        # a purchasable input in the downstream stage's own commodity sheet.
        "commodities": [{"commodity_id": "mid", "kind": "product", "unit": "t"}],
        "impacts": [],
        "technologies": [{"technology_id": "UPT", "actions": "continue", "opex": 1.0}],
        "processes": [
            {"process_id": "UP", "company": "UpCo", "baseline_technology": "UPT", "capacity": 1000}
        ],
        "io": [
            {
                "technology_id": "UPT",
                "target": "mid",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            }
        ],
        "demand": [{"company": "UpCo", "commodity_id": "mid", "year": 2025, "amount": 50}],
    }


def _downstream() -> dict:
    """Wants 100 t of ``fin``, one ``mid`` per ``fin``; buys ``mid`` at $1."""
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "mid", "kind": "material", "unit": "t", "price": 1.0},
            {"commodity_id": "fin", "kind": "product", "unit": "t"},
        ],
        "impacts": [],
        "technologies": [{"technology_id": "DT", "actions": "continue", "opex": 1.0}],
        "processes": [
            {"process_id": "DN", "company": "DnCo", "baseline_technology": "DT", "capacity": 1000}
        ],
        "io": [
            {"technology_id": "DT", "target": "mid", "role": "input", "coefficient": 1},
            {
                "technology_id": "DT",
                "target": "fin",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "demand": [{"company": "DnCo", "commodity_id": "fin", "year": 2025, "amount": 100}],
    }


def _stages() -> list[Stage]:
    return [Stage(id="up", model="up"), Stage(id="down", model="down")]


def _buy(result: dict, commodity: str) -> float:
    return sum(
        r["value"]
        for r in result["outputs"]["trade"]
        if r["kind"] == "buy" and r["commodity"] == commodity
    )


def test_no_link_lets_downstream_buy_all_it_needs() -> None:
    spec = ValueChainSpec(id="vc", stages=_stages())
    wbs = {"up": _upstream(), "down": _downstream()}
    res = run_value_chain(spec, wbs, SC)
    assert res["status"] == "optimal"
    assert _buy(res["stages"]["down"], "mid") == pytest.approx(100.0, rel=1e-6)
    assert res["stages"]["down"]["outputs"]["demand_slack"] == []


def test_volume_link_caps_downstream_purchase_at_upstream_output() -> None:
    spec = ValueChainSpec(
        id="vc",
        stages=_stages(),
        links=[CouplingLink(from_stage="up", to_stage="down", commodity="mid", signals=["volume"])],
    )
    wbs = {"up": _upstream(), "down": _downstream()}
    res = run_value_chain(spec, wbs, SC)

    # The upstream produced volume (50) is recorded as the transferred signal.
    vol = [c for c in res["couplings"] if c["signal"] == "volume"]
    assert vol and vol[0]["commodity"] == "mid"
    assert vol[0]["by_year"][0]["value"] == pytest.approx(50.0, rel=1e-6)

    # Downstream can now buy at most 50 t of mid → only 50 t of fin, 50 short.
    down = res["stages"]["down"]
    assert _buy(down, "mid") == pytest.approx(50.0, rel=1e-6)
    slack = {s["key"]: s["value"] for s in down["outputs"]["demand_slack"]}
    assert slack.get("DnCo|fin|2025") == pytest.approx(50.0, rel=1e-6)
