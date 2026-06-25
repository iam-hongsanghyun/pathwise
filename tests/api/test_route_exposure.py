"""Chokepoint-exposure endpoint: which sea routes a corridor closure hits, and how
far each detours. Pure geometry (searoute) — probability is overlaid client-side."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pathwise.api.main import app

client = TestClient(app)

# (lon, lat). Busan→Rotterdam is the canonical Suez-dependent lane; Busan→Sydney
# does not touch Suez, so it must NOT appear under the Suez corridor's exposure.
_BUSAN = (129.04, 35.10)
_ROTTERDAM = (4.48, 51.95)
_SYDNEY = (151.21, -33.87)


def _route(rid: str, a: tuple[float, float], b: tuple[float, float]) -> dict:
    return {
        "id": rid,
        "from_lon": a[0],
        "from_lat": a[1],
        "to_lon": b[0],
        "to_lat": b[1],
        "mode": "sea",
    }


def test_exposure_flags_the_suez_dependent_lane_with_a_detour() -> None:
    resp = client.post(
        "/api/route-exposure",
        json={
            "routes": [_route("kr_eu", _BUSAN, _ROTTERDAM), _route("kr_au", _BUSAN, _SYDNEY)],
            "corridors": [{"id": "suez", "prob": 0.05}, {"id": "panama", "prob": 0.02}],
        },
    )
    assert resp.status_code == 200
    by_id = {c["id"]: c for c in resp.json()["corridors"]}

    # Suez is on the KR→EU lane: one route affected, with a positive detour.
    assert "suez" in by_id
    suez = by_id["suez"]
    assert suez["n_routes"] == 1
    assert suez["routes"][0]["route_id"] == "kr_eu"
    assert suez["total_delta_km"] > 0
    assert suez["routes"][0]["delta_km"] > 0
    # The Busan→Sydney lane does not use Suez, so it is not listed there.
    assert all(r["route_id"] != "kr_au" for r in suez["routes"])


def test_hard_blocked_corridor_is_excluded_from_exposure() -> None:
    # A corridor at prob >= 1 is the deterministic base-case block, not a risk —
    # it must not appear in the exposure list (it defines the baseline instead).
    resp = client.post(
        "/api/route-exposure",
        json={
            "routes": [_route("kr_eu", _BUSAN, _ROTTERDAM)],
            "corridors": [{"id": "suez", "prob": 1.0}],
        },
    )
    assert resp.status_code == 200
    assert all(c["id"] != "suez" for c in resp.json()["corridors"])


def test_corridors_ranked_worst_first() -> None:
    resp = client.post(
        "/api/route-exposure",
        json={
            "routes": [_route("kr_eu", _BUSAN, _ROTTERDAM)],
            "corridors": [{"id": "suez", "prob": 0.1}, {"id": "panama", "prob": 0.1}],
        },
    )
    assert resp.status_code == 200
    deltas = [c["total_delta_km"] for c in resp.json()["corridors"]]
    assert deltas == sorted(deltas, reverse=True)
