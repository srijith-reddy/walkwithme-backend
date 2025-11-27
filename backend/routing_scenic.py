from backend.valhalla_client import valhalla_route
from backend.utils.landuse_scoring import compute_scores_from_valhalla
import polyline
import math


# -------------------------------------------------------------
# SIMPLE WAYPOINT REDUCER (for AR)
# -------------------------------------------------------------
def simplify_waypoints(coords, step=5):
    return coords[::step] if len(coords) > step else coords


# -------------------------------------------------------------
# NEXT TURN LOGIC (same as shortest)
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

    # fallback — straight bearing
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
# MAIN: SCENIC ROUTE
# -------------------------------------------------------------
def get_scenic_route(start, end):

    if not start or not end:
        return {"error": "Start and end coordinates required."}

    candidates = []

    # Base route
    try:
        r1 = valhalla_route(start, end, costing="pedestrian")
        candidates.append(("base", r1))
    except:
        pass

    lat2, lon2 = end

    # Park-biased nudge
    try:
        r2 = valhalla_route(start, (lat2 + 0.0007, lon2 + 0.0007), costing="pedestrian")
        candidates.append(("park", r2))
    except:
        pass

    # Water-biased nudge
    try:
        r3 = valhalla_route(start, (lat2 - 0.0007, lon2 - 0.0007), costing="pedestrian")
        candidates.append(("water", r3))
    except:
        pass

    if not candidates:
        return {"error": "Valhalla failed to compute scenic routes."}

    scored = []

    # ---------------------------------------------------------
    # SCORE EACH CANDIDATE ROUTE
    # ---------------------------------------------------------
    for label, route_json in candidates:
        try:
            scores = compute_scores_from_valhalla(route_json)

            # weighted final scenic score
            final_score = (
                0.5 * scores["scenic"] +
                0.3 * scores["green"] +
                0.2 * scores["water"]
            )

            # decode polyline6
            shape = route_json["trip"]["legs"][0]["shape"]
            coords = polyline.decode(shape, precision=6)

            scored.append((final_score, label, coords, scores, route_json))

        except Exception as e:
            print("Scenic scoring failed", e)
            continue

    if not scored:
        return {"error": "Scoring failed for all routes."}

    # ---------------------------------------------------------
    # PICK BEST SCENIC ROUTE
    # ---------------------------------------------------------
    best_score, best_label, best_coords, best_scores, best_route_json = \
        max(scored, key=lambda x: x[0])

    leg = best_route_json["trip"]["legs"][0]
    summary = best_route_json["trip"]["summary"]

    # ---------------------------------------------------------
    # MANEUVERS → TURN BY TURN STEPS
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
    # WAYPOINTS (Option A — from best_coords only)
    # ---------------------------------------------------------
    waypoints = simplify_waypoints(best_coords, step=5)

    # ---------------------------------------------------------
    # NEXT TURN
    # ---------------------------------------------------------
    next_turn = compute_next_turn(steps, best_coords)

    # ---------------------------------------------------------
    # FINAL GOLD STANDARD JSON
    # ---------------------------------------------------------
    return {
        "mode": "scenic",
        "variant": best_label,

        "coordinates": best_coords,     # full polyline
        "waypoints": waypoints,         # simplified path for AR

        "steps": steps,
        "next_turn": next_turn,

        "distance_m": summary.get("length", 0) * 1000,
        "duration_s": summary.get("time", 0),
        "summary": summary,

        "scenic_score": float(best_score),
        "green_score": float(best_scores["green"]),
        "water_score": float(best_scores["water"]),
        "scenic_detail": float(best_scores["scenic"]),

        # optional scoring for AI Best mode
        "safety_score": 0.82,
        "ai_best_score": 0.90,
    }
