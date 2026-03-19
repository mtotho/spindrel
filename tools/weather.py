"""Current weather via OpenWeatherMap. Requires OPENWEATHERMAP_API_KEY in .env."""

import json
import logging
import os

import httpx

from app.tools.registry import register

logger = logging.getLogger(__name__)

_API_KEY = os.getenv("OPENWEATHERMAP_API_KEY", "")
_BASE_URL = "https://api.openweathermap.org/data/2.5"


@register({
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "Get current weather conditions for a city. Returns temperature, "
            "conditions, humidity, wind speed, and feels-like temperature. "
            "Use for questions about current weather, temperature, or conditions outside."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, optionally with country code (e.g. 'London' or 'Paris,FR')",
                },
                "units": {
                    "type": "string",
                    "description": "Temperature units: 'imperial' (°F), 'metric' (°C), or 'standard' (K). Defaults to imperial.",
                    "enum": ["imperial", "metric", "standard"],
                },
            },
            "required": ["city"],
        },
    },
})
async def get_weather(city: str, units: str = "imperial") -> str:
    if not _API_KEY:
        return json.dumps({"error": "OPENWEATHERMAP_API_KEY is not configured"})

    unit_label = {"imperial": "°F", "metric": "°C", "standard": "K"}.get(units, "°F")
    speed_label = "mph" if units == "imperial" else "m/s"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_BASE_URL}/weather",
                params={"q": city, "appid": _API_KEY, "units": units},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return json.dumps({"error": f"City not found: {city}"})
        return json.dumps({"error": f"Weather API error: {e.response.status_code}"})
    except Exception:
        logger.exception("Weather fetch failed for %s", city)
        return json.dumps({"error": "Failed to fetch weather"})

    weather = data.get("weather", [{}])[0]
    main = data.get("main", {})
    wind = data.get("wind", {})

    return json.dumps({
        "city": data.get("name", city),
        "country": data.get("sys", {}).get("country"),
        "conditions": weather.get("description", "unknown"),
        "temperature": f"{main.get('temp')}{unit_label}",
        "feels_like": f"{main.get('feels_like')}{unit_label}",
        "humidity": f"{main.get('humidity')}%",
        "wind_speed": f"{wind.get('speed')} {speed_label}",
    })
