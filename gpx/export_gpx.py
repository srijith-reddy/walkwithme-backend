# backend/gpx/export_gpx.py

from xml.etree.ElementTree import Element, SubElement, tostring
from fastapi.responses import Response


def build_gpx(coords, name="Walk With Me Route"):
    """
    coords = list of (lat, lon) tuples
    Returns GPX XML string.
    """

    gpx = Element("gpx", {
        "version": "1.1",
        "creator": "Walk With Me",
        "xmlns": "http://www.topografix.com/GPX/1/1"
    })

    metadata = SubElement(gpx, "metadata")
    SubElement(metadata, "name").text = name

    trk = SubElement(gpx, "trk")
    SubElement(trk, "name").text = name

    trkseg = SubElement(trk, "trkseg")

    for lat, lon in coords:
        trkpt = SubElement(trkseg, "trkpt", {
            "lat": str(lat),
            "lon": str(lon)
        })

    xml_bytes = tostring(gpx, encoding="utf-8", xml_declaration=True)
    return xml_bytes


def gpx_response(coords, filename="route.gpx", name="Walk With Me Route"):
    xml_bytes = build_gpx(coords, name=name)

    return Response(
        content=xml_bytes,
        media_type="application/gpx+xml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
