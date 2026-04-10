# backend/routing_safe.py

import polyline
from backend.valhalla_client import valhalla_route
from backend.utils.common import (
    simplify_waypoints,
    compute_next_turn,
    parse_maneuvers,
    is_night,
)

_DAY_COSTING = {
    "pedestrian": {
        "use_roads": 0.2,
        "use_tracks": 0.2,
        "use_hills": 0.3,
        "use_lit": 0.4,
    }
}

_NIGHT_COSTING = {
    "pedestrian": {
        "use_lit": 1.5,
        "alley_factor": 8.0,
        "use_roads": 0.1,
        "use_tracks": 0.0,
    }
}


def get_safe_route(start: tuple, end: tuple, mode: str = "auto") -> dict:
    if mode == "auto":
        mode = "night" if is_night(*start) else "day"

    costing_options = _NIGHT_COSTING if mode == "night" else _DAY_COSTING

    result = valhalla_route(start, end, costing="pedestrian", costing_options=costing_options)

    if "trip" not in result:
        return {"error": result.get("error", "Valhalla failed safe route.")}

    leg = result["trip"]["legs"][0]
    summary = result["trip"]["summary"]
    coords = polyline.decode(leg["shape"], precision=6)
    steps = parse_maneuvers(leg)

    return {
        "mode": f"safe_{mode}",
        "coordinates": coords,
        "waypoints": simplify_waypoints(coords),
        "steps": steps,
        "next_turn": compute_next_turn(steps, coords),
        "distance_m": round(summary.get("length", 0) * 1000),
        "duration_s": int(summary.get("time", 0)),
    }
