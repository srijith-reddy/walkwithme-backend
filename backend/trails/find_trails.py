import requests
from shapely.geometry import Point, LineString
from shapely.ops import transform
import pyproj
import math
from collections import defaultdict

VALHALLA_URL = "http://165.227.188.199:8002"

proj_to_m = pyproj.Transformer.from_crs(
    "EPSG:4326", "EPSG:3857", always_xy=True
).transform


# -------------------------------------------------------------
# Grid spacing selection
# -------------------------------------------------------------
def choose_step_for_radius(radius_m):
    if radius_m <= 5000:
        return 500
    if radius_m <= 20000:
        return 1500
    if radius_m <= 50000:
        return 3000
    return 5000


# -------------------------------------------------------------
# Grid generator
# -------------------------------------------------------------
def generate_grid(lat, lon, radius_m, step_m, max_points=200):
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
# SAFE trace_attributes call
# -------------------------------------------------------------
def get_edges_from_point(lat, lon):
    payload = {
        "shape": [
            {"lat": lat, "lon": lon},
            {"lat": lat, "lon": lon + 0.002}   # 150–200m segment
        ],
        "costing": "pedestrian",
        "shape_match": "walk_or_snap",
        "trace_options": {
            "search_radius": 80
        },
        "filters": {
            "attributes": [
                "edge.use", "edge.surface", "edge.length",
                "names", "shape"
            ]
        }
    }

    try:
        r = requests.post(f"{VALHALLA_URL}/trace_attributes", json=payload, timeout=5)
        data = r.json()
        return data.get("edges", [])
    except:
        return []


# -------------------------------------------------------------
# MAIN TRAIL FINDER (proper merging)
# -------------------------------------------------------------
def find_nearby_trails(lat, lon, radius=2000):

    radius_m = radius
    step_m = choose_step_for_radius(radius_m)
    grid = generate_grid(lat, lon, radius_m, step_m)

    user_pt = Point(lon, lat)
    user_pt_m = transform(proj_to_m, user_pt)

    WALK_USES = {
        "footway", "path", "trail", "steps",
        "pedestrian", "sidewalk", "track",
        "cycleway", "bridleway", "service",
        "alley", "living_street", "residential",
        "unclassified", "road"
    }

    # Group edges by name
    merged = defaultdict(list)

    for (glat, glon) in grid:
        edges = get_edges_from_point(glat, glon)
        if not edges:
            continue

        for e in edges:
            use = e.get("use")
            if use not in WALK_USES:
                continue

            # name fallback
            name_list = e.get("names") or []
            name = name_list[0] if name_list else None
            if not name:
                name = "Unnamed Trail"

            raw = e.get("shape", [])
            if not raw or len(raw) < 2:
                continue

            coords = []
            for p in raw:
                if isinstance(p, dict):
                    coords.append((p["lon"], p["lat"]))
                else:
                    coords.append((p[0], p[1]))

            line = LineString(coords)
            merged[name].append({
                "coords": coords,
                "geom": line,
                "surface": e.get("surface", "unknown"),
                "use": use,
                "length": e.get("length", 0)
            })

    # ---------------------------------------------------------
    # Build final trails
    # ---------------------------------------------------------
    trails = []

    for name, segments in merged.items():
        if not segments:
            continue

        # Merge coords sequentially
        merged_coords = []
        total_length = 0
        surfaces = set()
        uses = set()

        for seg in segments:
            merged_coords.extend(seg["coords"])
            total_length += seg["length"]
            surfaces.add(seg["surface"])
            uses.add(seg["use"])

        if total_length < 20:  # skip tiny
            continue

        merged_line = LineString(merged_coords)
        merged_line_m = transform(proj_to_m, merged_line)

        dist = user_pt_m.distance(merged_line_m)
        if dist > radius_m:
            continue

        trails.append({
            "name": name,
            "length_m": total_length,
            "distance_from_user_m": dist,
            "coords": merged_coords,
            "surface": next(iter(surfaces)),
            "use": next(iter(uses)),
            "center": merged_coords[len(merged_coords)//2]
        })

    # Sort by distance
    trails.sort(key=lambda x: x["distance_from_user_m"])
    return trails[:20]
