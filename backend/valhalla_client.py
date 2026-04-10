# backend/valhalla_client.py

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from backend.config import VALHALLA_URL, VALHALLA_TIMEOUT


def valhalla_route(
    start: tuple,
    end: tuple,
    costing: str = "pedestrian",
    costing_options: dict | None = None,
    extra_params: dict | None = None,
) -> dict:
    """
    POST to Valhalla /route.

    start / end: (lat, lon) tuples
    costing: "pedestrian" | "bicycle" | "auto"
    costing_options: Valhalla costing_options dict
    extra_params: merged directly into the request body (e.g. {"directions_options": {...}})
    """
    lat1, lon1 = start
    lat2, lon2 = end

    body: dict = {
        "locations": [
            {"lat": lat1, "lon": lon1},
            {"lat": lat2, "lon": lon2},
        ],
        "costing": costing,
    }

    if costing_options:
        body["costing_options"] = costing_options

    if extra_params:
        body.update(extra_params)

    try:
        res = requests.post(
            f"{VALHALLA_URL}/route",
            json=body,
            timeout=VALHALLA_TIMEOUT,
        )
        res.raise_for_status()
        return res.json()
    except requests.HTTPError as e:
        return {"error": f"Valhalla HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except requests.Timeout:
        return {"error": "Valhalla request timed out"}
    except Exception as e:
        return {"error": f"Valhalla request failed: {e}"}


def valhalla_route_many(
    jobs: list[tuple],
    max_workers: int = 6,
) -> list[dict]:
    """
    Run multiple Valhalla route calls in parallel via a thread pool.

    jobs: list of (label, start, end, costing, costing_options) tuples
    Returns: list of (label, result_dict) in original order
    """

    def _call(job):
        label, start, end, costing, options = job
        return label, valhalla_route(start, end, costing, options)

    results = [None] * len(jobs)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(jobs))) as ex:
        future_to_idx = {ex.submit(_call, job): i for i, job in enumerate(jobs)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                label = jobs[idx][0]
                results[idx] = (label, {"error": str(e)})

    return results
