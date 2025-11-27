from backend.valhalla_client import valhalla_route
from backend.utils.landuse_scoring import compute_scores_from_valhalla
import polyline

def get_scenic_route(start, end):
    if not start or not end:
        return {"error": "Start and end coordinates required."}

    candidates = []

    # Base
    try:
        r1 = valhalla_route(start, end, costing="pedestrian")
        candidates.append(("base", r1))
    except:
        pass

    lat2, lon2 = end

    # Nudges
    try:
        park_end = (lat2 + 0.0007, lon2 + 0.0007)
        r2 = valhalla_route(start, park_end, costing="pedestrian")
        candidates.append(("park", r2))
    except:
        pass

    try:
        water_end = (lat2 - 0.0007, lon2 - 0.0007)
        r3 = valhalla_route(start, water_end, costing="pedestrian")
        candidates.append(("water", r3))
    except:
        pass

    if not candidates:
        return {"error": "Valhalla failed to compute scenic routes."}

    scored = []
    for label, route_json in candidates:
        try:
            scores = compute_scores_from_valhalla(route_json)

            final_score = (
                0.5 * scores["scenic"] +
                0.3 * scores["green"] +
                0.2 * scores["water"]
            )

            # polyline
            poly_str = route_json["trip"]["legs"][0]["shape"]

            # decode polyline → list of [lat, lon]
            coords = polyline.decode(poly_str)

            scored.append((final_score, label, coords, scores))
        except Exception as e:
            print("Scoring failed:", e)
            continue

    if not scored:
        return {"error": "Scoring failed for all routes."}

    best_score, best_label, best_coords, best_scores = max(scored, key=lambda x: x[0])

    return {
        "mode": "scenic",
        "variant": best_label,
        "scenic_score": float(best_score),
        "green": float(best_scores["green"]),
        "water": float(best_scores["water"]),
        "scenic_detail": float(best_scores["scenic"]),
        "coordinates": best_coords,          # ⭐ REQUIRED
    }
