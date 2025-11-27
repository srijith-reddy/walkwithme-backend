from backend.valhalla_client import valhalla_route
from datetime import datetime
import requests
import polyline


# ============================================================
# Weather (affects explore vibe)
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
# Day/Night detection
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
# EXPLORE ROUTE (Valhalla)
# ============================================================
def get_explore_route(start, end):

    if not start or not end:
        return {"error": "Missing start or end."}

    lat1, lon1 = start

    # Weather + time influences explore style
    weather = get_weather(lat1, lon1)
    night = is_night(lat1, lon1)

    # -----------------------------------------------------------------
    # COSTING OPTIONS — tuned for exploration
    # -----------------------------------------------------------------
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

    if night:
        explore_cost["pedestrian"]["use_tracks"] = 0.0
        explore_cost["pedestrian"]["use_lit"] = 1.2

    # -----------------------------------------------------------------
    # VALHALLA CALL
    # -----------------------------------------------------------------
    result = valhalla_route(
        start,
        end,
        costing="pedestrian",
        costing_options=explore_cost
    )

    if "trip" not in result:
        return {"error": "Valhalla failed explore route."}

    leg = result["trip"]["legs"][0]
    poly_str = leg["shape"]

    # ⭐ DECODE polyline to coordinates list (lat, lon)
    coords = polyline.decode(poly_str)

    return {
        "mode": "explore",
        "weather": weather,
        "night": night,
        "coordinates": coords,     # ⭐ REQUIRED
        "summary": result["trip"]["summary"]
    }
