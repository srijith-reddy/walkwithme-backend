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
    walking_speed_m_min = 250  # realistic pedestrian speed
    minutes = radius_m / walking_speed_m_min

    payload = {
        "locations": [{"lat": lat, "lon": lon}],
        "costing": "pedestrian",
        "contours": [{"time": minutes}],
        "polygons": True,
        "generalize": 20
    }

    try:
        r = requests.post(f"{VALHALLA_URL}/isochrone", json=payload, timeout=8)
        return r.json()
    except:
        return None


# -------------------------------------------------------------
# 2) Isochrone → polygon boundary → /trace_attributes
# -------------------------------------------------------------
def valhalla_isochrone_edges(lat, lon, radius_m):
    iso = valhalla_isochrone(lat, lon, radius_m)
    if not iso or "features" not in iso:
        return None

    poly = shape(iso["features"][0]["geometry"])
    boundary = list(poly.exterior.coords)

    # CRITICAL FIX: sample fewer points
    boundary = boundary[::25]

    # Build shape for trace attributes
    shape_points = [{"lat": y, "lon": x, "type": "break"} for x, y in boundary]

    if len(shape_points) < 2:
        return None

    payload = {
        "shape": shape_points,
        "costing": "pedestrian",

        # CRITICAL FIX: use walk_or_snap (works for polygons)
        "shape_match": "walk_or_snap",

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
# 3) Extract REAL nearby trails
# -------------------------------------------------------------
def find_nearby_trails(lat, lon, radius=160000):
    data = valhalla_isochrone_edges(lat, lon, radius)
    if not data or "edges" not in data:
        return []

    edges = data["edges"]
    trails = []

    user_pt = Point(lon, lat)
    user_pt_m = transform(proj_to_m, user_pt)

    WALK_USES = {
        "pedestrian", "footway", "path", "trail",
        "track", "steps", "sidewalk"
    }

    for edge in edges:
        use = edge.get("use")
        if use not in WALK_USES:
            continue

        rawshape = edge.get("shape", [])
        if not rawshape:
            continue

        # handle dict or [lon,lat]
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

        dist = user_pt_m.distance(geom_m)
        if dist > radius:
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
