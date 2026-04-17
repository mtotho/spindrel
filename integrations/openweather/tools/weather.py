"""Weather via OpenWeatherMap One Call 3.0. Requires OPENWEATHERMAP_API_KEY."""

import json
import logging
import re
from datetime import datetime, timezone

import httpx

from integrations.openweather.config import settings
from integrations.sdk import register_tool as register

logger = logging.getLogger(__name__)

_ONECALL_URL = "https://api.openweathermap.org/data/3.0/onecall"
_GEO_URL = "https://api.openweathermap.org/geo/1.0"

# US zip: 5 digits, optionally with ",CC" country code
_ZIP_RE = re.compile(r"^\s*(\d{5})(?:\s*,\s*([A-Za-z]{2}))?\s*$")


async def _geocode(client: httpx.AsyncClient, location: str, api_key: str) -> dict | None:
    """Resolve a location string to lat/lon via OpenWeatherMap's Geocoding API.

    Supports:
      - US zip codes: "08530" or "08530,US"
      - "City, State" (US assumed): "Lambertville, NJ"
      - "City, Country": "Paris, FR"
      - "City, State, Country": "Springfield, IL, US"
      - Plain city: "London"
    """
    zip_match = _ZIP_RE.match(location)
    if zip_match:
        zip_code = zip_match.group(1)
        country = (zip_match.group(2) or "US").upper()
        resp = await client.get(
            f"{_GEO_URL}/zip",
            params={"zip": f"{zip_code},{country}", "appid": api_key},
            timeout=10.0,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return {
            "lat": data["lat"],
            "lon": data["lon"],
            "name": data.get("name", zip_code),
            "country": data.get("country", country),
            "state": None,
        }

    # Already "City, ST, Country" (3 parts) → pass through as-is so we don't
    # re-append ",US" to a pre-resolved label like "Lambertville, NJ, US".
    parts = [p.strip() for p in location.split(",") if p.strip()]
    if len(parts) == 3:
        query = ",".join(parts)
    elif len(parts) == 2 and len(parts[1]) == 2 and parts[1].isalpha():
        query = f"{parts[0]},{parts[1].upper()},US"
    else:
        query = location

    resp = await client.get(
        f"{_GEO_URL}/direct",
        params={"q": query, "limit": 1, "appid": api_key},
        timeout=10.0,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    r = results[0]
    return {
        "lat": r["lat"],
        "lon": r["lon"],
        "name": r.get("name", location),
        "country": r.get("country"),
        "state": r.get("state"),
    }


def _local_dt(ts: int | None, offset: int) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts + offset, tz=timezone.utc).replace(tzinfo=None)


def _fmt_current(current: dict, unit_label: str, speed_label: str) -> dict:
    w = (current.get("weather") or [{}])[0]
    out = {
        "conditions": w.get("description", "unknown"),
        "icon": w.get("icon"),
        "temperature": f"{current.get('temp')}{unit_label}",
        "feels_like": f"{current.get('feels_like')}{unit_label}",
        "humidity": f"{current.get('humidity')}%",
        "wind_speed": f"{current.get('wind_speed')} {speed_label}",
        "uv_index": current.get("uvi"),
    }
    if current.get("clouds") is not None:
        out["cloud_cover"] = f"{current['clouds']}%"
    if current.get("visibility") is not None:
        out["visibility_m"] = current["visibility"]
    if current.get("wind_gust") is not None:
        out["wind_gust"] = f"{current['wind_gust']} {speed_label}"
    return out


def _fmt_daily(daily: list, unit_label: str, offset: int) -> list[dict]:
    out = []
    for d in daily[:7]:
        w = (d.get("weather") or [{}])[0]
        temp = d.get("temp", {})
        date = _local_dt(d.get("dt"), offset)
        out.append({
            "date": date.strftime("%a %m/%d") if date else None,
            "summary": d.get("summary"),
            "conditions": w.get("description", "unknown"),
            "temp_min": f"{temp.get('min')}{unit_label}",
            "temp_max": f"{temp.get('max')}{unit_label}",
            "temp_range": f"{temp.get('min')}–{temp.get('max')}{unit_label}",
            "precip_probability": f"{int(round(d.get('pop', 0) * 100))}%",
            "humidity": f"{d.get('humidity')}%",
            "wind_speed": d.get("wind_speed"),
            "uv_index": d.get("uvi"),
        })
    return out


def _fmt_hourly(hourly: list, unit_label: str, offset: int) -> list[dict]:
    out = []
    for h in hourly[:12]:
        w = (h.get("weather") or [{}])[0]
        ts = _local_dt(h.get("dt"), offset)
        out.append({
            "time": ts.strftime("%H:%M") if ts else None,
            "conditions": w.get("description", "unknown"),
            "temperature": f"{h.get('temp')}{unit_label}",
            "feels_like": f"{h.get('feels_like')}{unit_label}",
            "precip_probability": f"{int(round(h.get('pop', 0) * 100))}%",
        })
    return out


def _fmt_alerts(alerts: list, offset: int) -> list[dict]:
    out = []
    for a in alerts:
        start = _local_dt(a.get("start"), offset)
        end = _local_dt(a.get("end"), offset)
        out.append({
            "event": a.get("event"),
            "sender": a.get("sender_name"),
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "description": a.get("description"),
        })
    return out


@register({
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "Get current weather, forecast, and severe weather alerts for a location "
            "via OpenWeatherMap One Call 3.0. Accepts city names, 'City, State' for US, "
            "'City, Country', or US zip codes. Active government weather alerts (tornado "
            "warnings, flood warnings, etc.) are always included when present."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": (
                        "Location to look up. Examples: 'Lambertville, NJ', '08530', "
                        "'London', 'Paris, FR', 'Tokyo, JP'."
                    ),
                },
                "units": {
                    "type": "string",
                    "description": "Temperature units: 'imperial' (°F), 'metric' (°C), or 'standard' (K). Defaults to imperial.",
                    "enum": ["imperial", "metric", "standard"],
                },
                "include_daily": {
                    "type": "boolean",
                    "description": "Include a 7-day daily forecast with min/max, precipitation probability, and human-readable day summaries. Defaults to false.",
                },
                "include_hourly": {
                    "type": "boolean",
                    "description": "Include a 12-hour hourly forecast. Defaults to false.",
                },
            },
            "required": ["location"],
        },
    },
})
async def get_weather(
    location: str,
    units: str = "imperial",
    include_daily: bool = False,
    include_hourly: bool = False,
) -> str:
    api_key = settings.OPENWEATHERMAP_API_KEY
    if not api_key:
        return json.dumps({"error": "OPENWEATHERMAP_API_KEY is not configured"}, ensure_ascii=False)

    unit_label = {"imperial": "°F", "metric": "°C", "standard": "K"}.get(units, "°F")
    speed_label = "mph" if units == "imperial" else "m/s"

    exclude_parts = ["minutely"]
    if not include_hourly:
        exclude_parts.append("hourly")
    if not include_daily:
        exclude_parts.append("daily")
    exclude = ",".join(exclude_parts)

    try:
        async with httpx.AsyncClient() as client:
            geo = await _geocode(client, location, api_key)
            if not geo:
                return json.dumps({"error": f"Location not found: {location}"}, ensure_ascii=False)

            resp = await client.get(
                _ONECALL_URL,
                params={
                    "lat": geo["lat"],
                    "lon": geo["lon"],
                    "appid": api_key,
                    "units": units,
                    "exclude": exclude,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return json.dumps({
            "error": f"Weather API error: {e.response.status_code}",
            "detail": e.response.text[:200],
        }, ensure_ascii=False)
    except Exception:
        logger.exception("Weather fetch failed for %s", location)
        return json.dumps({"error": "Failed to fetch weather"}, ensure_ascii=False)

    tz_offset = data.get("timezone_offset", 0)
    label_parts = [geo["name"]]
    if geo.get("state"):
        label_parts.append(geo["state"])
    if geo.get("country"):
        label_parts.append(geo["country"])

    result: dict = {
        "location": ", ".join(label_parts),
        "units": units,
        "timezone": data.get("timezone"),
        "current": _fmt_current(data.get("current", {}), unit_label, speed_label),
    }

    if include_daily and data.get("daily"):
        result["daily_forecast"] = _fmt_daily(data["daily"], unit_label, tz_offset)
    if include_hourly and data.get("hourly"):
        result["hourly_forecast"] = _fmt_hourly(data["hourly"], unit_label, tz_offset)
    if data.get("alerts"):
        result["alerts"] = _fmt_alerts(data["alerts"], tz_offset)

    return json.dumps(result, ensure_ascii=False)
