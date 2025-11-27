# backend/trails/find_trails.py

import requests
from shapely.geometry import Point, LineString
from shapely.ops import transform
import pyproj

# Your Valhalla URL
VALHALLA_URL = "http://165.227.188.199:8002"  # change to your Fly.io endpoint


# ============================================================
# Helpers
# ============================================================

proj_to_m = pyproj.Transformer.from_crs(
    "EPSG:4326", "EPSG:3857", always_xy=True
).transform


def valhalla_locate(lat, lon):
    """
    Calls Valhalla's /locate API to get nearby edges.
    This is the replacement for your manual PBF parsing.
    """
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
    No files. No osmium. Uses Valhalla's own edge metadata.

    Strategy:
      1. Use /locate to find edges around user location.
      2. Filter edges where "use" = "pedestrian" or "path".
      3. Return them as "trails".
    """

    data = valhalla_locate(lat, lon)
    if not data:
        return []

    trails = []

    user_pt = Point(lon, lat)
    user_pt_m = transform(proj_to_m, user_pt)

    for edge in data.get("edges", []):
        if edge.get("use") not in ["pedestrian", "footway", "path"]:
            continue

        if "shape" not in edge:
            continue

        coords = [(c[0], c[1]) for c in edge["shape"]]
        geom = LineString(coords)
        geom_m = transform(proj_to_m, geom)

        # Compute distance
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
            "coords": coords
        })

    return trails
