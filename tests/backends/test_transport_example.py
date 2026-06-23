"""The spatial methanol-sourcing example (transport plan, Layer 1a) lands the
cheapest source and reroutes when a carbon price crosses the breakeven.

Guards the headline behaviour: transport-as-process (freight opex + per-tonne
transport CO2 + per-source production background + annual capacity) yields a
min-cost multi-commodity sourcing decision, and a CO2 price flips it from the
cheap-but-dirty coal route (China) to the cleaner US route. Annual resolution.
"""

from __future__ import annotations

from importlib.resources import files

from pathwise.api.workbook_io import parse_sqlite
from pathwise.backends.registry import get_backend

_SCENARIO = {
    "economics": {"base_year": 2025},
    "horizon": {"start": 2025, "end": 2025},
    "optimisation_scope": "system",
    "optimisation_mode": "joint",
    "objective": "cost",
}


def _model() -> dict:
    return parse_sqlite(
        (files("pathwise.assets.examples") / "transport_methanol.sqlite").read_bytes()
    )


def _run(carbon: float) -> tuple[str, dict[str, float], float]:
    wb = {**_model(), "impact_prices": [{"impact_id": "CO2", "year": 2025, "price": carbon}]}
    res = get_backend("linopy").run(wb, _SCENARIO, {})
    tp: dict[str, float] = {}
    for r in res["outputs"].get("throughput", []):
        tp[str(r["technology"])] = tp.get(str(r["technology"]), 0.0) + float(r["value"])
    co2 = sum(float(r["total"]) for r in res["summary"]["impacts"] if r["impact"] == "CO2")
    return res["status"], tp, co2


def _chosen(tp: dict[str, float]) -> str:
    return max(tp, key=lambda k: tp[k]) if tp else ""


def test_zero_carbon_sources_cheapest_landed_china() -> None:
    status, tp, _co2 = _run(0)
    assert status == "optimal"
    # China's coal-route methanol is the cheapest landed (price 360 + freight 20).
    assert _chosen(tp) == "Ship_CN_KR"
    assert tp["Ship_CN_KR"] > 0 and tp.get("Ship_US_KR", 0) == 0


def test_high_carbon_flips_sourcing_to_us() -> None:
    status, tp, _co2 = _run(50)
    assert status == "optimal"
    # The CO2 price penalises China's dirty production → US becomes cheapest landed.
    assert _chosen(tp) == "Ship_US_KR"


def test_carbon_price_cuts_emissions_at_the_flip() -> None:
    """Crossing the breakeven cuts the inventory (coal route → cleaner route)."""
    _, _, co2_lo = _run(0)
    _, _, co2_hi = _run(50)
    assert co2_hi < co2_lo  # rerouting away from the coal route lowers total CO2
