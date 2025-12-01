from backend.valhalla_client import valhalla_route
from datetime import datetime
import requests
import polyline
import math


# -------------------------------------------------------------
# CHECK DAY/NIGHT
# -------------------------------------------------------------
def is_night(lat, lon):
    try:
        url = f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&formatted=0"
        data = requests.get(url, timeout=5).json()["results"]

        sunrise = datetime.fromisoformat(data["sunrise"])   # tz-aware
        sunset  = datetime.fromisoformat(data["sunset"])    # tz-aware
        now = datetime.utcnow().astimezone()                # convert to local timezone

        # Convert sunrise/sunset to local timezone
        sunrise_local = sunrise.astimezone(now.tzinfo)
        sunset_local  = sunset.astimezone(now.tzinfo)

        return not (sunrise_local <= now <= sunset_local)

    except Exception as e:
        print("sunrise API failed:", e)
        # Fallback: assume night after 7 PM local time
        hour = datetime.now().hour
        return hour < 6 or hour > 19


# -------------------------------------------------------------
# SIMPLE AR WAYPOINT REDUCER
# -------------------------------------------------------------
def simplify_waypoints(coords, step=5):
    return coords[::step] if len(coords) > step else coords


# -------------------------------------------------------------
# TURN LOGIC
# -------------------------------------------------------------
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

    # fallback: straight bearing
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


# -------------------------------------------------------------
# MAIN SAFE ROUTE
# -------------------------------------------------------------
def get_safe_route(start, end, mode="auto"):

    # Determine profile automatically
    if mode == "auto":
        mode = "night" if is_night(*start) else "day"

    # ---------------------------------------------------------
    # COSTING PROFILES
    # ---------------------------------------------------------
    if mode == "day":
        costing_options = {
            "pedestrian": {
                "use_roads": 0.2,
                "use_tracks": 0.2,
                "use_hills": 0.3,
                "use_lit": 0.4,
                "safety_factor": 0.7
            }
        }
        safety_score = 0.75

    else:  # night
        costing_options = {
            "pedestrian": {
                "use_lit": 1.5,
                "alley_factor": 8.0,
                "use_roads": 0.1,
                "use_tracks": 0.0,
                "safety_factor": 1.3
            }
        }
        safety_score = 0.90  # night score higher relevance

    # ---------------------------------------------------------
    # CALL VALHALLA
    # ---------------------------------------------------------
    result = valhalla_route(
        start,
        end,
        costing="pedestrian",
        costing_options=costing_options
    )

    if "trip" not in result:
        return {"error": "Valhalla failed safe route."}

    leg = result["trip"]["legs"][0]
    summary = result["trip"]["summary"]

    # ---------------------------------------------------------
    # POLYLINE6 → COORDS
    # ---------------------------------------------------------
    shape = leg["shape"]
    coords = polyline.decode(shape, precision=6)

    # ---------------------------------------------------------
    # STEPS / MANEUVERS
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
    # FINAL GOLD STANDARD JSON
    # ---------------------------------------------------------
    return {
        "mode": f"safe_{mode}",

        "coordinates": coords,
        "waypoints": waypoints,

        "steps": steps,
        "next_turn": next_turn,

        "distance_m": summary.get("length", 0) * 1000,
        "duration_s": summary.get("time", 0),

        "summary": summary,

        "safety_score": safety_score,
        "ai_best_score": 0.88,   # placeholder for AI mode
    }
