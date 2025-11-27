# backend/utils/scoring.py

def compute_scores_from_valhalla(route_json):
    """
    Compute green and water scores directly from Valhalla route metadata.
    No external files, no Overpass API.
    """

    if "trip" not in route_json or "legs" not in route_json["trip"]:
        return {"green": 0.0, "water": 0.0, "scenic": 0.0}

    edges = []
    for leg in route_json["trip"]["legs"]:
        for man in leg.get("maneuvers", []):
            for edge in man.get("edge", []):
                edges.append(edge)

    if not edges:
        return {"green": 0.0, "water": 0.0, "scenic": 0.0}

    green_hits = 0
    water_hits = 0
    scenic_hits = 0

    for e in edges:
        use = e.get("use", "")
        road_class = e.get("road_class", "")
        name = e.get("name", "").lower()
        surface = e.get("surface", "")
        density = e.get("density", 8)  # high density = city

        # ---------------------------------------------------------
        # GREEN SCORE LOGIC
        # ---------------------------------------------------------
        # Trails, footpaths, pedestrian zones, low-density streets
        if use in ["path", "footway", "cycleway", "sidewalk"]:
            green_hits += 1
        elif road_class in ["residential", "service"] and density <= 4:
            green_hits += 1

        # ---------------------------------------------------------
        # WATER SCORE LOGIC
        # ---------------------------------------------------------
        # Street names near water ALWAYS include these words
        WATER_KEYWORDS = [
            "river", "lake", "pond", "harbor", "bay", "creek",
            "brook", "canal", "waterfront", "pier"
        ]
        if any(w in name for w in WATER_KEYWORDS):
            water_hits += 1

        # ---------------------------------------------------------
        # SCENIC SCORE LOGIC
        # ---------------------------------------------------------
        # Weighted: low density + good surface + trail usage
        scenic = 0

        # nicer surfaces (fine track)
        if surface in ["compacted", "fine_gravel", "dirt", "wood"]:
            scenic += 1
        
        # low traffic urban density
        if density <= 4:
            scenic += 1

        # trails/paths
        if use in ["path", "footway", "cycleway"]:
            scenic += 1

        if scenic > 0:
            scenic_hits += 1


    total = len(edges)

    return {
        "green": green_hits / total,
        "water": water_hits / total,
        "scenic": scenic_hits / total
    }
