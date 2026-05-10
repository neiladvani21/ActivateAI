from typing import Optional

import httpx
from langchain_core.tools import tool

from config import MCP_SERVER_URL, TOOL_TIMEOUT


@tool
def get_weather(city: str) -> str:
    """Get current weather for a city. Returns temperature, weather condition,
    and humidity. Use this on every request to provide weather context for
    the marketing activation plan."""
    try:
        with httpx.Client(timeout=TOOL_TIMEOUT) as client:
            response = client.get(
                f"{MCP_SERVER_URL}/weather",
                params={"city": city},
            )
        if response.status_code == 404:
            return f"City '{city}' not found."
        if response.status_code != 200:
            return f"Weather service error (HTTP {response.status_code}). Please retry."
        data = response.json()
        return (
            f"Weather in {data['city']}: {data['temperature']}°C, "
            f"{data['condition']}, humidity {data['humidity']}%."
        )
    except httpx.TimeoutException:
        return "Weather service timed out. Please retry."
    except Exception as e:
        return f"Weather service unavailable: {str(e)}. Please retry."


@tool
def geocode_location(location: str) -> str:
    """Geocode a location name or address to latitude and longitude coordinates.
    Use this to resolve a city or address to lat/lon before searching for POIs."""
    try:
        with httpx.Client(timeout=TOOL_TIMEOUT) as client:
            response = client.get(
                f"{MCP_SERVER_URL}/geocode",
                params={"location": location},
            )
        if response.status_code == 404:
            return f"Location '{location}' could not be geocoded."
        if response.status_code != 200:
            return f"Geocoding service error (HTTP {response.status_code}). Please retry."
        data = response.json()
        return f"Coordinates for '{data['display_name']}': lat={data['lat']}, lon={data['lon']}."
    except httpx.TimeoutException:
        return "Geocoding service timed out. Please retry."
    except Exception as e:
        return f"Geocoding service unavailable: {str(e)}. Please retry."


@tool
def search_pois(
    lat: float,
    lon: float,
    radius_m: int = 1000,
    brand: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """Search for points of interest (POIs) near a lat/lon coordinate.
    Supported categories: gym, pharmacy, grocery, coffee, fast_food, restaurant,
    bar, hotel, gas_station, clothing, bank, parking, hospital, school, supermarket.
    Brand: pass any real brand name (e.g. Starbucks, McDonald's, CVS, Whole Foods,
    Trader Joe's, Costco, Nike, Apple, Subway, Dunkin, Home Depot, Best Buy, Walgreens).
    Provide either brand OR category, not both.
    Returns a sorted list of nearby POIs with name, distance, and type.
    Never guess or hallucinate POI data — only use what this tool returns."""
    params: dict = {"lat": lat, "lon": lon, "radius_m": radius_m}
    if brand:
        params["brand"] = brand
    if category:
        params["category"] = category

    try:
        with httpx.Client(timeout=TOOL_TIMEOUT) as client:
            response = client.get(f"{MCP_SERVER_URL}/pois", params=params)
        if response.status_code == 400:
            return f"POI search error: {response.json().get('detail', 'Bad request')}."
        if response.status_code != 200:
            return "POI search unavailable, please try again."
        pois = response.json()
        if not pois:
            label = brand if brand else category
            return f"No '{label}' locations found within {radius_m}m of ({lat}, {lon}). The area may not have any matching venues in OpenStreetMap data. Try a larger radius or a different category."
        lines = [
            f"- {p['name']} ({p['type']}): {p['distance_m']}m away at ({p['lat']}, {p['lon']})"
            for p in pois
        ]
        # Append raw JSON block so main.py can extract structured POI data for the map
        import json
        map_pois = [{"name": p["name"], "lat": p["lat"], "lon": p["lon"],
                     "distance_m": p["distance_m"], "type": p["type"]} for p in pois[:15]]
        raw_block = f"\n\n__POI_DATA_JSON__:{json.dumps(map_pois)}"
        return f"Found {len(pois)} POI(s):\n" + "\n".join(lines[:20]) + raw_block
    except httpx.TimeoutException:
        return "POI search unavailable, please try again."
    except Exception as e:
        return f"POI search unavailable, please try again. Error: {str(e)}"


@tool
def suggest_geofence(poi_count: int, radius_m: int) -> str:
    """Get a recommended geofence radius based on the number of POIs found
    and the search radius. Call this on every request after searching for POIs
    to include a geofence recommendation in the activation plan."""
    try:
        with httpx.Client(timeout=TOOL_TIMEOUT) as client:
            response = client.get(
                f"{MCP_SERVER_URL}/geofence",
                params={"poi_count": poi_count, "radius_m": radius_m},
            )
        if response.status_code != 200:
            return f"Geofence service error (HTTP {response.status_code}). Please retry."
        data = response.json()
        return (
            f"Recommended geofence radius: {data['recommended_radius_m']}m. "
            f"Reasoning: {data['reasoning']}"
        )
    except httpx.TimeoutException:
        return "Geofence service timed out. Please retry."
    except Exception as e:
        return f"Geofence service unavailable: {str(e)}. Please retry."


TOOLS = [get_weather, geocode_location, search_pois, suggest_geofence]
