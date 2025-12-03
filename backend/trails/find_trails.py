# backend/trails/find_trails.py

import requests
from shapely.geometry import Point, LineString, shape
from shapely.ops import transform
import pyproj

# Your Valhalla URL
VALHALLA_URL = "http://165.227.188.199:8002"


# ============================================================
# Helpers
# ============================================================

proj_to_m = pyproj.Transformer.from_crs(
    "EPSG:4326", "EPSG:3857", always_xy=True
).transform


def valhalla_isochrone(lat, lon, radius_m):
    """
    Calls /isochrone to get a polygon of all walkable edges.
    """
    payload = {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": "pedestrian",
        "contours": [{"time": radius_m / 80}],  # ~80m/min
        "polygons": True,
        "generalize": 20
    }
    try:
        r = requests.post(f"{VALHALLA_URL}/isochrone", json=payload, timeout=6)
        return r.json()
    except:
        return None


def valhalla_isochrone_edges(lat, lon, radius_m):
    """
    Uses isochrone → extract boundary → send to /trace_attributes
    to get ALL edges inside.
    """
    iso = valhalla_isochrone(lat, lon, radius_m)
    if not iso or "features" not in iso:
        return None

    # First feature = polygon
    poly = shape(iso["features"][0]["geometry"])

    # Sample boundary points to feed into trace_attributes
    boundary = list(poly.exterior.coords)

    shape_points = [
        {"lat": c[1], "lon": c[0]} for c in boundary[::10]
    ]
    if len(shape_points) < 2:
        return None

    payload = {
        "shape": shape_points,
        "costing": "pedestrian",
        "shape_match": "map_snap",
        "filters": {
            "attributes": ["edge.use", "edge.surface", "shape", "names"]
        }
    }

    try:
        r = requests.post(f"{VALHALLA_URL}/trace_attributes", json=payload, timeout=8)
        return r.json()
    except:
        return None


# ============================================================
# Simple trail logic using TRULY nearby edges (isochrone-based)
# ============================================================

def find_nearby_trails(lat, lon, radius=2000):
    """
    Finds REAL nearby trails using:
      1. /isochrone → walkable polygon
      2. /trace_attributes → edges inside polygon
    """

    data = valhalla_isochrone_edges(lat, lon, radius)
    if not data or "edges" not in data:
        return []

    edges = data["edges"]

    trails = []

    # Convert user point to projected meters
    user_pt = Point(lon, lat)
    user_pt_m = transform(proj_to_m, user_pt)

    for edge in edges:

        # Use SAME FILTER as your previous code
        if edge.get("use") not in ["pedestrian", "footway", "path", "trail"]:
            continue

        if "shape" not in edge:
            continue

        # Convert geometry: [(lon,lat)] format
        coords = [(pt[0], pt[1]) for pt in edge["shape"]]
        geom = LineString(coords)
        geom_m = transform(proj_to_m, geom)

        # Distance to user
        dist = user_pt_m.distance(geom_m)
        if dist > radius:
            continue

        trails.append({
            "properties": {
                "id": edge.get("id"),
                "name": (edge.get("names") or ["Unnamed"])[0],
                "surface": edge.get("surface", "unknown"),
                "highway": edge.get("use"),
            },
            "length_m": geom_m.length,
            "distance_from_user_m": dist,
            "coords": coords,

            # REQUIRED for trail_scorer
            "geometry": geom
        })

    return trails
