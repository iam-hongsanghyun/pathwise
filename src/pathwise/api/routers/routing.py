"""Routing router — the drawable path for a transport route + chokepoint exposure.

The Fleet map needs the *actual* line a route follows so a sea route bends around
coasts and through canals (Suez/Panama) rather than cutting a great-circle across
land. ``POST /api/route-path`` returns the polyline + distance from the routing
providers (sea = searoute; land = straight segment × the mode factor).

``POST /api/route-exposure`` answers the chokepoint-risk question: for each
maritime corridor, which sea routes traverse it and how far each would have to
detour if it closed (or whether it is left with no alternative). This is pure
geometry — the per-corridor disruption *probability* is overlaid client-side, so
editing a probability never needs a re-fetch.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from pathwise.logger import get_logger
from pathwise.routing import route_distance_km, route_passages, route_path

logger = get_logger(__name__)
router = APIRouter(prefix="/api")


class RoutePathRequest(BaseModel):
    from_lon: float
    from_lat: float
    to_lon: float
    to_lat: float
    mode: str = "sea"
    #: Closed maritime corridors to route around (suez / ormuz / panama / …).
    avoid: list[str] = []


class RoutePathResponse(BaseModel):
    coordinates: list[list[float]]  # [[lon, lat], …] — drawable polyline
    distance_km: float


@router.post("/route-path")
def get_route_path(req: RoutePathRequest) -> RoutePathResponse:
    """The polyline + distance for one route (sea follows the marine network), routed
    around any closed corridors in ``avoid``."""
    coords, dist = route_path(
        (req.from_lon, req.from_lat), (req.to_lon, req.to_lat), req.mode, tuple(req.avoid)
    )
    return RoutePathResponse(coordinates=[[lon, lat] for lon, lat in coords], distance_km=dist)


# ── Chokepoint exposure (corridor sensitivity) ──────────────────────────────────


class ExposureRoute(BaseModel):
    id: str
    from_lon: float
    from_lat: float
    to_lon: float
    to_lat: float
    mode: str = "sea"


class ExposureCorridor(BaseModel):
    id: str
    #: Annual closure probability [0, 1]. ``>= 1`` ⇒ assumed closed in the base
    #: case (the deterministic hard block); such corridors define ``avoid`` and
    #: are excluded from the exposure list (they are not a *risk*, they are a fact).
    prob: float = 0.0


class RouteExposureRequest(BaseModel):
    routes: list[ExposureRoute]
    corridors: list[ExposureCorridor]


class AffectedRoute(BaseModel):
    route_id: str
    base_km: float
    #: Distance once this corridor is avoided; ``None`` ⇒ no alternative (stranded).
    detour_km: float | None
    delta_km: float | None
    delta_pct: float | None


class CorridorExposure(BaseModel):
    id: str
    n_routes: int  # sea routes that traverse this corridor today
    n_stranded: int  # of those, how many have no way around
    total_delta_km: float  # Σ detour Δ over routes that can reroute
    routes: list[AffectedRoute]


class RouteExposureResponse(BaseModel):
    #: One entry per candidate corridor that at least one route traverses, ranked
    #: worst-first (stranded routes, then largest total detour). Probability is NOT
    #: applied here — the client multiplies ``total_delta_km`` by each corridor's
    #: live probability to get the expected annual detour, so editing a probability
    #: needs no re-fetch.
    corridors: list[CorridorExposure]


@router.post("/route-exposure")
def get_route_exposure(req: RouteExposureRequest) -> RouteExposureResponse:
    """Per maritime corridor: which sea routes traverse it and how far each would
    detour (or whether it is stranded) if it closed.

    Base case = every corridor open EXCEPT those already at ``prob >= 1`` (the
    deterministic hard block), which are routed around up front so they form the
    baseline rather than appearing as risks.
    """
    base_avoid = tuple(c.id for c in req.corridors if c.prob >= 1.0)
    sea = [r for r in req.routes if (r.mode or "sea").lower() == "sea"]

    # Precompute, per route: its baseline passages + baseline distance (one pair
    # of searoute calls each), so the per-corridor loop only adds one call per
    # (corridor, affected-route).
    base: dict[str, tuple[tuple[float, float], tuple[float, float], set[str], float]] = {}
    for r in sea:
        a = (r.from_lon, r.from_lat)
        b = (r.to_lon, r.to_lat)
        passages = set(route_passages(a, b, base_avoid))
        try:
            d_open = route_distance_km(a, b, "sea", base_avoid)
        except Exception:
            continue  # baseline itself unroutable — skip this route entirely
        base[r.id] = (a, b, passages, d_open)

    out: list[CorridorExposure] = []
    for c in req.corridors:
        if c.id in base_avoid:
            continue  # already closed in the base case — not a risk to report
        affected: list[AffectedRoute] = []
        total = 0.0
        stranded = 0
        for r in sea:
            entry = base.get(r.id)
            if entry is None:
                continue
            a, b, passages, d_open = entry
            if c.id not in passages:
                continue  # this route doesn't use the corridor — no exposure
            try:
                d_det = route_distance_km(a, b, "sea", (*base_avoid, c.id))
                delta = d_det - d_open
                affected.append(
                    AffectedRoute(
                        route_id=r.id,
                        base_km=d_open,
                        detour_km=d_det,
                        delta_km=delta,
                        delta_pct=(100.0 * delta / d_open) if d_open else None,
                    )
                )
                total += max(delta, 0.0)
            except Exception:  # no path avoiding the corridor — the route is stranded
                stranded += 1
                affected.append(
                    AffectedRoute(
                        route_id=r.id, base_km=d_open, detour_km=None, delta_km=None, delta_pct=None
                    )
                )
        if affected:
            out.append(
                CorridorExposure(
                    id=c.id,
                    n_routes=len(affected),
                    n_stranded=stranded,
                    total_delta_km=total,
                    routes=affected,
                )
            )

    out.sort(key=lambda e: (e.n_stranded > 0, e.total_delta_km), reverse=True)
    return RouteExposureResponse(corridors=out)
