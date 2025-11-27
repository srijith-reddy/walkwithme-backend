from backend.valhalla_client import valhalla_route
from datetime import datetime
import requests
import polyline


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

    # Auto day/night
    if mode == "auto":
        mode = "night" if is_night(*start) else "day"

    # ========== DAY PROFILE ==========
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

    # ========== NIGHT PROFILE ==========
    else:
        costing_options = {
            "pedestrian": {
                "use_lit": 1.5,
                "alley_factor": 8.0,
                "use_roads": 0.1,
                "use_tracks": 0.0,
                "safety_factor": 1.3
            }
        }

    # ========== CALL VALHALLA ==========
    result = valhalla_route(
        start,
        end,
        costing="pedestrian",
        costing_options=costing_options
    )

    if "trip" not in result:
        return {"error": "Valhalla failed safe route."}

    # polyline string
    poly_str = result["trip"]["legs"][0]["shape"]

    # decode → list of (lat, lon)
    coords = polyline.decode(poly_str)

    return {
        "mode": f"safe_{mode}",
        "coordinates": coords,     # ⭐ REQUIRED
        "summary": result["trip"]["summary"]
    }
