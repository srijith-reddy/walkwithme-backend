import requests
from shapely.geometry import Point, LineString
from shapely.ops import transform
import pyproj
import math

VALHALLA_URL = "http://165.227.188.199:8002"

# -------------------------------------------------------------
# Project lat/lon → meters (for distances & lengths)
# -------------------------------------------------------------
proj_to_m = pyproj.Transformer.from_crs(
    "EPSG:4326", "EPSG:3857", always_xy=True
).transform


# -------------------------------------------------------------
# Adaptive grid spacing for large radii
# -------------------------------------------------------------
def choose_step_for_radius(radius_m):
    if radius_m <= 5000:
        return 500        # 0.5 km
    if radius_m <= 20000:
        return 1500       # 1.5 km
    if radius_m <= 50000:
        return 3000       # 3 km
    return 5000           # 5 km for 100 km scans


# -------------------------------------------------------------
# Create grid (lat/lon box)
# -------------------------------------------------------------
def generate_grid(lat, lon, radius_m, step_m, max_points=250):

    deg_lat_per_m = 1 / 111_000.0
    deg_lon_per_m = 1 / (111_000.0 * math.cos(math.radians(lat)))

    lat_step = step_m * deg_lat_per_m
    lon_step = step_m * deg_lon_per_m

    lat_min = lat - radius_m * deg_lat_per_m
    lat_max = lat + radius_m * deg_lat_per_m
    lon_min = lon - radius_m * deg_lon_per_m
    lon_max = lon + radius_m * deg_lon_per_m

    lat_points = int((lat_max - lat_min) / lat_step) + 1
    lon_points = int((lon_max - lon_min) / lon_step) + 1

    total = lat_points * lon_points

    # 🔥 LIMIT the grid
    if total > max_points:
        factor = math.sqrt(total / max_points)
        lat_step *= factor
        lon_step *= factor
        lat_points = int((lat_max - lat_min) / lat_step) + 1
        lon_points = int((lon_max - lon_min) / lon_step) + 1

    grid = []
    for i in range(lat_points):
        for j in range(lon_points):
            glat = lat_min + i * lat_step
            glon = lon_min + j * lon_step
            grid.append((glat, glon))

    return grid[:max_points]



# -------------------------------------------------------------
# One-line trace per grid point
# -------------------------------------------------------------
def get_edges_from_point(lat, lon):
    payload = {
        "shape": [
            {"lat": lat, "lon": lon, "type": "break"},
            {"lat": lat + 0.0003, "lon": lon + 0.0003, "type": "break"}
        ],
        "costing": "pedestrian",

        # IMPORTANT: works even if point isn't on a trail exactly
        "shape_match": "walk_or_snap",

        "filters": {
            "attributes": [
                "edge.use",
                "edge.surface",
                "edge.length",
                "names",
                "shape"
            ]
        }
    }

    try:
        r = requests.post(f"{VALHALLA_URL}/trace_attributes", json=payload, timeout=6)
        return r.json().get("edges", [])
    except:
        return []


# -------------------------------------------------------------
# MAIN TRAIL FINDER (AllTrails-like)
# -------------------------------------------------------------
def find_nearby_trails(lat, lon, radius=2000):

    radius_m = radius
    step_m = choose_step_for_radius(radius_m)

    # 1) Grid
    grid = generate_grid(lat, lon, radius_m, step_m)

    trails = []

    # Convert user point
    user_pt = Point(lon, lat)
    user_pt_m = transform(proj_to_m, user_pt)

    WALK_USES = {
    "footway",
    "path",
    "trail",
    "steps",
    "pedestrian",
    "sidewalk",
    "track",
    "pedestrian_crossing",
    "service",                 # parks, waterfront paths
    "service_other",
    "alley",
    "living_street",
    "cycleway",                # shared bike/ped paths
    "bridleway",
    "residential",             # some parks are tagged incorrectly
    "unclassified",
    "road",                    # only if pedestrian_type=foot
}


    seen_ids = set()

    # 2) For each grid point → do small trace_attributes
    for (glat, glon) in grid:
        edges = get_edges_from_point(glat, glon)
        if not edges:
            continue

        for edge in edges:
            use = edge.get("use")
            if use not in WALK_USES:
                continue

            # Deduplicate by ID
            eid = edge.get("id")
            if eid in seen_ids:
                continue
            seen_ids.add(eid)

            rawshape = edge.get("shape", [])
            if not rawshape:
                continue

            # convert shape to coords
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

            # distance to user
            dist = user_pt_m.distance(geom_m)
            if dist > radius_m:
                continue

            props = {
                "id": eid,
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
