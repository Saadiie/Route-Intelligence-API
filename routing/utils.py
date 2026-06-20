"""
Geospatial utilities for route processing.

All functions are pure (no I/O) and fully typed.
Uses standard library math only — no heavy geospatial deps required
for the core algorithm, though shapely/numpy are used where available.
"""

from __future__ import annotations

import math
from typing import NamedTuple

EARTH_RADIUS_MILES = 3958.8


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class LatLon(NamedTuple):
    """A geographic coordinate."""
    lat: float
    lon: float


class RoutePoint(NamedTuple):
    """A point along the route with cumulative distance from start."""
    lat: float
    lon: float
    cumulative_miles: float


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------


def haversine_miles(p1: LatLon, p2: LatLon) -> float:
    """
    Compute great-circle distance in miles between two lat/lon points.

    Time complexity: O(1)
    """
    phi1 = math.radians(p1.lat)
    phi2 = math.radians(p2.lat)
    dphi = math.radians(p2.lat - p1.lat)
    dlambda = math.radians(p2.lon - p1.lon)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Route interpolation
# ---------------------------------------------------------------------------


def annotate_route_with_distances(
    coordinates: list[list[float]],
) -> list[RoutePoint]:
    """
    Convert raw [lon, lat] coordinate list into RoutePoint list with
    cumulative mileage attached.

    The geometry comes from ORS/OSRM as [lon, lat] pairs (GeoJSON order).

    Time complexity: O(n) where n = len(coordinates)
    """
    if not coordinates:
        return []

    points: list[RoutePoint] = []
    cumulative = 0.0

    prev = LatLon(lat=coordinates[0][1], lon=coordinates[0][0])
    points.append(RoutePoint(lat=prev.lat, lon=prev.lon, cumulative_miles=0.0))

    for coord in coordinates[1:]:
        cur = LatLon(lat=coord[1], lon=coord[0])
        segment_miles = haversine_miles(prev, cur)
        cumulative += segment_miles
        points.append(RoutePoint(lat=cur.lat, lon=cur.lon, cumulative_miles=cumulative))
        prev = cur

    return points


def find_point_at_distance(
    route_points: list[RoutePoint],
    target_miles: float,
) -> RoutePoint:
    """
    Return the RoutePoint closest to *target_miles* along the route.

    Uses binary search for O(log n) lookup.
    """
    if not route_points:
        raise ValueError("route_points must not be empty")

    lo, hi = 0, len(route_points) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if route_points[mid].cumulative_miles < target_miles:
            lo = mid + 1
        else:
            hi = mid

    # lo is now the index of the first point >= target_miles
    # Return whichever of lo-1, lo is closer to target_miles
    if lo == 0:
        return route_points[0]
    before = route_points[lo - 1]
    after = route_points[lo]
    if abs(before.cumulative_miles - target_miles) <= abs(after.cumulative_miles - target_miles):
        return before
    return after


def perpendicular_distance_miles(
    point: LatLon,
    segment_start: LatLon,
    segment_end: LatLon,
) -> float:
    """
    Approximate perpendicular distance from *point* to a great-circle
    segment [segment_start, segment_end], in miles.

    Uses a flat-Earth approximation which is accurate enough for the
    ~50-mile radii we care about.
    """
    # Project to local Cartesian (East-North in miles)
    def to_en(ref: LatLon, p: LatLon) -> tuple[float, float]:
        dlat = math.radians(p.lat - ref.lat) * EARTH_RADIUS_MILES
        dlon = (
            math.radians(p.lon - ref.lon)
            * EARTH_RADIUS_MILES
            * math.cos(math.radians(ref.lat))
        )
        return dlon, dlat  # East, North

    origin = segment_start
    sx, sy = 0.0, 0.0
    ex, ey = to_en(origin, segment_end)
    px, py = to_en(origin, point)

    seg_len_sq = ex ** 2 + ey ** 2
    if seg_len_sq < 1e-10:
        return math.hypot(px, py)

    t = max(0.0, min(1.0, (px * ex + py * ey) / seg_len_sq))
    closest_x = sx + t * ex
    closest_y = sy + t * ey
    return math.hypot(px - closest_x, py - closest_y)
