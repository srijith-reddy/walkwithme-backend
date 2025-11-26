# backend/routing_scenic.py

from backend.valhalla_client import valhalla_route
from backend.utils.landuse_scoring import compute_scores_from_valhalla
import polyline


def get_scenic_route(start, end):
    """
    Scenic routing using Valhalla.
    Strategy:
        1. Compute multiple Valhalla routes with small nudges
        2. Score each route using Valhalla-based scenic scoring:
           - green score
           - water score
           - scenic score (surface + density + use)
        3. Return the highest-scoring one
    """

    if not start or not end:
        return {"error": "Start and end coordinates required."}

    candidates = []

    # ---------------------------------------
    # Base route
    # ---------------------------------------
    try:
        r1 = valhalla_route(start, end, costing="pedestrian")
        candidates.append(("base", r1))
    except Exception:
        pass

    lat2, lon2 = end

    # ---------------------------------------
    # Park-biased (nudged endpoint NE)
    # ---------------------------------------
    try:
        park_end = (lat2 + 0.0007, lon2 + 0.0007)
        r2 = valhalla_route(start, park_end, costing="pedestrian")
        candidates.append(("park", r2))
    except Exception:
        pass

    # ---------------------------------------
    # Water-biased (nudged endpoint SW)
    # ---------------------------------------
    try:
        water_end = (lat2 - 0.0007, lon2 - 0.0007)
        r3 = valhalla_route(start, water_end, costing="pedestrian")
        candidates.append(("water", r3))
    except Exception:
        pass

    if not candidates:
        return {"error": "Valhalla failed to compute scenic routes."}

    # ---------------------------------------
    # Score each route
    # ---------------------------------------
    scored = []
    for label, route_json in candidates:
        try:
            scores = compute_scores_from_valhalla(route_json)

            # scenic = combination of green + water + scenic metrics
            final_score = (
                0.5 * scores["scenic"] +
                0.3 * scores["green"] +
                0.2 * scores["water"]
            )

            # polyline for returning to frontend
            poly = route_json["trip"]["legs"][0]["shape"]

            scored.append((final_score, label, poly, scores))
        except Exception as e:
            print("Scoring failed:", e)
            continue

    if not scored:
        return {"error": "Scoring failed for all routes."}

    # pick highest-scoring route
    best_score, best_label, best_poly, best_scores = max(scored, key=lambda x: x[0])

    return {
        "mode": "scenic",
        "variant": best_label,
        "scenic_score": float(best_score),
        "green": float(best_scores["green"]),
        "water": float(best_scores["water"]),
        "scenic_detail": float(best_scores["scenic"]),
        "coordinates_polyline": best_poly,
    }
