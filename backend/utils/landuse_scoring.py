# backend/utils/landuse_scoring.py

import json
import os
from shapely.wkb import loads as load_wkb
from shapely.geometry import Point
from rtree import index

# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------
BASE_PATH = os.path.dirname(__file__)

RTREE_IDX = os.path.join(BASE_PATH, "landuse_rtree.idx")
RTREE_DAT = os.path.join(BASE_PATH, "landuse_rtree.dat")
RTREE_PROP = os.path.join(BASE_PATH, "landuse_rtree_properties.json")
GEOM_FOLDER = os.path.join(BASE_PATH, "landuse_wkb")   # pre-saved geometry

# ---------------------------------------------------------
# Load R-tree index
# ---------------------------------------------------------
idx = index.Index(RTREE_IDX[:-4])

# ---------------------------------------------------------
# Load small metadata (ID → green/water)
# ---------------------------------------------------------
with open(RTREE_PROP, "r") as f:
    METADATA = json.load(f)

# ---------------------------------------------------------
# Lazy geometry loader (each polygon is a tiny .wkb file)
# ---------------------------------------------------------
GEOMETRY_CACHE = {}

def load_geometry(pid):
    if pid in GEOMETRY_CACHE:
        return GEOMETRY_CACHE[pid]

    path = os.path.join(GEOM_FOLDER, f"{pid}.wkb")

    with open(path, "rb") as f:
        geom = load_wkb(f.read())

    GEOMETRY_CACHE[pid] = geom
    return geom


# ---------------------------------------------------------
# Compute GREEN score
# ---------------------------------------------------------
def compute_green_score(coords):
    if not coords:
        return 0.0

    total = len(coords)
    count = 0

    for lat, lon in coords:
        pt = Point(lon, lat)

        for pid in idx.intersection((lon, lat, lon, lat)):
            if METADATA.get(str(pid)) != "green":
                continue

            geom = load_geometry(pid)
            if geom.contains(pt):
                count += 1
                break

    return count / total


# ---------------------------------------------------------
# Compute WATER score
# ---------------------------------------------------------
def compute_water_score(coords):
    if not coords:
        return 0.0

    total = len(coords)
    count = 0

    for lat, lon in coords:
        pt = Point(lon, lat)

        for pid in idx.intersection((lon, lat, lon, lat)):
            if METADATA.get(str(pid)) != "water":
                continue

            geom = load_geometry(pid)
            if geom.contains(pt):
                count += 1
                break

    return count / total
