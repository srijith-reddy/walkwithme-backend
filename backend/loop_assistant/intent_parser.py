# backend/loop_assistant/intent_parser.py
#
# Rule-based natural language intent parser for the Loop Assistant.
# No LLM dependency — designed to be swapped with an LLM layer later.
#
# Parses free-text queries like:
#   "create a food loop in East Village"
#   "quick scenic walk from 23rd St"
#   "surprise me"
# into a structured ParsedIntent.

import re
from dataclasses import dataclass, field
from typing import Literal

QueryType = Literal["station", "area", "open_ended"]


# ---------------------------------------------------------------------------
# Keyword vocabularies
# ---------------------------------------------------------------------------

_THEME_KEYWORDS: dict[str, list[str]] = {
    "food":     ["food", "eat", "eating", "restaurant", "restaurants", "dining",
                 "lunch", "dinner", "brunch", "hungry", "bite"],
    "coffee":   ["coffee", "cafe", "cafes", "café", "caffeine", "espresso",
                 "latte", "bakery", "bakeries"],
    "scenic":   ["scenic", "beautiful", "scenery", "view", "views", "pretty",
                 "waterfront", "river", "picturesque", "lovely"],
    "landmark": ["landmark", "landmarks", "monument", "monuments", "famous",
                 "iconic", "sights", "sightseeing", "attraction"],
    "history":  ["history", "historic", "historical", "heritage", "old",
                 "architecture", "heritage", "classical"],
    "parks":    ["park", "parks", "green", "nature", "garden", "gardens",
                 "trees", "outdoor", "outdoors"],
    "explore":  ["explore", "exploring", "exploration", "discover", "wander",
                 "wandering", "adventure", "random", "surprise", "anywhere",
                 "whatever", "anything"],
}

_DURATION_RULES: list[tuple[int, list[str]]] = [
    # Order matters — check most specific first
    (15, ["15 min", "15min", "15-min", "15 minute"]),
    (20, ["20 min", "20min", "20-min", "20 minute", "quick", "short", "fast", "brief"]),
    (25, ["25 min", "25min", "25-min"]),
    (30, ["30 min", "30min", "30-min", "half hour", "half-hour", "30 minute"]),
    (40, ["40 min", "40min", "40-min", "40 minute"]),
    (45, ["45 min", "45min", "45-min", "45 minute", "medium"]),
    (50, ["50 min", "50min", "50-min"]),
    (60, ["60 min", "60min", "1 hour", "one hour", "hour long", "hour-long",
          "long walk", "long", "leisurely", "slow"]),
]

# Patterns that suggest the start location is a transit station or street address
_STATION_INDICATORS = [
    r'\b\d+(st|nd|rd|th)\s*(st|street|ave|avenue|blvd|boulevard)?\b',
    r'\b(station|subway|metro|train|stop|terminal)\b',
    r'\bfrom\s+\d+\s*(st|nd|rd|th)',
    r'\b[nesw]?\s*\d+th\b',
]

# Patterns to extract a location string from the query.
# Each tuple: (pattern, capture_group_index)
_LOCATION_PATTERNS: list[tuple[str, int]] = [
    (r'\bfrom\s+(.+?)(?:\s*(?:area|neighborhood|district|loop|walk|route|stroll))?$', 1),
    (r'\bin\s+the\s+(.+?)(?:\s*(?:area|neighborhood|district|loop|walk|route))?$', 1),
    (r'\bin\s+(.+?)(?:\s*(?:area|neighborhood|district|loop|walk|route|stroll))?$', 1),
    (r'\bnear\s+(.+?)(?:\s*(?:area|neighborhood|district|loop|walk|route))?$', 1),
    (r'\baround\s+(.+?)(?:\s*(?:area|neighborhood|district|loop|walk|route))?$', 1),
    (r'\bthrough\s+(.+?)(?:\s*(?:area|neighborhood|district|loop|walk|route))?$', 1),
]

# Trailing noise to strip from extracted location hints
_LOCATION_TRAILING_NOISE = re.compile(
    r'\s*(loop|walk|route|stroll|hike|run|jog|please|today|tonight|now|me)$',
    re.IGNORECASE,
)

# Map theme → preferred Valhalla routing style
_THEME_TO_ROUTE_STYLE: dict[str, str] = {
    "food":     "explore",
    "coffee":   "explore",
    "scenic":   "scenic",
    "landmark": "scenic",
    "history":  "scenic",
    "parks":    "scenic",
    "explore":  "explore",
}

# Default duration when no duration keyword matches
_DEFAULT_DURATION = 35


# ---------------------------------------------------------------------------
# ParsedIntent
# ---------------------------------------------------------------------------

@dataclass
class ParsedIntent:
    query_type: QueryType
    location_hint: str | None        # raw extracted location string (lowercase)
    theme: str                        # food | coffee | scenic | landmark | history | parks | explore
    duration_min: int                 # target walk duration in minutes
    route_style: str                  # scenic | explore — passed to routing as style hint
    matched_keywords: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public: parse_intent
# ---------------------------------------------------------------------------

def parse_intent(query: str) -> ParsedIntent:
    """
    Convert a free-text query into a ParsedIntent.

    Examples:
        parse_intent("food loop in East Village")
        → ParsedIntent(query_type="area", location_hint="east village",
                       theme="food", duration_min=35, ...)

        parse_intent("quick scenic walk from 23rd St")
        → ParsedIntent(query_type="station", location_hint="23rd st",
                       theme="scenic", duration_min=20, ...)

        parse_intent("surprise me")
        → ParsedIntent(query_type="open_ended", location_hint=None,
                       theme="explore", duration_min=35, ...)
    """
    q = query.strip().lower()

    # --- Theme detection ---
    matched_theme = _detect_theme(q)
    matched_kws = [kw for kw in _THEME_KEYWORDS.get(matched_theme, []) if kw in q]

    # --- Duration detection ---
    duration_min = _detect_duration(q)

    # --- Location extraction ---
    location_hint = _extract_location(q)

    # --- Query type ---
    query_type = _detect_query_type(q, location_hint)

    route_style = _THEME_TO_ROUTE_STYLE.get(matched_theme, "explore")

    return ParsedIntent(
        query_type=query_type,
        location_hint=location_hint,
        theme=matched_theme,
        duration_min=duration_min,
        route_style=route_style,
        matched_keywords=matched_kws,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_theme(q: str) -> str:
    """Return the best-matching theme based on keyword count."""
    scores: dict[str, int] = {}
    for theme, keywords in _THEME_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in q)
        if count > 0:
            scores[theme] = count

    # Open-ended signals take priority over keyword counts
    open_ended_signals = ["surprise", "good walk", "any walk", "just walk",
                          "anything", "whatever", "random", "no preference"]
    if any(s in q for s in open_ended_signals):
        return "explore"

    if not scores:
        return "scenic"  # safe, broadly appealing default

    return max(scores, key=lambda t: scores[t])


def _detect_duration(q: str) -> int:
    """Return inferred duration in minutes."""
    for minutes, keywords in _DURATION_RULES:
        if any(kw in q for kw in keywords):
            return minutes
    return _DEFAULT_DURATION


def _extract_location(q: str) -> str | None:
    """Extract a location hint string from the query, or None."""
    for pattern, group in _LOCATION_PATTERNS:
        m = re.search(pattern, q)
        if m:
            raw = m.group(group).strip()
            # Strip trailing noise words
            raw = _LOCATION_TRAILING_NOISE.sub("", raw).strip()
            # Minimum viable location: at least 2 characters
            if len(raw) >= 2:
                return raw
    return None


def _detect_query_type(q: str, location_hint: str | None) -> QueryType:
    """Classify the query as station / area / open_ended."""
    # Station: matches transit/address patterns
    is_station = any(re.search(p, q) for p in _STATION_INDICATORS)
    if is_station:
        return "station"

    # Area: has a location hint that doesn't look like a station
    if location_hint:
        return "area"

    return "open_ended"
