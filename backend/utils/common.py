# backend/utils/common.py
#
# Shared utilities used across all routing modules.
# Previously copy-pasted 4-5 times — now one canonical place.

import math
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Haversine distance (km)
# ---------------------------------------------------------------------------
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(max(0.0, a)))


# ---------------------------------------------------------------------------
# AR waypoint simplification
# ---------------------------------------------------------------------------
def simplify_waypoints(coords: list, step: int = 5) -> list:
    """Return every Nth coordinate — reduces AR anchor density."""
    if len(coords) <= step:
        return coords
    return coords[::step]


# ---------------------------------------------------------------------------
# Turn-by-turn: extract first meaningful step or compute bearing
# ---------------------------------------------------------------------------
def compute_next_turn(steps: list, coords: list) -> dict | None:
    if steps:
        m = steps[0]
        return {
            "type": m.get("type", ""),
            "instruction": m.get("instruction", ""),
            "distance_m": m.get("length", 0),
        }

    if len(coords) >= 2:
        lat1, lon1 = coords[0]
        lat2, lon2 = coords[1]
        bearing = math.degrees(math.atan2(lon2 - lon1, lat2 - lat1))
        return {
            "type": "straight",
            "instruction": "Continue straight",
            "degrees": round(bearing, 1),
            "distance_m": 5,
        }

    return None


# ---------------------------------------------------------------------------
# Parse Valhalla leg → steps list
# ---------------------------------------------------------------------------
def parse_maneuvers(leg: dict) -> list[dict]:
    steps = []
    for m in leg.get("maneuvers", []):
        steps.append(
            {
                "instruction": m.get("instruction", ""),
                "type": m.get("type", ""),
                "length_km": round(m.get("length", 0), 3),
                "begin_shape_index": m.get("begin_shape_index"),
                "end_shape_index": m.get("end_shape_index"),
                "street_names": m.get("street_names", []),
            }
        )
    return steps


# ---------------------------------------------------------------------------
# Weather (Open-Meteo) — free, no key required
# ---------------------------------------------------------------------------
def get_weather(lat: float, lon: float) -> str:
    """Returns one of: clear | rain | snow | hot | cold"""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}&current_weather=true"
        )
        w = requests.get(url, timeout=4).json()["current_weather"]
        code = int(w["weathercode"])
        temp = float(w["temperature"])

        if code in {61, 63, 65, 80, 81, 82}:
            return "rain"
        if code in {71, 73, 75, 77, 85, 86}:
            return "snow"
        if temp > 30:
            return "hot"
        if temp < 4:
            return "cold"
        return "clear"
    except Exception:
        return "clear"


# ---------------------------------------------------------------------------
# Day / Night detection (sunrise-sunset.org)
# ---------------------------------------------------------------------------
def is_night(lat: float, lon: float) -> bool:
    try:
        r = requests.get(
            f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&formatted=0",
            timeout=4,
        ).json()["results"]

        sunrise = datetime.fromisoformat(r["sunrise"])
        sunset = datetime.fromisoformat(r["sunset"])
        now = datetime.now(timezone.utc)

        return not (sunrise <= now <= sunset)
    except Exception:
        # Fallback: night if outside 6am–8pm local
        hour = datetime.now().hour
        return hour < 6 or hour >= 20


# ---------------------------------------------------------------------------
# Fetch weather + night in parallel (saves ~4s on sequential calls)
# ---------------------------------------------------------------------------
def get_weather_and_night(lat: float, lon: float) -> tuple[str, bool]:
    """Returns (weather, night) fetched concurrently."""
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_weather = ex.submit(get_weather, lat, lon)
        f_night = ex.submit(is_night, lat, lon)
        weather = f_weather.result()
        night = f_night.result()
    return weather, night


# ---------------------------------------------------------------------------
# Bounding box from coordinate list (with optional buffer in degrees)
# ---------------------------------------------------------------------------
def coords_bbox(coords: list[tuple], buffer_deg: float = 0.005) -> dict:
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    return {
        "min_lat": min(lats) - buffer_deg,
        "max_lat": max(lats) + buffer_deg,
        "min_lon": min(lons) - buffer_deg,
        "max_lon": max(lons) + buffer_deg,
    }


# ---------------------------------------------------------------------------
# Point-to-polyline distance (meters) — used for enrichment filtering
# ---------------------------------------------------------------------------
def point_to_route_distance_m(
    lat: float, lon: float, coords: list[tuple], sample_every: int = 5
) -> float:
    """
    Approximate minimum distance from (lat, lon) to any sampled route coordinate.
    Sampling avoids O(N) cost for long routes.
    """
    sampled = coords[::sample_every] if len(coords) > sample_every else coords
    min_dist = float("inf")
    for rlat, rlon in sampled:
        d = haversine(lat, lon, rlat, rlon) * 1000  # meters
        if d < min_dist:
            min_dist = d
    return min_dist
