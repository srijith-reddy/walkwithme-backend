from backend.valhalla_client import valhalla_route
from datetime import datetime
import requests


def is_night(lat, lon):
    try:
        url = f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&formatted=0"
        data = requests.get(url, timeout=5).json()["results"]
        sunrise = datetime.fromisoformat(data["sunrise"])
        sunset  = datetime.fromisoformat(data["sunset"])
        now = datetime.utcnow()
        return not (sunrise <= now <= sunset)
    except:
        return False


def get_safe_route(start, end, mode="auto"):

    # Auto-determine day/night
    if mode == "auto":
        mode = "night" if is_night(*start) else "day"

    # ============================
    # DAY SAFETY PROFILE
    # ============================
    if mode == "day":
        costing_options = {
            "pedestrian": {
                "use_roads": 0.2,        # avoid primary/secondary
                "use_tracks": 0.2,       # avoid dirt paths unless necessary
                "use_hills": 0.3,        # avoid steep slopes
                "use_lit": 0.4,          # prefer lit paths but less strict
                "safety_factor": 0.7     # general safety weight
            }
        }

    # ============================
    # NIGHT SAFETY PROFILE
    # ============================
    else:
        costing_options = {
            "pedestrian": {
                "use_lit": 1.5,          # very strong preference for lit areas
                "alley_factor": 8.0,     # avoid alleys HARD
                "use_roads": 0.1,        # avoid big roads even more
                "use_tracks": 0.0,       # avoid trails at night
                "safety_factor": 1.3     # boost safety scoring
            }
        }

    # ============================
    # Valhalla Routing Call
    # ============================
    result = valhalla_route(
        start,
        end,
        costing="pedestrian",
        costing_options=costing_options
    )

    if "trip" not in result:
        return {"error": "Valhalla failed safe route."}

    return {
        "mode": f"safe_{mode}",
        "coordinates_polyline": result["trip"]["legs"][0]["shape"],
        "summary": result["trip"]["summary"]
    }
