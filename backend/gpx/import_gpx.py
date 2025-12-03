# backend/gpx/import_gpx.py

import xml.etree.ElementTree as ET
from fastapi import UploadFile

# Some GPX files have namespaces like:
# <gpx xmlns="http://www.topografix.com/GPX/1/1">
GPX_NS = {"gpx": "http://www.topografix.com/GPX/1/1"}


def _parse_trkpts(root):
    coords = []
    # Extract track points: <trk><trkseg><trkpt lat=".." lon="..">
    for trkpt in root.findall(".//gpx:trkpt", GPX_NS):
        lat = float(trkpt.attrib.get("lat"))
        lon = float(trkpt.attrib.get("lon"))
        coords.append((lat, lon))
    return coords


def _parse_rtepts(root):
    coords = []
    # Extract route points: <rte><rtept lat=".." lon="..">
    for rtept in root.findall(".//gpx:rtept", GPX_NS):
        lat = float(rtept.attrib.get("lat"))
        lon = float(rtept.attrib.get("lon"))
        coords.append((lat, lon))
    return coords


def _parse_wpts(root):
    coords = []
    # Extract waypoints: <wpt lat=".." lon="..">
    for wpt in root.findall(".//gpx:wpt", GPX_NS):
        lat = float(wpt.attrib.get("lat"))
        lon = float(wpt.attrib.get("lon"))
        coords.append((lat, lon))
    return coords


async def import_gpx(file: UploadFile):
    """
    Parses an uploaded GPX file and returns list of (lat, lon).
    """

    data = await file.read()
    root = ET.fromstring(data)

    # Try trkpts first (most common)
    coords = _parse_trkpts(root)
    if coords:
        return coords

    # If no trkpts, try rtepts
    coords = _parse_rtepts(root)
    if coords:
        return coords

    # If no routes either, fallback to waypoints
    coords = _parse_wpts(root)
    if coords:
        return coords

    return []
