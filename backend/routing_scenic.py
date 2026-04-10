# backend/routing_scenic.py
#
# Generates up to 3 candidate routes with slight destination nudges,
# scores them by landuse metadata, returns the most scenic one.

import polyline
from backend.valhalla_client import valhalla_route_many
from backend.utils.common import simplify_waypoints, compute_next_turn, parse_maneuvers
from backend.utils.landuse_scoring import compute_scores_from_valhalla


def get_scenic_route(start: tuple, end: tuple) -> dict:
    lat2, lon2 = end

    # Three candidates: direct + two small destination nudges
    jobs = [
        ("base",  start, end,                            "pedestrian", None),
        ("nudge1", start, (lat2 + 0.0007, lon2 + 0.0007), "pedestrian",
            {"pedestrian": {"use_roads": 0.2, "use_hills": 0.4}}),
        ("nudge2", start, (lat2 - 0.0007, lon2 + 0.0005), "pedestrian",
            {"pedestrian": {"use_roads": 0.2, "use_hills": 0.4}}),
    ]

    results = valhalla_route_many(jobs, max_workers=3)

    scored = []
    for label, route_json in results:
        if "trip" not in route_json:
            continue
        try:
            scores = compute_scores_from_valhalla(route_json)
            final_score = (
                0.5 * scores["scenic"] + 0.3 * scores["green"] + 0.2 * scores["water"]
            )
            leg = route_json["trip"]["legs"][0]
            summary = route_json["trip"]["summary"]
            coords = polyline.decode(leg["shape"], precision=6)
            scored.append((final_score, label, coords, scores, leg, summary))
        except Exception:
            continue

    if not scored:
        return {"error": "Scoring failed for all scenic candidates."}

    best_score, best_label, coords, scores, leg, summary = max(scored, key=lambda x: x[0])
    steps = parse_maneuvers(leg)

    return {
        "mode": "scenic",
        "variant": best_label,
        "coordinates": coords,
        "waypoints": simplify_waypoints(coords),
        "steps": steps,
        "next_turn": compute_next_turn(steps, coords),
        "distance_m": round(summary.get("length", 0) * 1000),
        "duration_s": int(summary.get("time", 0)),
        "scenic_score": round(float(best_score), 3),
        "green_score": round(float(scores["green"]), 3),
        "water_score": round(float(scores["water"]), 3),
    }
