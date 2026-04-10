# backend/routing_shortest.py

import polyline
from backend.valhalla_client import valhalla_route
from backend.utils.common import simplify_waypoints, compute_next_turn, parse_maneuvers


def get_shortest_route(start: tuple, end: tuple) -> dict:
    result = valhalla_route(start, end, costing="pedestrian")

    if "trip" not in result:
        return {"error": result.get("error", "No route found from Valhalla.")}

    leg = result["trip"]["legs"][0]
    summary = result["trip"]["summary"]
    coords = polyline.decode(leg["shape"], precision=6)
    steps = parse_maneuvers(leg)

    return {
        "mode": "shortest",
        "coordinates": coords,
        "waypoints": simplify_waypoints(coords),
        "steps": steps,
        "next_turn": compute_next_turn(steps, coords),
        "distance_m": round(summary.get("length", 0) * 1000),
        "duration_s": int(summary.get("time", 0)),
    }
