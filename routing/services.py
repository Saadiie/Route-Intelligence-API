"""
Routing service.

Strategy:
1. Check DB cache — return immediately if found (zero external calls).
2. If ORS_API_KEY is set, call OpenRouteService (1 API call).
3. Otherwise use a built-in coordinate interpolation fallback —
   no external API needed, works offline.
"""

from __future__ import annotations

import logging
import math
import requests
from typing import Optional

from django.conf import settings

from routing.models import Route

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

# ---------------------------------------------------------------------------
# US city coordinate lookup for offline fallback
# ---------------------------------------------------------------------------

US_CITY_COORDS: dict[str, tuple[float, float]] = {
    "new york": (40.7128, -74.0060),
    "new york, ny": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437),
    "los angeles, ca": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298),
    "chicago, il": (41.8781, -87.6298),
    "houston": (29.7604, -95.3698),
    "houston, tx": (29.7604, -95.3698),
    "phoenix": (33.4484, -112.0740),
    "phoenix, az": (33.4484, -112.0740),
    "philadelphia": (39.9526, -75.1652),
    "philadelphia, pa": (39.9526, -75.1652),
    "san antonio": (29.4241, -98.4936),
    "san antonio, tx": (29.4241, -98.4936),
    "san diego": (32.7157, -117.1611),
    "san diego, ca": (32.7157, -117.1611),
    "dallas": (32.7767, -96.7970),
    "dallas, tx": (32.7767, -96.7970),
    "san jose": (37.3382, -121.8863),
    "san jose, ca": (37.3382, -121.8863),
    "austin": (30.2672, -97.7431),
    "austin, tx": (30.2672, -97.7431),
    "seattle": (47.6062, -122.3321),
    "seattle, wa": (47.6062, -122.3321),
    "denver": (39.7392, -104.9903),
    "denver, co": (39.7392, -104.9903),
    "nashville": (36.1627, -86.7816),
    "nashville, tn": (36.1627, -86.7816),
    "miami": (25.7617, -80.1918),
    "miami, fl": (25.7617, -80.1918),
    "atlanta": (33.7490, -84.3880),
    "atlanta, ga": (33.7490, -84.3880),
    "boston": (42.3601, -71.0589),
    "boston, ma": (42.3601, -71.0589),
    "las vegas": (36.1699, -115.1398),
    "las vegas, nv": (36.1699, -115.1398),
    "portland": (45.5051, -122.6750),
    "portland, or": (45.5051, -122.6750),
    "memphis": (35.1495, -90.0490),
    "memphis, tn": (35.1495, -90.0490),
    "oklahoma city": (35.4676, -97.5164),
    "oklahoma city, ok": (35.4676, -97.5164),
    "louisville": (38.2527, -85.7585),
    "louisville, ky": (38.2527, -85.7585),
    "baltimore": (39.2904, -76.6122),
    "baltimore, md": (39.2904, -76.6122),
    "milwaukee": (43.0389, -87.9065),
    "milwaukee, wi": (43.0389, -87.9065),
    "albuquerque": (35.0844, -106.6504),
    "albuquerque, nm": (35.0844, -106.6504),
    "tucson": (32.2226, -110.9747),
    "tucson, az": (32.2226, -110.9747),
    "fresno": (36.7378, -119.7871),
    "fresno, ca": (36.7378, -119.7871),
    "sacramento": (38.5816, -121.4944),
    "sacramento, ca": (38.5816, -121.4944),
    "kansas city": (39.0997, -94.5786),
    "kansas city, mo": (39.0997, -94.5786),
    "mesa": (33.4152, -111.8315),
    "mesa, az": (33.4152, -111.8315),
    "omaha": (41.2565, -95.9345),
    "omaha, ne": (41.2565, -95.9345),
    "minneapolis": (44.9778, -93.2650),
    "minneapolis, mn": (44.9778, -93.2650),
    "raleigh": (35.7796, -78.6382),
    "raleigh, nc": (35.7796, -78.6382),
    "cleveland": (41.4993, -81.6944),
    "cleveland, oh": (41.4993, -81.6944),
    "pittsburgh": (40.4406, -79.9959),
    "pittsburgh, pa": (40.4406, -79.9959),
    "st. louis": (38.6270, -90.1994),
    "st. louis, mo": (38.6270, -90.1994),
    "st louis": (38.6270, -90.1994),
    "st louis, mo": (38.6270, -90.1994),
    "tampa": (27.9506, -82.4572),
    "tampa, fl": (27.9506, -82.4572),
    "cincinnati": (39.1031, -84.5120),
    "cincinnati, oh": (39.1031, -84.5120),
    "indianapolis": (39.7684, -86.1581),
    "indianapolis, in": (39.7684, -86.1581),
    "columbus": (39.9612, -82.9988),
    "columbus, oh": (39.9612, -82.9988),
    "charlotte": (35.2271, -80.8431),
    "charlotte, nc": (35.2271, -80.8431),
    "salt lake city": (40.7608, -111.8910),
    "salt lake city, ut": (40.7608, -111.8910),
    "jacksonville": (30.3322, -81.6557),
    "jacksonville, fl": (30.3322, -81.6557),
    "richmond": (37.5407, -77.4360),
    "richmond, va": (37.5407, -77.4360),
    "baton rouge": (30.4515, -91.1871),
    "baton rouge, la": (30.4515, -91.1871),
    "new orleans": (29.9511, -90.0715),
    "new orleans, la": (29.9511, -90.0715),
    "birmingham": (33.5186, -86.8104),
    "birmingham, al": (33.5186, -86.8104),
}


def get_route(start: str, destination: str) -> Route:
    """
    Return a Route for (start, destination), using DB cache when available.
    """
    start_key = start.strip().lower()
    dest_key = destination.strip().lower()

    # 1. DB cache
    try:
        existing = Route.objects.get(
            start_location__iexact=start_key,
            destination_location__iexact=dest_key,
        )
        logger.info("Route cache hit: %s -> %s", start, destination)
        return existing
    except Route.DoesNotExist:
        pass

    # 2. Try ORS if key available
    api_key = settings.OPENROUTESERVICE_API_KEY
    if api_key:
        try:
            route = _fetch_ors(start, destination, api_key)
            route.save()
            return route
        except Exception as exc:
            logger.warning("ORS failed (%s) -- falling back to offline mode.", exc)

    # 3. Offline fallback
    logger.info("Using offline coordinate interpolation for %s -> %s", start, destination)
    route = _build_offline_route(start, destination)
    route.save()
    return route


def _fetch_ors(start: str, destination: str, api_key: str) -> Route:
    start_coords = _ors_geocode(start, api_key)
    dest_coords = _ors_geocode(destination, api_key)

    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "coordinates": [
            [start_coords[1], start_coords[0]],
            [dest_coords[1], dest_coords[0]],
        ],
        "instructions": False,
        "geometry": True,
        "units": "mi",
    }

    resp = requests.post(
        "https://api.openrouteservice.org/v2/directions/driving-car",
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    summary = data["routes"][0]["summary"]
    geometry_coords = data["routes"][0]["geometry"]["coordinates"]

    route = Route(
        start_location=start.strip().lower(),
        destination_location=destination.strip().lower(),
        distance_miles=summary["distance"],
        duration_minutes=summary["duration"] / 60,
    )
    route.geometry = geometry_coords
    return route


def _ors_geocode(location: str, api_key: str) -> tuple[float, float]:
    url = "https://api.openrouteservice.org/geocode/search"
    params = {"api_key": api_key, "text": location, "boundary.country": "US", "size": 1}
    resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    features = resp.json().get("features", [])
    if not features:
        raise RoutingError(f"Could not geocode: {location!r}")
    lon, lat = features[0]["geometry"]["coordinates"]
    return (lat, lon)


def _build_offline_route(start: str, destination: str) -> Route:
    """
    Build a route using straight-line interpolation between city coordinates.
    Distance estimated using haversine x 1.2 (road distance is ~20% longer).
    """
    start_coords = _lookup_city(start)
    dest_coords = _lookup_city(destination)

    if start_coords is None:
        raise RoutingError(
            f"Unknown location: '{start}'. "
            "Please use a major US city like 'Houston, TX' or 'Chicago, IL'."
        )
    if dest_coords is None:
        raise RoutingError(
            f"Unknown location: '{destination}'. "
            "Please use a major US city like 'Houston, TX' or 'Chicago, IL'."
        )

    n_points = 200
    geometry: list[list[float]] = []

    for i in range(n_points + 1):
        t = i / n_points
        lat = start_coords[0] + t * (dest_coords[0] - start_coords[0])
        lon = start_coords[1] + t * (dest_coords[1] - start_coords[1])
        arc = math.sin(t * math.pi) * 0.5
        lat += arc * (dest_coords[1] - start_coords[1]) * 0.1
        geometry.append([lon, lat])

    straight_miles = _haversine(start_coords, dest_coords)
    distance_miles = straight_miles * 1.2
    duration_minutes = (distance_miles / 60) * 60

    route = Route(
        start_location=start.strip().lower(),
        destination_location=destination.strip().lower(),
        distance_miles=distance_miles,
        duration_minutes=duration_minutes,
    )
    route.geometry = geometry
    return route


def _lookup_city(location: str) -> Optional[tuple[float, float]]:
    key = location.strip().lower()
    if key in US_CITY_COORDS:
        return US_CITY_COORDS[key]
    city_part = key.split(",")[0].strip()
    if city_part in US_CITY_COORDS:
        return US_CITY_COORDS[city_part]
    return None


def _haversine(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    R = 3958.8
    phi1, phi2 = math.radians(p1[0]), math.radians(p2[0])
    dphi = math.radians(p2[0] - p1[0])
    dlambda = math.radians(p2[1] - p1[1])
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


class RoutingError(Exception):
    """Raised when route fetching fails."""