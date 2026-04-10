# backend/walks.py
#
# Unexplored city — client-driven street coverage analysis.
#
# Design: no server-side user storage required.
# The iOS app stores walked route coordinates locally and sends them
# to these endpoints for analysis. The backend does the computation;
# the client holds the data.
#
# This means:
#   - No auth system needed for v1
#   - No database dependency
#   - Works offline-first — client can batch upload when connected
#
# When you add user accounts, move storage server-side and these
# endpoints become stateful. The analysis logic stays the same.

import math
from backend.utils.common import haversine, coords_bbox


# ---------------------------------------------------------------------------
# Street segment hashing
# ---------------------------------------------------------------------------
# We discretize the world into ~20m × 20m grid cells.
# A "walked segment" is a set of cells traversed.
# Coverage = unique cells walked / total cells in the city bbox.
#
# Grid resolution: 0.0002 degrees ≈ 22m at the equator.

GRID_RES = 0.0002


def _coord_to_cell(lat: float, lon: float) -> tuple[int, int]:
    return (int(lat / GRID_RES), int(lon / GRID_RES))


def _cells_for_route(coords: list[tuple]) -> set[tuple]:
    """Return the set of grid cells traversed by a route."""
    cells: set = set()
    for lat, lon in coords:
        cells.add(_coord_to_cell(lat, lon))
    # Also interpolate between consecutive points (handles sparse coords)
    for i in range(len(coords) - 1):
        lat1, lon1 = coords[i]
        lat2, lon2 = coords[i + 1]
        dist_m = haversine(lat1, lon1, lat2, lon2) * 1000
        if dist_m < 5:
            continue
        steps = max(2, int(dist_m / 15))
        for s in range(steps):
            t = s / steps
            ilat = lat1 + t * (lat2 - lat1)
            ilon = lon1 + t * (lon2 - lon1)
            cells.add(_coord_to_cell(ilat, ilon))
    return cells


# ---------------------------------------------------------------------------
# Coverage analysis
# ---------------------------------------------------------------------------
def analyze_coverage(
    walked_routes: list[list[tuple]],
    city_bbox: dict | None = None,
) -> dict:
    """
    Given a list of walked routes (each a list of (lat, lon) tuples),
    compute street coverage statistics.

    city_bbox: {"min_lat": ..., "max_lat": ..., "min_lon": ..., "max_lon": ...}
    If not provided, derived from walked routes.

    Returns:
        walked_cells:    number of unique ~20m grid cells walked
        total_cells:     total walkable cells in the bounding area
        coverage_pct:    percentage of the area covered
        walked_km:       approximate total distance walked
        unique_km:       approximate unique distance (deduped)
    """
    if not walked_routes:
        return _empty_coverage()

    all_walked_cells: set = set()
    total_walked_km = 0.0

    for route in walked_routes:
        if len(route) < 2:
            continue
        cells = _cells_for_route(route)
        all_walked_cells.update(cells)
        for i in range(len(route) - 1):
            total_walked_km += haversine(
                route[i][0], route[i][1], route[i+1][0], route[i+1][1]
            )

    # Derive bounding box
    if city_bbox is None:
        all_coords = [pt for route in walked_routes for pt in route]
        city_bbox = coords_bbox(all_coords, buffer_deg=0.01)

    # Estimate total walkable cells in bbox
    lat_span = city_bbox["max_lat"] - city_bbox["min_lat"]
    lon_span = city_bbox["max_lon"] - city_bbox["min_lon"]
    total_cells = max(1, int((lat_span / GRID_RES) * (lon_span / GRID_RES)))

    walked = len(all_walked_cells)
    coverage_pct = round(min(100.0, walked / total_cells * 100), 2)

    # Approximate unique distance: each cell ≈ 20m
    unique_km = round(walked * 0.020, 2)

    return {
        "walked_cells": walked,
        "total_cells": total_cells,
        "coverage_pct": coverage_pct,
        "total_walked_km": round(total_walked_km, 2),
        "unique_km": unique_km,
        "route_count": len(walked_routes),
    }


def _empty_coverage() -> dict:
    return {
        "walked_cells": 0, "total_cells": 0,
        "coverage_pct": 0.0, "total_walked_km": 0.0,
        "unique_km": 0.0, "route_count": 0,
    }


# ---------------------------------------------------------------------------
# Unexplored area suggestions
# ---------------------------------------------------------------------------
def suggest_unexplored(
    walked_routes: list[list[tuple]],
    center_lat: float,
    center_lon: float,
    radius_m: int = 1500,
    n_suggestions: int = 3,
) -> list[dict]:
    """
    Find areas near `center` that the user hasn't walked through yet.

    Returns a list of (lat, lon, label) points that could form the basis
    of a new route or loop — areas in the grid that haven't been visited.
    """
    if not walked_routes:
        return []

    walked_cells: set = set()
    for route in walked_routes:
        walked_cells.update(_cells_for_route(route))

    # Grid search around center
    radius_cells = int(radius_m / (GRID_RES * 111_000)) + 1
    center_cell = _coord_to_cell(center_lat, center_lon)
    cx, cy = center_cell

    # Collect unwalked cells, grouped into coarse clusters
    unwalked: list[tuple] = []
    for dx in range(-radius_cells, radius_cells + 1):
        for dy in range(-radius_cells, radius_cells + 1):
            cell = (cx + dx, cy + dy)
            if cell not in walked_cells:
                # Convert back to lat/lon (cell center)
                lat = (cell[0] + 0.5) * GRID_RES
                lon = (cell[1] + 0.5) * GRID_RES
                dist_m = haversine(center_lat, center_lon, lat, lon) * 1000
                if dist_m <= radius_m:
                    unwalked.append((lat, lon, dist_m))

    if not unwalked:
        return []

    # Cluster into sectors (N/NE/E/SE/S/SW/W/NW) and pick the best from each
    def sector(lat, lon):
        bearing = math.degrees(math.atan2(lon - center_lon, lat - center_lat)) % 360
        return int(bearing / 45)

    by_sector: dict[int, list] = {}
    for lat, lon, dist_m in unwalked:
        s = sector(lat, lon)
        if s not in by_sector:
            by_sector[s] = []
        by_sector[s].append((lat, lon, dist_m))

    suggestions = []
    for s, cells in sorted(by_sector.items()):
        # Pick the cell at roughly 60% of max radius — interesting but reachable
        target = radius_m * 0.6
        best = min(cells, key=lambda c: abs(c[2] - target))
        suggestions.append({
            "lat": round(best[0], 5),
            "lon": round(best[1], 5),
            "distance_from_you_m": int(best[2]),
            "direction": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][s],
            "label": f"Unexplored area {int(best[2])}m {['N','NE','E','SE','S','SW','W','NW'][s]}",
        })
        if len(suggestions) >= n_suggestions:
            break

    return suggestions
