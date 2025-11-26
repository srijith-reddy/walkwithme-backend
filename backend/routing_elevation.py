from backend.valhalla_client import valhalla_route
import polyline


# ============================================================
# Elevation-Friendly Routing using Valhalla
# ============================================================
def get_elevation_route(start, end):

    if not start or not end:
        return {"error": "Missing start or end"}

    # -----------------------------------------------------------
    # COSTING OPTIONS: prioritize flatter, less steep streets
    # -----------------------------------------------------------
    costing_options = {
        "pedestrian": {
            "use_hills": 0.0,        # avoid hills as much as possible
            "use_roads": 0.3,        # slight preference for roads over trails
            "use_tracks": 0.3,       # avoid rough terrain
            "hill_penalty": 15.0,    # strong penalty for steep slopes
            "safety_factor": 1.0
        }
    }

    # -----------------------------------------------------------
    # Valhalla route request
    # -----------------------------------------------------------
    result = valhalla_route(
        start,
        end,
        costing="pedestrian",
        costing_options=costing_options
    )

    if "trip" not in result:
        return {"error": "Valhalla elevation route failed."}

    leg = result["trip"]["legs"][0]
    shape_polyline = leg["shape"]

    # Decode to get raw coords (for front-end visualization)
    coords = polyline.decode(shape_polyline)

    # -----------------------------------------------------------
    # Extract Valhalla-provided elevation samples
    # -----------------------------------------------------------
    elevations = []

    for edge in leg.get("maneuvers", []):
        # Valhalla includes elevation samples inside shape points
        pts = edge.get("begin_shape_index"), edge.get("end_shape_index")
        # but not height directly — use the edge-level metadata
        pass

    # BUT: easier way — Valhalla's `elevation.at` endpoint (built-in)
    # Each server provides elevation automatically for shape points.
    # (Valhalla uses DEM internally so results are instant)
    import requests
    try:
        url = f"http://localhost:8002/elevation?shape={shape_polyline}"
        elev_js = requests.get(url, timeout=5).json()
        elevations = [pt["height"] for pt in elev_js.get("shape", [])]
    except:
        elevations = []

    # -----------------------------------------------------------
    # Compute average slope penalty
    # -----------------------------------------------------------
    penalties = []
    for i in range(len(elevations) - 1):
        up = elevations[i]
        dn = elevations[i+1]

        delta = dn - up
        pen = 1 + abs(delta) * 0.05     # mild penalty
        penalties.append(pen)

    avg_penalty = round(sum(penalties) / max(1, len(penalties)), 3)

    return {
        "mode": "elevation",
        "start": start,
        "end": end,
        "coordinates_polyline": shape_polyline,
        "coordinates": coords,
        "elevations": elevations,
        "avg_slope_penalty": avg_penalty,
        "summary": result["trip"]["summary"]
    }
