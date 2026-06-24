"""Route-distance providers: great-circle, land detour factor, and sea (searoute)."""

from __future__ import annotations

import pytest

from pathwise.routing import (
    DETOUR_FACTOR,
    great_circle_km,
    route_distance_km,
    route_passages,
    route_path,
)

# (lon, lat) points.
_BUSAN = (129.04, 35.10)
_SYDNEY = (151.21, -33.87)


def test_great_circle_one_degree_of_latitude() -> None:
    # One degree of latitude is ~111 km anywhere on the globe.
    d = great_circle_km((0.0, 0.0), (0.0, 1.0))
    assert d == pytest.approx(111.19, abs=0.5)


def test_great_circle_is_symmetric_and_zero_on_self() -> None:
    assert great_circle_km(_BUSAN, _SYDNEY) == pytest.approx(great_circle_km(_SYDNEY, _BUSAN))
    assert great_circle_km(_BUSAN, _BUSAN) == pytest.approx(0.0, abs=1e-9)


def test_land_modes_apply_their_detour_factor() -> None:
    base = great_circle_km(_BUSAN, _SYDNEY)
    assert route_distance_km(_BUSAN, _SYDNEY, "road") == pytest.approx(base * DETOUR_FACTOR["road"])
    assert route_distance_km(_BUSAN, _SYDNEY, "rail") == pytest.approx(base * DETOUR_FACTOR["rail"])
    # An unknown / blank mode is plain great-circle (factor 1).
    assert route_distance_km(_BUSAN, _SYDNEY, "") == pytest.approx(base)


def test_route_path_sea_is_a_polyline_following_the_water() -> None:
    # A sea route is a many-point polyline (around coasts / through canals), not a
    # straight 2-point segment, and its length matches the sea distance.
    coords, dist = route_path(_BUSAN, _SYDNEY, "sea")
    assert len(coords) > 2
    assert dist == pytest.approx(route_distance_km(_BUSAN, _SYDNEY, "sea"))
    # endpoints anchor near the requested ports
    assert coords[0][0] == pytest.approx(_BUSAN[0], abs=2.0)


def test_route_path_land_is_a_straight_segment() -> None:
    coords, dist = route_path(_BUSAN, _SYDNEY, "road")
    assert coords == [_BUSAN, _SYDNEY]
    assert dist == pytest.approx(great_circle_km(_BUSAN, _SYDNEY) * DETOUR_FACTOR["road"])


_ROTTERDAM = (4.48, 51.95)


def test_blocking_a_corridor_forces_a_longer_reroute() -> None:
    # The normal Busan→Rotterdam lane runs through Suez; closing Suez forces a
    # longer way round (Panama / Cape), so the avoided distance must exceed the base.
    base = route_distance_km(_BUSAN, _ROTTERDAM, "sea")
    via_block = route_distance_km(_BUSAN, _ROTTERDAM, "sea", ("suez",))
    assert via_block > base
    # Closing Panama as well pushes it further still (around Africa).
    assert route_distance_km(_BUSAN, _ROTTERDAM, "sea", ("suez", "panama")) > via_block


def test_route_passages_lists_the_chokepoints_used() -> None:
    # The KR→EU sea route depends on the Suez corridor (so a Suez block would hit it).
    passages = route_passages(_BUSAN, _ROTTERDAM)
    assert "suez" in passages


def test_sea_route_is_longer_than_great_circle() -> None:
    # The marine network must go around land, so the sea distance exceeds the
    # straight-line great-circle between the two ports.
    sea = route_distance_km(_BUSAN, _SYDNEY, "sea")
    assert sea > great_circle_km(_BUSAN, _SYDNEY)
    assert 7000 < sea < 12000  # sanity band for Busan↔Sydney [km]
