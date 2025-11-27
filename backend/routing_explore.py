from backend.valhalla_client import valhalla_route
from datetime import datetime
import requests
import polyline
import math


# ============================================================
# WEATHER (affects explore vibe)
# ============================================================
def get_weather(lat, lon):
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current_weather=true"
        )
        w = requests.get(url, timeout=5).json()["current_weather"]
        code = int(w["weathercode"])
        temp = float(w["temperature"])

        if code in [61, 63, 65]: return "rain"
        if code in [71, 73, 75]: return "snow"
        if temp > 30: return "hot"
        if temp < 5:  return "cold"
        return "clear"
    except:
        return "clear"


# ============================================================
# DAY/NIGHT DETECTOR
# ============================================================
def is_night(lat, lon):
    try:
        url = f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&formatted=0"
        r = requests.get(url, timeout=5).json()["results"]
        sunrise = datetime.fromisoformat(r["sunrise"])
        sunset  = datetime.fromisoformat(r["sunset"])
        now = datetime.utcnow()
        return not (sunrise <= now <= sunset)
    except:
        return False


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

    # fallback bearing
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
# EXPLORE ROUTE
# ============================================================
def get_explore_route(start, end):

    if not start or not end:
        return {"error": "Missing start or end."}

    lat1, lon1 = start

    # Weather + time-of-day influence
    weather = get_weather(lat1, lon1)
    night = is_night(lat1, lon1)

    # ---------------------------------------------------------
    # COSTING PROFILE
    # ---------------------------------------------------------
    explore_cost = {
        "pedestrian": {
            "use_roads": 0.1,
            "use_tracks": 0.6,
            "use_hills": 0.4,
            "use_lit": 0.6,
            "alley_factor": 1.4,
            "safety_factor": 0.9,
            "walkway_factor": 0.5
        }
    }

    # Weather adjustments
    if weather in ["rain", "snow", "cold"]:
        explore_cost["pedestrian"]["use_tracks"] = 0.2

    # Night adjustments
    if night:
        explore_cost["pedestrian"]["use_tracks"] = 0.0
        explore_cost["pedestrian"]["use_lit"] = 1.2

    # ---------------------------------------------------------
    # VALHALLA CALL
    # ---------------------------------------------------------
    result = valhalla_route(
        start,
        end,
        costing="pedestrian",
        costing_options=explore_cost
    )

    if "trip" not in result:
        return {"error": "Valhalla failed explore route."}

    leg = result["trip"]["legs"][0]
    summary = result["trip"]["summary"]

    # ---------------------------------------------------------
    # POLYLINE6 DECODE
    # ---------------------------------------------------------
    poly_str = leg["shape"]
    coords = polyline.decode(poly_str, precision=6)

    # ---------------------------------------------------------
    # STEPS
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    # WAYPOINTS FOR AR
    # ---------------------------------------------------------
    waypoints = simplify_waypoints(coords, step=5)

    # ---------------------------------------------------------
    # NEXT TURN
    # ---------------------------------------------------------
    next_turn = compute_next_turn(steps, coords)

    # ---------------------------------------------------------
    # FINAL GOLD JSON
    # ---------------------------------------------------------
    return {
        "mode": "explore",
        "weather": weather,
        "night": night,

        "coordinates": coords,
        "waypoints": waypoints,
        "steps": steps,
        "next_turn": next_turn,

        "distance_m": summary.get("length", 0) * 1000,
        "duration_s": summary.get("time", 0),
        "summary": summary,

        # AI scores (can be improved later)
        "scenic_score": 0.65,
        "safety_score": 0.78,
        "ai_best_score": 0.84,
    }
