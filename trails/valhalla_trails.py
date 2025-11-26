# backend/trails/valhalla_trails.py

import polyline
from backend.valhalla_client import valhalla_route


def valhalla_trail_route(start_lat, start_lon, end_lat, end_lon):
    """
    Compute a walking route between two trail points using Valhalla.
    Input: coordinates in (lat, lon)
    Output: decoded geometry + distance + duration
    """

    start = (start_lat, start_lon)
    end   = (end_lat, end_lon)

    # --------------------------------------
    # Valhalla Request
    # --------------------------------------
    try:
        result = valhalla_route(
            start,
            end,
            costing="pedestrian"
        )
    except Exception as e:
        return {"error": f"Valhalla request failed: {str(e)}"}

    # --------------------------------------
    # Validate response
    # --------------------------------------
    if "trip" not in result:
        return {"error": "Valhalla returned no route"}

    trip = result["trip"]
    if not trip.get("legs"):
        return {"error": "Valhalla returned empty legs"}

    leg = trip["legs"][0]

    if "shape" not in leg:
        return {"error": "Valhalla returned no polyline shape"}

    encoded_poly = leg["shape"]

    # Decode Valhalla polyline → (lat, lon)
    try:
        coords = polyline.decode(encoded_poly)
    except:
        return {"error": "Failed to decode polyline"}

    # --------------------------------------
    # Extract distance/time
    # --------------------------------------
    summary = trip.get("summary", {})
    distance_m = summary.get("length", 0) * 1000     # km → meters
    duration_s = summary.get("time", 0)              # seconds

    if distance_m < 5:
        return {"error": "Valhalla returned unrealistic zero-length route"}

    return {
        "ok": True,
        "distance_m": round(distance_m, 2),
        "duration_s": round(duration_s, 2),
        "coordinates": coords,
        "polyline": encoded_poly
    }
