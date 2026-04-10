# backend/routing_explore.py

import polyline
from backend.valhalla_client import valhalla_route
from backend.utils.common import (
    simplify_waypoints,
    compute_next_turn,
    parse_maneuvers,
    get_weather_and_night,
)


def get_explore_route(start: tuple, end: tuple) -> dict:
    lat, lon = start
    weather, night = get_weather_and_night(lat, lon)

    costing_options = {
        "pedestrian": {
            "use_roads": 0.1,
            "use_tracks": 0.6,
            "use_hills": 0.4,
            "use_lit": 0.6,
            "alley_factor": 1.4,
            "walkway_factor": 0.5,
        }
    }

    if weather in ("rain", "snow", "cold"):
        costing_options["pedestrian"]["use_tracks"] = 0.2

    if night:
        costing_options["pedestrian"]["use_tracks"] = 0.0
        costing_options["pedestrian"]["use_lit"] = 1.2

    result = valhalla_route(start, end, costing="pedestrian", costing_options=costing_options)

    if "trip" not in result:
        return {"error": result.get("error", "Valhalla failed explore route.")}

    leg = result["trip"]["legs"][0]
    summary = result["trip"]["summary"]
    coords = polyline.decode(leg["shape"], precision=6)
    steps = parse_maneuvers(leg)

    return {
        "mode": "explore",
        "weather": weather,
        "night": night,
        "coordinates": coords,
        "waypoints": simplify_waypoints(coords),
        "steps": steps,
        "next_turn": compute_next_turn(steps, coords),
        "distance_m": round(summary.get("length", 0) * 1000),
        "duration_s": int(summary.get("time", 0)),
    }
