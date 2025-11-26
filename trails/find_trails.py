# backend/trails/find_trails.py

import osmium
from shapely.geometry import LineString, Point
from shapely.ops import transform
import pyproj

# ============================================================
# PBF FILE (BBBike or Geofabrik extract)
# ============================================================
PBF_PATH = "osrm/map.osm.pbf"   # change only if your path is different


# ============================================================
# TRAIL EXTRACTOR
# ============================================================
class TrailHandler(osmium.SimpleHandler):
    """
    Extracts walkable trail-like features from an OSM PBF.
    Runs once at startup → results cached.
    """

    def __init__(self):
        super().__init__()
        self.trails = []

        # 4326 → WebMercator (meters)
        self.proj = pyproj.Transformer.from_crs(
            "EPSG:4326", "EPSG:3857", always_xy=True
        ).transform

    def way(self, w):

        # Skip ways without highway tag
        if "highway" not in w.tags:
            return

        hw = w.tags.get("highway")

        # Only keep relevant walking trails
        if hw not in ["path", "footway", "track", "bridleway"]:
            return

        if len(w.nodes) < 2:
            return

        # Extract geometry (lon, lat)
        coords = [(n.lon, n.lat) for n in w.nodes]
        geom = LineString(coords)

        # Project into meters for distance
        geom_m = transform(self.proj, geom)

        props = {
            "id": w.id,
            "name": w.tags.get("name", "Unnamed Trail"),
            "surface": w.tags.get("surface", "unknown"),
            "highway": hw,
        }

        self.trails.append({
            "geometry": geom,       # WGS84
            "geometry_m": geom_m,   # meters
            "properties": props,
            "length_m": geom_m.length
        })


# ============================================================
# CACHE TRAILS (load only once)
# ============================================================
_trail_cache = None

def load_trails():
    global _trail_cache
    if _trail_cache is not None:
        return _trail_cache

    handler = TrailHandler()
    handler.apply_file(PBF_PATH, locations=True)

    _trail_cache = handler.trails
    return _trail_cache


# ============================================================
# FILTER BY RADIUS
# ============================================================
def filter_trails(lat, lon, radius_m):
    """
    Returns all trails within radius (in meters) from a lat/lon point.
    """

    # Convert user point to Shapely in 4326
    user_pt = Point(lon, lat)

    proj = pyproj.Transformer.from_crs(
        "EPSG:4326", "EPSG:3857", always_xy=True
    ).transform
    user_pt_m = transform(proj, user_pt)

    trails = load_trails()
    result = []

    for t in trails:
        geom_m = t["geometry_m"]
        dist = user_pt_m.distance(geom_m)

        if dist <= radius_m:
            result.append({
                "properties": t["properties"],
                "length_m": t["length_m"],
                "distance_from_user_m": dist,
                "coords": list(t["geometry"].coords)
            })

    return result


# ============================================================
# PUBLIC API ENTRY
# ============================================================
def find_nearby_trails(lat, lon, radius=2000):
    """
    Main function used by /trails endpoint.
    Works fully offline using your OSM PBF.
    Returns trail list compatible with Leaflet/Valhalla front-end.
    """
    return filter_trails(lat, lon, radius)
