# backend/routing_elevation.py
#
# Flat-friendly pedestrian routing with full elevation analytics.
# Uses Valhalla's built-in /height endpoint where available,
# falling back to the external elevation pipeline.

import requests
import polyline
from backend.config import VALHALLA_URL, VALHALLA_TIMEOUT
from backend.valhalla_client import valhalla_route
from backend.utils.common import simplify_waypoints, compute_next_turn, parse_maneuvers

_FLAT_COSTING = {
    "pedestrian": {
        "use_hills": 0.0,
        "use_roads": 0.3,
        "use_tracks": 0.3,
    }
}


def _fetch_valhalla_heights(coords: list[tuple]) -> list[float] | None:
    """Ask Valhalla /height for elevation data (no external API needed)."""
    try:
        payload = {"shape": [{"lat": lat, "lon": lon} for lat, lon in coords]}
        res = requests.post(
            f"{VALHALLA_URL}/height", json=payload, timeout=VALHALLA_TIMEOUT
        )
        if res.status_code != 200:
            return None
        data = res.json()
        heights = [pt.get("height", 0) for pt in data.get("shape", [])]
        return heights if len(heights) == len(coords) else None
    except Exception:
        return None


def _elevation_stats(coords: list[tuple], elevations: list[float]) -> dict:
    gain = loss = 0.0
    slopes = []

    for i in range(1, len(elevations)):
        diff = elevations[i] - elevations[i - 1]
        if diff > 0:
            gain += diff
        else:
            loss += abs(diff)

        # approximate horizontal distance (m) between consecutive coords
        from backend.utils.common import haversine
        dist_m = haversine(
            coords[i - 1][0], coords[i - 1][1],
            coords[i][0], coords[i][1]
        ) * 1000

        slope = round((diff / dist_m) * 100, 2) if dist_m > 1 else 0.0
        slopes.append(slope)

    max_slope = max(abs(s) for s in slopes) if slopes else 0.0

    if gain < 40 and max_slope < 5:
        difficulty = "Easy"
    elif gain < 120 and max_slope < 10:
        difficulty = "Moderate"
    elif gain < 250 and max_slope < 15:
        difficulty = "Hard"
    else:
        difficulty = "Very Hard"

    return {
        "elevations": [round(e, 1) for e in elevations],
        "elevation_gain_m": round(gain, 1),
        "elevation_loss_m": round(loss, 1),
        "max_slope_percent": round(max_slope, 2),
        "difficulty": difficulty,
    }


def get_elevation_route(start: tuple, end: tuple) -> dict:
    result = valhalla_route(start, end, costing="pedestrian", costing_options=_FLAT_COSTING)

    if "trip" not in result:
        return {"error": result.get("error", "Valhalla elevation route failed.")}

    leg = result["trip"]["legs"][0]
    summary = result["trip"]["summary"]
    coords = polyline.decode(leg["shape"], precision=6)
    steps = parse_maneuvers(leg)

    # Try Valhalla's own height service first
    elevations = _fetch_valhalla_heights(coords)

    elevation_data: dict = {}
    if elevations:
        elevation_data = _elevation_stats(coords, elevations)
    else:
        # Defer to the shared elevation pipeline (non-blocking: return zeros + flag)
        elevation_data = {
            "elevations": [],
            "elevation_gain_m": 0,
            "elevation_loss_m": 0,
            "max_slope_percent": 0,
            "difficulty": "Unknown",
            "note": "Elevation data unavailable",
        }

    return {
        "mode": "elevation",
        "coordinates": coords,
        "waypoints": simplify_waypoints(coords),
        "steps": steps,
        "next_turn": compute_next_turn(steps, coords),
        "distance_m": round(summary.get("length", 0) * 1000),
        "duration_s": int(summary.get("time", 0)),
        **elevation_data,
    }
