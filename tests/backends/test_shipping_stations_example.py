"""The shipping-with-stations example: candidate fleets + refuelling infrastructure.

A Busan→Sydney cargo lane is carried by a carrier that owns an HFO ship (cheap
bunker, high impact) and an e-ammonia ship (pricier fuel, zero impact); a Busan
bunkering STATION dispenses the bunker, capacity-limited + with a per-unit fee. With
no carbon price the HFO ship wins and refuels at the station; a carbon price on the
fuel's impact flips the optimiser to the e-ammonia ship.
"""

from __future__ import annotations

import json
from importlib.resources import files

from pathwise.backends.registry import get_backend

_SCENARIO = {
    "economics": {"base_year": 2025},
    "horizon": {"start": 2025, "end": 2025},
    "optimisation_scope": "system",
    "optimisation_mode": "joint",
    "objective": "cost",
}


def _model() -> dict:
    return json.loads((files("pathwise.assets.examples") / "shipping_stations.json").read_text())


def _run(carbon: float = 0.0) -> tuple[dict, dict[str, float]]:
    wb = _model()
    if carbon:
        wb = {**wb, "impact_prices": [{"impact_id": "ghg", "year": 2025, "price": carbon}]}
    res = get_backend("linopy").run(wb, _SCENARIO, {})
    ships = {
        str(r["fleet"]): float(r["ships"])
        for r in res["outputs"].get("fleet", [])
        if r.get("process") == "rt" and float(r["ships"]) > 0
    }
    return res, ships


def _delivered(res: dict) -> float:
    return sum(
        float(r["value"])
        for r in res["outputs"].get("throughput", [])
        if r.get("process") == "chain/au/term"
    )


def test_example_loads_and_solves() -> None:
    res, ships = _run(0.0)
    assert res["status"] == "optimal"
    assert abs(_delivered(res) - 1000.0) < 1e-3  # demand met
    assert ships  # a fleet runs the lane


def test_no_carbon_uses_the_hfo_ship_and_refuels() -> None:
    # Cheap bunker (+ the station fee) still beats e-ammonia ⇒ the HFO ship wins.
    _res, ships = _run(0.0)
    assert "hfo_ship" in ships and "nh3_ship" not in ships


def test_carbon_price_flips_to_the_ammonia_ship() -> None:
    # A carbon price on the fuel's impact overtakes the bunker savings ⇒ switch to
    # the zero-impact e-ammonia ship (which doesn't draw on the bunker station).
    _res, ships = _run(150.0)
    assert "nh3_ship" in ships and "hfo_ship" not in ships
