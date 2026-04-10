# backend/themes.py
#
# Themed walk definitions.
#
# A theme tells the loop generator what kind of places to route through
# and gives the iOS app enough context to show a compelling walk card.
#
# The backend owns theme metadata + routing config.
# Curation (which specific walks are "featured") belongs in the iOS app or a CMS.

from typing import TypedDict


class WalkTheme(TypedDict):
    id: str
    name: str
    emoji: str
    tagline: str
    description: str
    loop_theme: str        # passed to get_ai_loop_route as `theme`
    suggested_duration_min: int
    highlight_categories: list[str]
    tags: list[str]        # for filtering/discovery in iOS


THEMES: dict[str, WalkTheme] = {
    "coffee": {
        "id": "coffee",
        "name": "Coffee Shop Loop",
        "emoji": "☕",
        "tagline": "The best independent cafes in the neighbourhood.",
        "description": "Route through the most interesting independent cafes and bakeries nearby. Ideal for a slow morning or weekend exploration.",
        "loop_theme": "coffee",
        "suggested_duration_min": 30,
        "highlight_categories": ["cafe"],
        "tags": ["morning", "food", "chill", "weekend"],
    },
    "history": {
        "id": "history",
        "name": "Historic Walk",
        "emoji": "🏛️",
        "tagline": "The neighbourhood as it used to be.",
        "description": "Monuments, historic buildings, and heritage sites that tell the story of the area. Every street has a memory.",
        "loop_theme": "history",
        "suggested_duration_min": 45,
        "highlight_categories": ["historic", "landmark", "museum"],
        "tags": ["cultural", "landmark", "educational"],
    },
    "parks": {
        "id": "parks",
        "name": "Green Loop",
        "emoji": "🌳",
        "tagline": "Parks, gardens, and a bit of breathing room.",
        "description": "A restorative walk through the city's green spaces. The urban version of a nature walk.",
        "loop_theme": "parks",
        "suggested_duration_min": 40,
        "highlight_categories": ["park", "nature"],
        "tags": ["scenic", "nature", "relaxing", "morning"],
    },
    "food": {
        "id": "food",
        "name": "Food Discovery Loop",
        "emoji": "🍽️",
        "tagline": "Walk until you find something worth stopping for.",
        "description": "Local restaurants, food markets, and hidden gems. Build your appetite, then satisfy it.",
        "loop_theme": "food",
        "suggested_duration_min": 35,
        "highlight_categories": ["restaurant", "cafe", "bar"],
        "tags": ["food", "evening", "social"],
    },
    "landmark": {
        "id": "landmark",
        "name": "Landmark Loop",
        "emoji": "📍",
        "tagline": "The places that define this neighbourhood.",
        "description": "Iconic spots, city landmarks, and the views that make your city worth walking in.",
        "loop_theme": "landmark",
        "suggested_duration_min": 50,
        "highlight_categories": ["landmark", "museum", "nature"],
        "tags": ["cultural", "iconic", "photo", "tourist"],
    },
    "scenic": {
        "id": "scenic",
        "name": "Scenic Loop",
        "emoji": "🌅",
        "tagline": "The most beautiful streets nearby.",
        "description": "Chosen for scenery, not efficiency. Waterfronts, parks, viewpoints, and the streets that feel like somewhere.",
        "loop_theme": "scenic",
        "suggested_duration_min": 45,
        "highlight_categories": ["park", "nature", "landmark"],
        "tags": ["scenic", "relaxing", "golden_hour", "photo"],
    },
    "explore": {
        "id": "explore",
        "name": "Explore Loop",
        "emoji": "🗺️",
        "tagline": "No plan. Just walk.",
        "description": "Lively streets, interesting corners, and the feeling of discovering a city on foot. For when you want to get a little lost.",
        "loop_theme": "explore",
        "suggested_duration_min": 40,
        "highlight_categories": ["cafe", "landmark", "restaurant"],
        "tags": ["explore", "urban", "discovery", "anytime"],
    },
}


def get_all_themes() -> list[WalkTheme]:
    return list(THEMES.values())


def get_theme(theme_id: str) -> WalkTheme | None:
    return THEMES.get(theme_id)


def get_themes_by_tag(tag: str) -> list[WalkTheme]:
    return [t for t in THEMES.values() if tag in t["tags"]]
