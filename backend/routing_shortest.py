from backend.valhalla_client import valhalla_route
import polyline
import math


def simplify_waypoints(coords, step=5):
    """
    Reduce coordinate list for AR navigation.
    Example: take every 5th point.
    """
    return coords[::step] if len(coords) > step else coords


def compute_next_turn(steps, coords):
    """
    Extract next turn instruction from Valhalla steps.
    If steps not available, fallback to simple bearing logic.
    """

    if steps and len(steps) > 0:
        next_step = steps[0]

        return {
            "type": next_step.get("type", "straight"),
            "instruction": next_step.get("instruction", ""),
            "distance_m": next_step.get("length", 0),
            "lat": next_step.get("begin_shape_index", None),
            "lon": next_step.get("end_shape_index", None),
        }

    # Fallback: compute simple bearing
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


def get_shortest_route(start, end):
    """
    Uses Valhalla walking engine to compute shortest pedestrian route.
    """

    if not start or not end:
        return {"error": "Start and end coordinates required."}

    try:
        result = valhalla_route(start, end, costing="pedestrian")

        # ❌ No trip returned
        if "trip" not in result:
            return {"error": "No route found from Valhalla."}

        leg = result["trip"]["legs"][0]
        summary = result["trip"]["summary"]

        # ⭐ Decode polyline6 (IMPORTANT)
        coords = polyline.decode(leg["shape"], precision=6)

        # ⭐ Extract steps if available
        steps = []
        if "maneuvers" in leg:
            for m in leg["maneuvers"]:
                steps.append({
                    "instruction": m.get("instruction", ""),
                    "type": m.get("type", ""),
                    "length": m.get("length", 0),
                    "begin_lat": m.get("begin_shape_index", None),
                    "end_lat": m.get("end_shape_index", None)
                })

        # ⭐ Simplified nodes for AR path
        waypoints = simplify_waypoints(coords, step=5)

        # ⭐ Next turn logic
        next_turn = compute_next_turn(steps, coords)

        return {
            "mode": "shortest",

            # full polyline for map
            "coordinates": coords,

            # AR waypoints
            "waypoints": waypoints,

            # Summary numbers
            "distance_m": summary.get("length", 0) * 1000,
            "duration_s": summary.get("time", 0),

            "summary": summary,

            # turn-by-turn
            "steps": steps,
            "next_turn": next_turn,

            # AI placeholder scores (optional)
            "safety_score": 0.82,
            "scenic_score": 0.71,
            "ai_best_score": 0.90,
        }

    except Exception as e:
        return {
            "error": f"Valhalla routing failed: {str(e)}",
            "suggest": [
                "Try another start or end point.",
                "Check Valhalla server status.",
                "Ensure coordinates are valid lat/lon."
            ]
        }
