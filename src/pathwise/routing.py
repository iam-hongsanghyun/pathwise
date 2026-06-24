"""Physical route distances for transport links.

The optimiser only ever consumes a **scalar distance** per route; path-finding is
kept out of the core so the engine stays geometry-agnostic. This module turns two
geographic points (lon, lat) and a transport mode into that distance via two
providers:

* **sea** — the real marine network (great-circle legs joined through canals and
  straits, so Suez/Panama/Cape are reflected) via the ``searoute`` package.
* **land (road / rail)** — great-circle distance × a per-mode *detour factor*, a
  cheap, dependency-free estimate. No routing service is required; swap in
  precomputed OSM distances (a route's explicit ``distance``) when accuracy matters.

A route's explicitly authored distance always wins; these providers only fill it
in when it is left blank.

Algorithm (great-circle, haversine):
    $$d = 2R\\,\\arcsin\\sqrt{\\sin^2\\tfrac{\\Delta\\varphi}{2}
        + \\cos\\varphi_1\\cos\\varphi_2\\sin^2\\tfrac{\\Delta\\lambda}{2}}$$
    ASCII: d = 2*R*asin(sqrt(sin^2(dlat/2) + cos(lat1)*cos(lat2)*sin^2(dlon/2)))
where R is the Earth radius [km], phi is latitude and lambda is longitude [rad].
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any

#: Mean Earth radius [km] (IUGG).
EARTH_RADIUS_KM = 6371.0088

#: Great-circle is the straight-line lower bound; real road/rail networks are
#: longer. These multiply the great-circle distance by a typical published ratio of
#: network distance to straight-line distance, per mode. A route may always override
#: the estimate with an explicit distance. ``sea`` is not here — it uses ``searoute``.
DETOUR_FACTOR: dict[str, float] = {
    "road": 1.4,
    "rail": 1.2,
}

#: A geographic point as ``(longitude, latitude)`` in degrees (searoute's order).
Point = tuple[float, float]


def great_circle_km(a: Point, b: Point) -> float:
    """Haversine great-circle distance [km] between two ``(lon, lat)`` points."""
    lon1, lat1 = a
    lon2, lat2 = b
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlam = radians(lon2 - lon1)
    h = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(h))


#: searoute's own default restriction (the Northwest Passage is closed year-round in
#: its base network). Corridor what-ifs ADD to this — they never remove it.
_DEFAULT_RESTRICTIONS = ["northwest"]


def _sea(a: Point, b: Point, avoid: tuple[str, ...], passages: bool) -> Any:
    """Call searoute avoiding ``avoid`` passages (on top of the base restriction)."""
    import searoute as sr  # type: ignore[import-untyped]  # lazy: marine net loads on demand

    restrictions = [*_DEFAULT_RESTRICTIONS, *(p for p in avoid if p not in _DEFAULT_RESTRICTIONS)]
    return sr.searoute(
        list(a), list(b), units="km", restrictions=restrictions, return_passages=passages
    )


def sea_distance_km(a: Point, b: Point, avoid: tuple[str, ...] = ()) -> float:
    """Marine-network distance [km] between two ``(lon, lat)`` points via searoute.

    ``searoute`` routes through the global shipping network, so the result follows
    canals/straits (Suez, Panama, Malacca) rather than crossing land. ``avoid`` is a
    set of passage ids (``suez``, ``ormuz`` = Hormuz, ``panama``, …) that are CLOSED —
    the route is forced around them (longer, or impossible).
    """
    return float(_sea(a, b, avoid, False)["properties"]["length"])


def route_distance_km(a: Point, b: Point, mode: str, avoid: tuple[str, ...] = ()) -> float:
    """Distance [km] for a ``(from, to, mode)`` route, optionally avoiding ``avoid``
    passages (a corridor what-if; sea only).

    ``sea`` uses the marine network (searoute); ``road``/``rail`` use great-circle ×
    the mode detour factor; any other/blank mode falls back to great-circle (×1).
    """
    if (mode or "").lower() == "sea":
        return sea_distance_km(a, b, avoid)
    return great_circle_km(a, b) * DETOUR_FACTOR.get((mode or "").lower(), 1.0)


def route_path(
    a: Point, b: Point, mode: str, avoid: tuple[str, ...] = ()
) -> tuple[list[Point], float]:
    """The drawable polyline + distance [km] for a ``(from, to, mode)`` route.

    ``sea`` returns the actual marine path (searoute follows coasts + canals, so a
    sea route never cuts across land), forced around any ``avoid`` (closed) passages;
    other modes return the straight segment with the mode's great-circle × factor.
    """
    if (mode or "").lower() == "sea":
        route = _sea(a, b, avoid, False)
        coords = [(float(lon), float(lat)) for lon, lat in route["geometry"]["coordinates"]]
        return coords, float(route["properties"]["length"])
    return [a, b], route_distance_km(a, b, mode)


def route_passages(a: Point, b: Point, avoid: tuple[str, ...] = ()) -> list[str]:
    """The named chokepoints a sea route traverses (``suez``, ``ormuz``, …).

    Lets the UI show which corridors a lane depends on (and which a block would hit).
    Returns ``[]`` for an unroutable pair.
    """
    try:
        props = _sea(a, b, avoid, True)["properties"]
    except Exception:
        return []
    return list(props.get("traversed_passages") or [])
