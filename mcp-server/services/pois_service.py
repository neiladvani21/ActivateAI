import math
import logging
from typing import List, Optional
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from config import OVERPASS_URL, HTTP_TIMEOUT
from models.pois import POI

logger = logging.getLogger(__name__)

OVERPASS_FALLBACK_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

CATEGORY_TAGS = {
    "gym":         [("amenity", "fitness_centre"), ("leisure", "fitness_centre")],
    "pharmacy":    [("amenity", "pharmacy")],
    "grocery":     [("shop",    "supermarket")],
    "coffee":      [("amenity", "cafe")],
    "fast_food":   [("amenity", "fast_food")],
    "restaurant":  [("amenity", "restaurant")],
    "bar":         [("amenity", "bar")],
    "hotel":       [("tourism", "hotel")],
    "gas_station": [("amenity", "fuel")],
    "clothing":    [("shop",    "clothes")],
    "bank":        [("amenity", "bank")],
    "parking":     [("amenity", "parking")],
    "hospital":    [("amenity", "hospital")],
    "school":      [("amenity", "school")],
    "supermarket": [("shop",    "supermarket")],
}

VALID_CATEGORIES = set(CATEGORY_TAGS.keys())


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _build_overpass_query(
    lat: float,
    lon: float,
    radius_m: int,
    brand: Optional[str],
    category: Optional[str],
) -> str:
    if brand:
        filters = [f'["name"="{brand}"]']
    else:
        filters = [f'["{k}"="{v}"]' for k, v in CATEGORY_TAGS[category]]

    lines = []
    for f in filters:
        lines.append(f'  node{f}(around:{radius_m},{lat},{lon});')
        lines.append(f'  way{f}(around:{radius_m},{lat},{lon});')

    return "[out:json][timeout:25];\n(\n" + "\n".join(lines) + "\n);\nout center;"


async def get_pois(
    lat: float,
    lon: float,
    radius_m: int,
    brand: Optional[str],
    category: Optional[str],
) -> List[POI]:
    if brand and category:
        raise HTTPException(status_code=400, detail="Provide either 'brand' or 'category', not both.")
    if not brand and not category:
        raise HTTPException(status_code=400, detail="Provide either 'brand' or 'category'.")
    if category and category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Category must be one of: {', '.join(sorted(VALID_CATEGORIES))}.")

    query = _build_overpass_query(lat, lon, radius_m, brand, category)

    elements: List[dict] = []
    failures: List[str] = []
    overpass_urls = [OVERPASS_URL] + OVERPASS_FALLBACK_URLS

    for overpass_url in overpass_urls:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.post(
                    overpass_url,
                    content=urlencode({"data": query}).encode(),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "User-Agent": "ActivateAI/1.0 (marketing-activation-tool)",
                    },
                )

            if response.status_code == 200:
                elements = response.json().get("elements", [])
                break

            failures.append(f"{overpass_url} returned status {response.status_code}")
        except httpx.TimeoutException:
            failures.append(f"{overpass_url} timed out")
        except httpx.RequestError as e:
            failures.append(f"{overpass_url} request error: {str(e)}")

    if not elements and failures:
        logger.warning(
            "POI search unavailable across Overpass providers. Returning empty list. %s",
            " | ".join(failures),
        )
        return []

    poi_type = brand if brand else category

    results: List[POI] = []
    for el in elements:
        # ways have lat/lon under "center"; nodes have them directly
        if el["type"] == "way":
            center = el.get("center", {})
            poi_lat = center.get("lat")
            poi_lon = center.get("lon")
        else:
            poi_lat = el.get("lat")
            poi_lon = el.get("lon")

        if poi_lat is None or poi_lon is None:
            continue

        name = el.get("tags", {}).get("name")
        if not name:
            continue
        distance = _haversine(lat, lon, poi_lat, poi_lon)

        results.append(POI(
            name=name,
            lat=poi_lat,
            lon=poi_lon,
            distance_m=round(distance, 1),
            type=poi_type,
        ))

    results.sort(key=lambda p: p.distance_m)
    return results
