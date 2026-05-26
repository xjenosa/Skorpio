"""
Open-Meteo client — replaces OpenWeatherMap.

Free, no API key required, 10k requests/day. Used during per-site
generation for current weather + 7-day forecast + cooling degree days.

Public interface matches the previous OpenWeatherClient so callers
don't need to change anything beyond their import.

Docs: https://open-meteo.com/en/docs
"""
from typing import Optional

import httpx

from backend.config import settings
from backend.utils.cache import weather_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# WMO weather codes → human-readable condition labels.
# https://open-meteo.com/en/docs (search "WMO Weather interpretation codes")
_WMO_CONDITION = {
    0: "Clear",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Fog",
    51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers", 81: "Rain showers", 82: "Heavy rain showers",
    85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}


class OpenMeteoClient:
    def __init__(self):
        self.base = settings.open_meteo_base_url

    async def current(self, lat: float, lon: float) -> Optional[dict]:
        """Return current weather + temperature for a lat/lon."""
        cache_key = f"current:{lat:.3f}:{lon:.3f}"
        cached = await weather_cache.aget(cache_key)
        if cached:
            return cached
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{self.base}/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                        "wind_speed_unit": "ms",
                    },
                )
                if r.status_code != 200:
                    return None
                payload = r.json()
        except Exception as e:
            logger.warning(f"Open-Meteo current error at {lat},{lon}: {e}")
            return None

        current = payload.get("current", {})
        code = current.get("weather_code")
        result = {
            "temp_c": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "wind_speed_ms": current.get("wind_speed_10m"),
            "condition": _WMO_CONDITION.get(code, "Unknown") if code is not None else None,
            "city": None,
            "source": "Open-Meteo",
        }
        await weather_cache.aset(cache_key, result)
        return result

    async def forecast(self, lat: float, lon: float, days: int = 5) -> list[dict]:
        """Return an hourly forecast list (capped at `days`). Each entry has
        the shape {"time": "...", "temp_c": float, "wind_speed_ms": float}."""
        cache_key = f"forecast:{lat:.3f}:{lon:.3f}:{days}"
        cached = await weather_cache.aget(cache_key)
        if cached:
            return cached
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(
                    f"{self.base}/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "hourly": "temperature_2m,wind_speed_10m",
                        "wind_speed_unit": "ms",
                        "forecast_days": min(max(days, 1), 16),
                    },
                )
                if r.status_code != 200:
                    return []
                payload = r.json()
        except Exception as e:
            logger.warning(f"Open-Meteo forecast error: {e}")
            return []

        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        winds = hourly.get("wind_speed_10m", [])

        entries: list[dict] = []
        for i, t in enumerate(times):
            entries.append({
                "time": t,
                "temp_c": temps[i] if i < len(temps) else None,
                "wind_speed_ms": winds[i] if i < len(winds) else None,
            })
        await weather_cache.aset(cache_key, entries)
        return entries

    async def cooling_degree_days(self, lat: float, lon: float, days: int = 5) -> float:
        """Estimate CDD (base 18 °C) from the next-`days` hourly forecast."""
        entries = await self.forecast(lat, lon, days=days)
        if not entries:
            return 0.0
        cdd = 0.0
        for e in entries:
            t = e.get("temp_c")
            if t is None:
                continue
            cdd += max(0.0, float(t) - 18.0)
        # Sum of hourly temps → divide by 24 to convert to day equivalents
        return round(cdd / 24.0, 2)


open_meteo_client = OpenMeteoClient()
# Backwards-compat alias so any existing `from backend.services.openweather import
# openweather_client` keeps working until callers are migrated.
openweather_client = open_meteo_client
