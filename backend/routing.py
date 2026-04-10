# backend/routing.py
# Unified routing dispatcher — delegates to mode-specific modules.

from backend.config import WALK_SPEED_KPH
from backend.routing_shortest import get_shortest_route
from backend.routing_safe import get_safe_route
from backend.routing_scenic import get_scenic_route
from backend.routing_explore import get_explore_route
from backend.routing_ai import get_ai_best_route, get_ai_loop_route
from backend.routing_elevation import get_elevation_route

ALLOWED_MODES = {"shortest", "safe", "scenic", "explore", "elevation", "best", "loop"}


def get_route(
    start: tuple,
    end: tuple | None = None,
    mode: str = "shortest",
    duration_minutes: int = 30,
    loop_theme: str = "scenic",
) -> dict:
    """
    Unified routing entry point.

    start:            (lat, lon)
    end:              (lat, lon) — required for all non-loop modes
    mode:             one of ALLOWED_MODES
    duration_minutes: used by loop mode to determine target distance
    loop_theme:       "scenic" | "explore" | "safe"
    """
    if not start:
        return {"error": "Missing start coordinates."}

    if mode not in ALLOWED_MODES:
        return {"error": f"Invalid mode '{mode}'. Allowed: {', '.join(sorted(ALLOWED_MODES))}"}

    if mode != "loop" and not end:
        return {"error": "Missing destination coordinates."}

    if mode == "shortest":
        return get_shortest_route(start, end)

    if mode == "safe":
        return get_safe_route(start, end)

    if mode == "scenic":
        return get_scenic_route(start, end)

    if mode == "explore":
        return get_explore_route(start, end)

    if mode == "elevation":
        return get_elevation_route(start, end)

    if mode == "best":
        return get_ai_best_route(start, end)

    if mode == "loop":
        # Convert walk duration to target distance: distance = speed × time
        target_km = (duration_minutes / 60.0) * WALK_SPEED_KPH
        target_km = max(0.5, round(target_km, 2))  # floor at 500m
        return get_ai_loop_route(start, target_km=target_km, theme=loop_theme)

    return {"error": "Unexpected routing error."}
