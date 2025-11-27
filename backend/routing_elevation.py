from backend.valhalla_client import valhalla_route, VALHALLA_URL
import polyline
import requests
import math


# ============================================================
# WAYPOINT REDUCER FOR AR
# ============================================================
def simplify_waypoints(coords, step=5):
    return coords[::step] if len(coords) > step else coords


# ============================================================
# NEXT TURN COMPUTATION
# ============================================================
def compute_next_turn(steps, coords):
    if steps and len(steps) > 0:
        m = steps[0]
        return {
            "type": m.get("type", ""),
            "instruction": m.get("instruction", ""),
            "distance_m": m.get("length", 0),
            "lat": m.get("begin_shape_index", None),
            "lon": m.get("end_shape_index", None),
        }

    # fallback: compute bearing
    if len(coords) >= 2:
        lat1, lon1 = coords[0]
        lat2, lon2 = coords[1]
        bearing = math.degrees(math.atan2(lon2 - lon1, lat2 - lat1))

        return {
            "type": "straight",
            "instruction": "Continue straight",
            "degrees": bearing,
            "distance_m": 5
        }

    return None


# ============================================================
# ELEVATION-FRIENDLY ROUTE
# ============================================================
def get_elevation_route(start, end):

    if not start or not end:
        return {"error": "Missing start or end"}

    # -----------------------------------------------------------
    # COSTING OPTIONS — avoid hills aggressively
    # -----------------------------------------------------------
    costing_options = {
        "pedestrian": {
            "use_hills": 0.0,          # avoid steep hills
            "hill_penalty": 15.0,
            "use_roads": 0.3,
            "use_tracks": 0.3,
            "safety_factor": 1.0
        }
    }

    # -----------------------------------------------------------
    # VALHALLA CALL
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
    summary = result["trip"]["summary"]
    poly_str = leg["shape"]

    # -----------------------------------------------------------
    # DECODE POLYLINE6
    # -----------------------------------------------------------
    coords = polyline.decode(poly_str, precision=6)

    # -----------------------------------------------------------
    # STEPS FOR TURN-BY-TURN
    # -----------------------------------------------------------
    steps = []
    if "maneuvers" in leg:
        for m in leg["maneuvers"]:
            steps.append({
                "instruction": m.get("instruction", ""),
                "type": m.get("type", ""),
                "length": m.get("length", 0),
                "begin_lat": m.get("begin_shape_index", None),
                "end_lat": m.get("end_shape_index", None),
            })

    # -----------------------------------------------------------
    # WAYPOINTS FOR AR
    # -----------------------------------------------------------
    waypoints = simplify_waypoints(coords, step=5)

    # -----------------------------------------------------------
    # NEXT TURN
    # -----------------------------------------------------------
    next_turn = compute_next_turn(steps, coords)

    # -----------------------------------------------------------
    # ELEVATION REQUEST
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
    # STATS: Gain / Loss / Slopes
    # -----------------------------------------------------------
    elevation_gain = 0
    elevation_loss = 0
    slopes = []

    for i in range(len(elevations) - 1):
        d = elevations[i+1] - elevations[i]
        if d > 0: elevation_gain += d
        else: elevation_loss += abs(d)

        slopes.append(d)

    # Difficulty scale
    if elevation_gain < 10:
        difficulty = "Easy"
    elif elevation_gain < 40:
        difficulty = "Moderate"
    else:
        difficulty = "Hard"

    # -----------------------------------------------------------
    # RETURN GOLD JSON
    # -----------------------------------------------------------
    return {
        "mode": "elevation",

        # ROUTE COORDS
        "coordinates": coords,
        "waypoints": waypoints,

        # TURNS
        "steps": steps,
        "next_turn": next_turn,

        # ELEVATION
        "elevations": elevations,
        "elevation_gain_m": round(elevation_gain, 2),
        "elevation_loss_m": round(elevation_loss, 2),
        "slopes": slopes,
        "max_slope_percent": max(slopes) if slopes else 0.0,
        "difficulty": difficulty,

        # SUMMARY
        "distance_m": summary.get("length", 0) * 1000,
        "duration_s": summary.get("time", 0),
        "summary": summary,

        # AI score placeholder
        "ai_best_score": 0.72,
    }
