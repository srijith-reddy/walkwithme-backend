# backend/routing.py  (VALHALLA VERSION)

from backend.routing_shortest import get_shortest_route
from backend.routing_safe import get_safe_route
from backend.routing_scenic import get_scenic_route
from backend.routing_explore import get_explore_route
from backend.routing_ai import get_ai_best_route, get_ai_loop_route
from backend.routing_elevation import get_elevation_route

def get_route(start, end=None, mode="shortest", duration_minutes=20):
    """
    Unified routing entry for WALKR (Valhalla-based).

    Modes:
        - shortest
        - safe
        - scenic
        - explore
        - elevation
        - best
        - loop
    """

    if not start:
        return {"error": "Missing start coordinates."}

    # All modes except LOOP require an end coordinate
    if mode != "loop" and not end:
        return {"error": "Missing destination coordinates."}

    # ---------------------------
    # SHORTEST — Valhalla pedestrian
    # ---------------------------
    if mode == "shortest":
        return get_shortest_route(start, end)

    # ---------------------------
    # SAFE — Valhalla pedestrian w/ custom costing
    # ---------------------------
    if mode == "safe":
        return get_safe_route(start, end)

    # ---------------------------
    # SCENIC — parks, greenery, waterfront bias
    # ---------------------------
    if mode == "scenic":
        return get_scenic_route(start, end)

    # ---------------------------
    # EXPLORE — lively streets, food streets, cozy walking areas
    # ---------------------------
    if mode == "explore":
        return get_explore_route(start, end)

    # ---------------------------
    # ELEVATION — external elevation analytics + Valhalla geometry
    # ---------------------------
    if mode == "elevation":
        return get_elevation_route(start, end)

    # ---------------------------
    # AI-BEST — weather + time + day/night fused profile
    # ---------------------------
    if mode == "best":
        return get_ai_best_route(start, end)

    # ---------------------------
    # LOOP — Valhalla random loop
    # ---------------------------
    if mode == "loop":
        target_km = 5.0 
        return get_ai_loop_route(start, target_km=target_km)

    # ---------------------------
    # INVALID
    # ---------------------------
    return {
        "error": f"Invalid mode '{mode}'. Allowed: shortest, safe, scenic, explore, elevation, best, loop."
    }
