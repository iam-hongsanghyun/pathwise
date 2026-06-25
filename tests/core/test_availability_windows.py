"""Availability windows: streams, technologies, facilities, markets."""

from __future__ import annotations

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _solve(wb: dict) -> dict:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    res = extract_results(solve(build(assemble_problem(wb, sc))))
    assert res["status"] == "optimal"
    return res


def _base() -> dict:
    """One facility; OLD burns coal, NEW burns gas; demand every period."""
    return {
        "periods": [{"year": 2025}, {"year": 2030}, {"year": 2035}],
        "flows": [
            {"flow_id": "coal", "kind": "energy", "price": 10.0},
            {"flow_id": "gas", "kind": "energy", "price": 30.0},
            {"flow_id": "widget", "kind": "product"},
        ],
        "technologies": [{"technology_id": "OLD"}, {"technology_id": "NEW"}],
        "io": [
            {"technology_id": "OLD", "target": "coal", "role": "input", "coefficient": 1},
            {
                "technology_id": "OLD",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
            {"technology_id": "NEW", "target": "gas", "role": "input", "coefficient": 1},
            {
                "technology_id": "NEW",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "OLD", "capacity": 100}
        ],
        "transitions": [{"from_technology": "OLD", "to_technology": "NEW", "action": "replace"}],
        "demand": [
            {"company": "C", "flow_id": "widget", "year": y, "amount": 50}
            for y in (2025, 2030, 2035)
        ],
        "impacts": [],
        "markets": [],
        "storage": [],
    }


def _active(res: dict) -> dict[int, str]:
    return {r["period"]: r["technology"] for r in res["outputs"]["technology"]}


def test_technology_phase_out_forces_transition() -> None:
    # phase_out_year is EXCLUSIVE: OLD is unusable FROM 2030, so the switch to
    # NEW must already be in place in 2030 even though NEW costs 3x.
    wb = _base()
    wb["technologies"][0]["phase_out_year"] = 2030
    active = _active(_solve(wb))
    assert active[2025] == "OLD"
    assert active[2030] == "NEW" and active[2035] == "NEW"


def test_stream_window_blocks_purchase() -> None:
    # Coal may not be BOUGHT after 2030 — same effect as the tech ban here,
    # driven from the stream side ("available until").
    wb = _base()
    wb["flows"][0]["available_to"] = 2030
    res = _solve(wb)
    coal_2035 = [
        t
        for t in res["outputs"]["trade"]
        if t["flow"] == "coal" and t["period"] == 2035 and t["kind"] == "buy"
    ]
    assert not coal_2035, "no coal purchases after its availability window"
    assert _active(res)[2035] == "NEW"


def test_stream_available_from_delays_use() -> None:
    # Gas only purchasable from 2035: even if NEW were attractive earlier, it
    # cannot run before its fuel exists. Make NEW cheap to tempt the optimiser.
    wb = _base()
    wb["flows"][1]["price"] = 1.0
    wb["flows"][1]["available_from"] = 2035
    res = _solve(wb)
    active = _active(res)
    assert active[2030] == "OLD", "gas not yet available in 2030"
    assert active[2035] == "NEW"


def test_facility_decommission_switches_off() -> None:
    wb = _base()
    wb["processes"][0]["decommission_year"] = 2030
    res = _solve(wb)
    active = _active(res)
    # decommission_year (close year) is EXCLUSIVE: runs up to 2029, off FROM 2030.
    assert 2025 in active
    assert 2030 not in active and 2035 not in active, "off from the close year"
    assert any("2030" in s["key"] for s in res["outputs"]["demand_slack"]), (
        "demand from the close year goes unmet (slack) once the facility is gone"
    )


def test_facility_build_year_delays_online() -> None:
    # build_year (introduced_year) is the online-from year: the asset is OFF
    # before it, so early demand can only be met by slack.
    wb = _base()
    wb["processes"][0]["introduced_year"] = 2030
    res = _solve(wb)
    active = _active(res)
    assert 2025 not in active, "asset not built yet in 2025"
    assert 2030 in active and 2035 in active
    assert any("2025" in s["key"] for s in res["outputs"]["demand_slack"])


def test_market_window() -> None:
    # A cheap coal market that only opens in 2035 — before that, coal is bought
    # at the flow price; after, via the market.
    wb = _base()
    wb["markets"] = [
        {"market_id": "coal_mkt", "target": "coal", "price": 2.0, "available_from": 2035}
    ]
    res = _solve(wb)
    buys = {m["market"]: m["by_period"] for m in res["outputs"]["markets"]}
    rows = {b["period"]: b["buy"] for b in buys.get("coal_mkt", [])}
    assert rows.get(2025, 0) == 0 and rows.get(2030, 0) == 0
    assert rows.get(2035, 0) > 0, "market used once its window opens"
