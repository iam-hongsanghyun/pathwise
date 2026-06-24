"""Layer 1c: a fleet burns fuel ∝ efficiency × route distance.

The transport process consumes its fleet's fuel commodity at ``efficiency ×
distance`` per unit cargo, so a longer route costs more fuel and emits more — via
the fuel's own price and ``commodity_impacts``, with no privileged fuel or impact.
"""

from __future__ import annotations

from typing import Any

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

_SC = ScenarioConfig.from_dict(
    {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
)


def _wb_fuel(distance: float, efficiency: float = 0.01) -> dict[str, Any]:
    """One lane; the ship's capacity is left huge so only the FUEL scales with distance."""
    return {
        "periods": [{"year": 2025}],
        "commodities": [
            {"commodity_id": "cargo_kr", "kind": "material", "unit": "kt", "price": 0.0},
            {"commodity_id": "cargo_a", "kind": "product", "unit": "kt"},
            {"commodity_id": "bunker", "kind": "energy", "unit": "t", "price": 1.0},
        ],
        "impacts": [{"impact_id": "co2", "unit": "t"}],
        "commodity_impacts": [{"commodity_id": "bunker", "impact_id": "co2", "factor": 3.0}],
        "technologies": [{"technology_id": "route_a", "opex": 0}],
        "io": [
            {"technology_id": "route_a", "target": "cargo_kr", "role": "input", "coefficient": 1},
            {
                "technology_id": "route_a",
                "target": "cargo_a",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "processes": [
            {
                "process_id": "pA",
                "company": "carrier",
                "baseline_technology": "route_a",
                "capacity": 1e6,
            },
        ],
        "fleet": [
            {
                "fleet_id": "ship",
                "company": "carrier",
                "cargo": "cargo_kr",
                "fuel": "bunker",
                "efficiency": efficiency,  # t bunker / kt cargo / km
                # Flat capacity left generous (no ship_size/speed) so the carrier pool
                # never binds — this isolates the fuel effect from the ship-count one.
                "capacity": 1e6,
                "count": 1000.0,
            }
        ],
        "routes": [{"process": "pA", "mode": "sea", "distance": distance}],
        "fleet_routes": [{"process": "pA", "fleet_id": "ship"}],
        "demand": [
            {"company": "carrier", "commodity_id": "cargo_a", "year": 2025, "amount": 100.0}
        ],
    }


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    return extract_results(solve(build(assemble_problem(wb, _SC))))


def _co2(res: dict[str, Any]) -> float:
    return sum(float(r["total"]) for r in res["summary"]["impacts"] if r["impact"] == "co2")


def test_fuel_emissions_scale_with_distance() -> None:
    # fuel = efficiency · distance · throughput; co2 = fuel · 3.0.
    # near 10 000 km → 0.01·10000·100 = 10 000 t bunker → 30 000 t CO2.
    near = _solve(_wb_fuel(distance=10_000.0))
    assert near["status"] == "optimal"
    assert abs(_co2(near) - 30_000.0) < 1e-3
    # Doubling the distance doubles fuel burn and emissions.
    far = _solve(_wb_fuel(distance=20_000.0))
    assert abs(_co2(far) - 60_000.0) < 1e-3
    assert far["objective"] > near["objective"]  # more fuel bought ⇒ higher cost


def test_no_fuel_without_efficiency() -> None:
    # efficiency 0 ⇒ no fuel coefficient injected ⇒ no emissions.
    res = _solve(_wb_fuel(distance=10_000.0, efficiency=0.0))
    assert res["status"] == "optimal"
    assert _co2(res) < 1e-6
