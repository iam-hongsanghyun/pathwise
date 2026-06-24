"""Routing router — the drawable path for a transport route.

The Fleet map needs the *actual* line a route follows so a sea route bends around
coasts and through canals (Suez/Panama) rather than cutting a great-circle across
land. ``POST /api/route-path`` returns the polyline + distance from the routing
providers (sea = searoute; land = straight segment × the mode factor).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from pathwise.logger import get_logger
from pathwise.routing import route_path

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
