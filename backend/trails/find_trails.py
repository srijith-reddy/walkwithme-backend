# backend/trails/find_trails.py

import requests
from shapely.geometry import Point, LineString, shape
from shapely.ops import transform
import pyproj

VALHALLA_URL = "http://165.227.188.199:8002"

# -------------------------------------------------------------
# Projection helper (lat/lon → meters)
# -------------------------------------------------------------
proj_to_m = pyproj.Transformer.from_crs(
    "EPSG:4326", "EPSG:3857", always_xy=True
).transform


# -------------------------------------------------------------
# 1) Call /isochrone
# -------------------------------------------------------------
def valhalla_isochrone(lat, lon, radius_m):
    # Valhalla pedestrian ~4.5 km/h → 75 m/min (conservative)
    walking_speed_m_min = 200
    minutes = radius_m / walking_speed_m_min

    payload = {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": "pedestrian",
        "contours": [{"time": minutes}],
        "polygons": True,
        "generalize": 10
    }

    try:
        r = requests.post(f"{VALHALLA_URL}/isochrone", json=payload, timeout=8)
        return r.json()
    except:
        return None


# -------------------------------------------------------------
# 2) Isochrone → polygon → boundary → /trace_attributes
# -------------------------------------------------------------
def valhalla_isochrone_edges(lat, lon, radius_m):
    iso = valhalla_isochrone(lat, lon, radius_m)
    if not iso or "features" not in iso:
        return None

    # get polygon
    poly = shape(iso["features"][0]["geometry"])

    # DO NOT SKIP POINTS — or you lose edges!
    boundary = list(poly.exterior.coords)

    shape_points = [{"lat": y, "lon": x} for x, y in boundary]

    if len(shape_points) < 2:
        return None

    payload = {
        "shape": shape_points,
        "costing": "pedestrian",
        "shape_match": "map_snap",
        "filters": {
            "attributes": [
                "edge.id",
                "edge.use",
                "edge.surface",
                "edge.length",
                "names",
                "shape"
            ]
        }
    }

    try:
        r = requests.post(f"{VALHALLA_URL}/trace_attributes", json=payload, timeout=12)
        return r.json()
    except:
        return None


# -------------------------------------------------------------
# 3) Extract REAL trails from returned edges
# -------------------------------------------------------------
def find_nearby_trails(lat, lon, radius=12000):
    """
    AllTrails-style extraction:
      - /isochrone → walkable polygon
      - /trace_attributes → all edges
      - filter to walkable trail-like surfaces
    """
    data = valhalla_isochrone_edges(lat, lon, radius)
    if not data or "edges" not in data:
        return []

    edges = data["edges"]
    trails = []

    # project user coordinate
    user_pt_m = transform(proj_to_m, Point(lon, lat))

    # EXPANDED WALKABLE USES (critical fix)
    WALK_USES = {
        "pedestrian", "footway", "path", "trail",
        "track", "steps", "sidewalk",
        "residential", "service", "alley",
        "living_street", "parking_aisle"
    }

    for edge in edges:
        use = edge.get("use")
        if use not in WALK_USES:
            continue

        rawshape = edge.get("shape", [])
        if not rawshape:
            continue

        # Handle dict OR [lon,lat]
        coords = []
        for p in rawshape:
            if isinstance(p, dict):
                coords.append((p["lon"], p["lat"]))
            else:
                coords.append((p[0], p[1]))

        if len(coords) < 2:
            continue

        geom = LineString(coords)
        geom_m = transform(proj_to_m, geom)

        # distance from user to closest point on that line
        dist = user_pt_m.distance(geom_m)

        # Allow trails slightly beyond radius
        if dist > radius * 1.5:
            continue

        props = {
            "id": edge.get("id"),
            "name": (edge.get("names") or ["Unnamed"])[0],
            "surface": edge.get("surface", "unknown"),
            "highway": use
        }

        trails.append({
            "properties": props,
            "length_m": geom_m.length,
            "distance_from_user_m": dist,
            "coords": coords,
            "geometry": geom
        })

    return trails
