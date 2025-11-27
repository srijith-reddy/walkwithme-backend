from backend.valhalla_client import valhalla_route, VALHALLA_URL
import polyline
import requests


# ============================================================
# Elevation-Friendly Routing using Valhalla
# ============================================================
def get_elevation_route(start, end):

    if not start or not end:
        return {"error": "Missing start or end"}

    # -----------------------------------------------------------
    # COSTING OPTIONS: prioritize flatter, less steep streets
    # -----------------------------------------------------------
    costing_options = {
        "pedestrian": {
            "use_hills": 0.0,        # avoid hills as much as possible
            "use_roads": 0.3,
            "use_tracks": 0.3,
            "hill_penalty": 15.0,
            "safety_factor": 1.0
        }
    }

    # -----------------------------------------------------------
    # Valhalla route request
    # -----------------------------------------------------------
    result = valhalla_route(
        start,
        end,
        costing="pedestrian",
        costing_options=costing_options
    )

    if "trip" not in result:
        return {"error": "Valhalla elevation route failed."}

    leg = result["trip"]["legs"][0]
    poly_str = leg["shape"]

    # Decode polyline → list of (lat, lon)
    coords = polyline.decode(poly_str)

    # -----------------------------------------------------------
    # Proper elevation endpoint (using your server)
    # -----------------------------------------------------------
    elevations = []
    try:
        elev_url = f"{VALHALLA_URL}/height"
        payload = {"shape": [{"lat": lat, "lon": lon} for lat, lon in coords]}
        elev_js = requests.post(elev_url, json=payload, timeout=5).json()

        elevations = [p["height"] for p in elev_js.get("shape", [])]

    except Exception as e:
        print("Elevation error:", e)
        elevations = []

    # -----------------------------------------------------------
    # Compute average slope penalty
    # -----------------------------------------------------------
    penalties = []
    for i in range(len(elevations) - 1):
        delta = elevations[i+1] - elevations[i]
        penalties.append(1 + abs(delta) * 0.05)

    avg_penalty = round(sum(penalties) / max(1, len(penalties)), 3)

    # -----------------------------------------------------------
    # RETURN (correct backend contract)
    # -----------------------------------------------------------
    return {
        "mode": "elevation",
        "coordinates": coords,              # ⭐ REQUIRED
        "elevations": elevations,
        "avg_slope_penalty": avg_penalty,
        "summary": result["trip"]["summary"]
    }
