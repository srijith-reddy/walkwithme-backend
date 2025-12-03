# backend/trails/find_trails.py

import requests
from shapely.geometry import Point, LineString
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


def valhalla_locate(lat, lon):
    payload = {
        "locations": [{"lat": lat, "lon": lon}],
        "verbose": True
    }

    try:
        r = requests.post(f"{VALHALLA_URL}/locate", json=payload, timeout=3)
        return r.json()
    except:
        return None


# ============================================================
# Simple trail logic using Valhalla edges
# ============================================================

def find_nearby_trails(lat, lon, radius=2000):
    """
    Reads Valhalla /locate edges around the user and extracts
    only pedestrian/path/footway edges.
    """

    data = valhalla_locate(lat, lon)
    if not data:
        return []

    # -----------------------------------------------------------
    # Valhalla sometimes returns:
    #   { "edges": [...] }
    # OR
    #   [ { "edges": [...] } ]
    # -----------------------------------------------------------
    if isinstance(data, list):
        # use the first entry (we only passed one location)
        if len(data) > 0 and isinstance(data[0], dict):
            data = data[0]
        else:
            return []

    # If still not a dict → invalid
    if not isinstance(data, dict):
        return []

    edges = data.get("edges", [])

    trails = []

    # Convert user point to projected meters
    user_pt = Point(lon, lat)
    user_pt_m = transform(proj_to_m, user_pt)

    for edge in edges:

        # Filter for trail-type uses
        if edge.get("use") not in ["pedestrian", "footway", "path"]:
            continue

        if "shape" not in edge:
            continue

        # Lat/lon are in order [lon, lat] from Valhalla
        coords = [(c[0], c[1]) for c in edge["shape"]]

        geom = LineString(coords)
        geom_m = transform(proj_to_m, geom)

        # Distance to user
        dist = user_pt_m.distance(geom_m)
        if dist > radius:
            continue

        trails.append({
            "properties": {
                "id": edge.get("id"),
                "name": edge.get("names", ["Unnamed"])[0],
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
