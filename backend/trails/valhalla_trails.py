# backend/trails/valhalla_trails.py

import polyline
from backend.valhalla_client import valhalla_route


def valhalla_trail_route(start_lat, start_lon, end_lat, end_lon):
    """
    Compute a pedestrian route between two trail points using Valhalla.
    
    Inputs:
        start_lat, start_lon : float
        end_lat, end_lon     : float
        
    Returns:
        {
            ok: True/False,
            distance_m: meters,
            duration_s: seconds,
            coordinates: [(lat, lon), ...],
            polyline: encoded polyline
        }
    """

    start = (start_lat, start_lon)
    end   = (end_lat, end_lon)

    # ---------------------------------------------------------------
    # 1. Call Valhalla
    # ---------------------------------------------------------------
    try:
        result = valhalla_route(
            start,
            end,
            costing="pedestrian"
        )
    except Exception as e:
        return {"error": f"Valhalla request failed: {str(e)}"}

    # ---------------------------------------------------------------
    # 2. Validate response structure
    # ---------------------------------------------------------------
    if not isinstance(result, dict) or "trip" not in result:
        return {"error": "Valhalla returned no trip object"}

    trip = result["trip"]

    if "legs" not in trip or len(trip["legs"]) == 0:
        return {"error": "Valhalla returned empty legs"}

    leg = trip["legs"][0]

    if "shape" not in leg:
        return {"error": "Valhalla returned no shape polyline"}

    encoded_poly = leg["shape"]

    # ---------------------------------------------------------------
    # 3. Decode polyline
    # ---------------------------------------------------------------
    try:
        coords = polyline.decode(encoded_poly)   # [(lat, lon), ...]
    except Exception as e:
        return {"error": f"Failed to decode polyline: {str(e)}"}

    if len(coords) < 2:
        return {"error": "Valhalla returned too few geometry points"}

    # ---------------------------------------------------------------
    # 4. Summary extraction
    # ---------------------------------------------------------------
    summary = trip.get("summary", {})
    length_km = summary.get("length", 0)
    duration_s = summary.get("time", 0)

    # Protect against bogus routes
    distance_m = max(0.0, length_km * 1000)

    if distance_m < 5:
        return {"error": "Valhalla returned unrealistic zero-length trail route"}

    # ---------------------------------------------------------------
    # 5. Return clean result
    # ---------------------------------------------------------------
    return {
        "ok": True,
        "distance_m": round(distance_m, 2),
        "duration_s": round(float(duration_s), 2),
        "coordinates": coords,
        "polyline": encoded_poly
    }
