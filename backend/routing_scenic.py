# backend/routing_scenic.py

from backend.valhalla_client import valhalla_route
from backend.utils.landuse_scoring import compute_green_score, compute_water_score


def get_scenic_route(start, end):
    """
    Scenic routing using Valhalla.
    Strategy:
        1. Generate multiple Valhalla routes with slight endpoint nudges
        2. Score each route on greenery + water
        3. Choose the highest-scoring one
    """

    if not start or not end:
        return {"error": "Start and end coordinates required."}

    candidates = []

    # ------------------------
    # Base route
    # ------------------------
    try:
        r1 = valhalla_route(start, end, costing="pedestrian")
        coords = r1["trip"]["legs"][0]["shape"]
        candidates.append(("base", coords))
    except:
        pass

    lat2, lon2 = end

    # ------------------------
    # Park-biased
    # ------------------------
    try:
        park_end = (lat2 + 0.0007, lon2 + 0.0007)
        r2 = valhalla_route(start, park_end, costing="pedestrian")
        coords = r2["trip"]["legs"][0]["shape"]
        candidates.append(("park", coords))
    except:
        pass

    # ------------------------
    # Water-biased
    # ------------------------
    try:
        water_end = (lat2 - 0.0007, lon2 - 0.0007)
        r3 = valhalla_route(start, water_end, costing="pedestrian")
        coords = r3["trip"]["legs"][0]["shape"]
        candidates.append(("water", coords))
    except:
        pass

    if not candidates:
        return {"error": "Valhalla failed to compute scenic routes."}

    # ------------------------
    # Score routes
    # ------------------------
    scored = []
    for label, polyline in candidates:
        # decode valhalla polyline
        import polyline
        coords = polyline.decode(polyline)

        green = compute_green_score(coords)
        water = compute_water_score(coords)

        total_score = 0.6 * green + 0.4 * water
        scored.append((total_score, label, polyline))

    # ------------------------
    # Return highest scoring
    # ------------------------
    best_score, best_label, best_polyline = max(scored, key=lambda x: x[0])

    return {
        "mode": "scenic",
        "variant": best_label,
        "scenic_score": float(best_score),
        "coordinates_polyline": best_polyline,
    }
