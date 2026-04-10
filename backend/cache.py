# backend/cache.py
#
# Shared in-memory TTL cache used by both the route layer and Overpass enrichment.
# Thread-safe. No external dependencies.
#
# Production note: replace with Redis for multi-process deployments.

import time
import hashlib
import json
from threading import Lock


class TTLCache:
    """
    Simple in-memory key-value cache with per-entry TTL and max-size eviction.
    Evicts the soonest-to-expire entry when full.
    """

    def __init__(self, ttl_seconds: int = 3600, max_size: int = 512):
        self._store: dict = {}          # key → (value, expires_at)
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str):
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, key: str, value) -> None:
        with self._lock:
            if len(self._store) >= self._max_size:
                # Evict the entry closest to expiry
                oldest_key = min(self._store, key=lambda k: self._store[k][1])
                del self._store[oldest_key]
            self._store[key] = (value, time.monotonic() + self._ttl)

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._store),
                "max_size": self._max_size,
                "ttl_seconds": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total else 0.0,
            }

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

# Route results — deterministic modes cache for 30 min
# (weather-dependent modes like best/loop are excluded — handled in routing.py)
route_cache = TTLCache(ttl_seconds=1800, max_size=256)

# Overpass results — POI data changes rarely, cache for 1 hour
overpass_cache = TTLCache(ttl_seconds=3600, max_size=256)


# ---------------------------------------------------------------------------
# Cache key helpers
# ---------------------------------------------------------------------------

def route_key(start: tuple, end: tuple | None, mode: str) -> str:
    """Stable cache key for a routing request."""
    lat1, lon1 = round(start[0], 4), round(start[1], 4)
    if end:
        lat2, lon2 = round(end[0], 4), round(end[1], 4)
    else:
        lat2, lon2 = None, None
    return f"route:{lat1},{lon1}:{lat2},{lon2}:{mode}"


def overpass_key(bbox: dict) -> str:
    """Stable cache key from a bounding box dict."""
    stable = json.dumps(
        {k: round(v, 4) for k, v in sorted(bbox.items())},
        sort_keys=True,
    )
    return "overpass:" + hashlib.md5(stable.encode()).hexdigest()
