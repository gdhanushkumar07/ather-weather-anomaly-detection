"""
ATHER Open-Meteo Current Weather Service
----------------------------------------
Fetches real-time localized meteorological conditions from Open-Meteo API
with built-in in-memory caching to optimize bandwidth and eliminate redundant queries.
"""

import time
import urllib.request
import urllib.parse
import json
from typing import Dict, Any, Optional

# WMO Weather interpretation codes (WW)
WMO_WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail"
}

def degrees_to_cardinal(deg: Optional[float]) -> str:
    if deg is None:
        return "CALM"
    val = int((deg / 22.5) + 0.5)
    cardinals = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
    ]
    return cardinals[(val % 16)]

class OpenMeteoService:
    def __init__(self, cache_ttl_seconds: int = 300):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = cache_ttl_seconds

    def get_current_weather(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Fetches current weather for given coordinates from Open-Meteo or returns cached entry.
        """
        cache_key = f"{round(lat, 3)}_{round(lon, 3)}"
        now = time.time()

        if cache_key in self.cache:
            entry = self.cache[cache_key]
            if now - entry["cached_at"] < self.cache_ttl:
                return entry["data"]

        # Build Open-Meteo URL
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
        }
        url = f"https://api.open-meteo.com/v1/forecast?{urllib.parse.urlencode(params)}"

        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ATHER-Weather-Intelligence/1.0 (academic-monitoring)"}
        )

        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            if response.status != 200:
                raise RuntimeError(f"Open-Meteo returned status {response.status}")
            raw = json.loads(response.read().decode("utf-8"))

        current = raw.get("current", {})
        weather_code = current.get("weather_code", 0)
        wind_deg = current.get("wind_direction_10m")

        formatted_data = {
            "latitude": lat,
            "longitude": lon,
            "temperature": current.get("temperature_2m"),
            "apparentTemperature": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "pressure": current.get("pressure_msl") or current.get("surface_pressure"),
            "surfacePressure": current.get("surface_pressure"),
            "windSpeed": current.get("wind_speed_10m"),
            "windGusts": current.get("wind_gusts_10m"),
            "windDirectionDeg": wind_deg,
            "windDirection": degrees_to_cardinal(wind_deg),
            "precipitation": current.get("precipitation", 0.0),
            "weatherCode": weather_code,
            "condition": WMO_WEATHER_CODES.get(weather_code, "Fair"),
            "timestamp": current.get("time"),
            "source": "Open-Meteo"
        }

        # Store in cache
        self.cache[cache_key] = {
            "cached_at": now,
            "data": formatted_data
        }

        return formatted_data

    def get_batch_weather(
        self,
        coords: List[Any],
        chunk_size: int = 50
    ) -> List[Optional[Dict[str, Any]]]:
        """
        Fetches current weather for a list of (lat, lon) coordinates in chunks of up to 50
        using Open-Meteo multi-coordinate API. Returns list matching input order.
        """
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        now = time.time()
        results: List[Optional[Dict[str, Any]]] = [None] * len(coords)

        # Check cache first
        indices_to_fetch = []
        for idx, (lat, lon) in enumerate(coords):
            cache_key = f"{round(lat, 3)}_{round(lon, 3)}"
            if cache_key in self.cache and now - self.cache[cache_key]["cached_at"] < self.cache_ttl:
                results[idx] = self.cache[cache_key]["data"]
            else:
                indices_to_fetch.append(idx)

        if not indices_to_fetch:
            return results

        # Fetch in chunks of up to 50
        for i in range(0, len(indices_to_fetch), chunk_size):
            chunk_indices = indices_to_fetch[i : i + chunk_size]
            chunk_coords = [coords[ci] for ci in chunk_indices]

            lats = ",".join(str(round(c[0], 4)) for c in chunk_coords)
            lons = ",".join(str(round(c[1], 4)) for c in chunk_coords)

            url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}&"
                "current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
            )

            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "ATHER-Weather-Intelligence/1.0 (academic-monitoring)"}
                )
                with urllib.request.urlopen(req, context=ctx, timeout=8) as response:
                    if response.status == 200:
                        raw = json.loads(response.read().decode("utf-8"))
                        if isinstance(raw, dict):
                            raw_list = [raw]
                        elif isinstance(raw, list):
                            raw_list = raw
                        else:
                            raw_list = []

                        for j, item in enumerate(raw_list):
                            if j >= len(chunk_indices):
                                break
                            target_idx = chunk_indices[j]
                            orig_lat, orig_lon = coords[target_idx]
                            current = item.get("current", {})
                            weather_code = current.get("weather_code", 0)
                            wind_deg = current.get("wind_direction_10m")

                            formatted_data = {
                                "latitude": orig_lat,
                                "longitude": orig_lon,
                                "temperature": current.get("temperature_2m"),
                                "apparentTemperature": current.get("apparent_temperature"),
                                "humidity": current.get("relative_humidity_2m"),
                                "pressure": current.get("pressure_msl") or current.get("surface_pressure"),
                                "surfacePressure": current.get("surface_pressure"),
                                "windSpeed": current.get("wind_speed_10m"),
                                "windGusts": current.get("wind_gusts_10m"),
                                "windDirectionDeg": wind_deg,
                                "windDirection": degrees_to_cardinal(wind_deg),
                                "precipitation": current.get("precipitation", 0.0),
                                "weatherCode": weather_code,
                                "condition": WMO_WEATHER_CODES.get(weather_code, "Fair"),
                                "timestamp": current.get("time"),
                                "source": "AWS Live Feed (Open-Meteo In-Situ)"
                            }

                            cache_key = f"{round(orig_lat, 3)}_{round(orig_lon, 3)}"
                            self.cache[cache_key] = {"cached_at": now, "data": formatted_data}
                            results[target_idx] = formatted_data
            except Exception as e:
                print(f"Warning: Open-Meteo batch weather fetch error for chunk {i}: {e}")

        return results

open_meteo_service = OpenMeteoService()
