"""
Live Weather Data Adapter for ATHER.
Fetches real-time weather observations from Open-Meteo's free Current Weather API
and normalizes them into AWSReading objects for the ATHER anomaly detection pipeline.

Open-Meteo Current Weather API:
- Free, no API key required
- Returns: temperature_2m, relative_humidity_2m, surface_pressure, wind_speed_10m, etc.
- Updates approximately every 15 minutes
- Docs: https://open-meteo.com/en/docs
"""
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

from ather.data.schema import AWSReading, StationMetadata

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Indian AWS Station Registry
# Real coordinates across India's major climate zones for SIH demonstration
# ---------------------------------------------------------------------------
STATION_REGISTRY: Dict[str, StationMetadata] = {
    "AWS_MUMBAI_01": StationMetadata(
        station_id="AWS_MUMBAI_01",
        name="Mumbai Colaba Observatory",
        lat=18.9067,
        lon=72.8147,
        elevation_m=11.0,
    ),
    "AWS_DELHI_01": StationMetadata(
        station_id="AWS_DELHI_01",
        name="New Delhi Safdarjung",
        lat=28.5849,
        lon=77.2087,
        elevation_m=216.0,
    ),
    "AWS_CHENNAI_01": StationMetadata(
        station_id="AWS_CHENNAI_01",
        name="Chennai Nungambakkam",
        lat=13.0674,
        lon=80.2376,
        elevation_m=16.0,
    ),
    "AWS_KOLKATA_01": StationMetadata(
        station_id="AWS_KOLKATA_01",
        name="Kolkata Alipore",
        lat=22.5354,
        lon=88.3390,
        elevation_m=6.0,
    ),
    "AWS_BENGALURU_01": StationMetadata(
        station_id="AWS_BENGALURU_01",
        name="Bengaluru HAL Airport",
        lat=12.9499,
        lon=77.6684,
        elevation_m=920.0,
    ),
    "AWS_JAIPUR_01": StationMetadata(
        station_id="AWS_JAIPUR_01",
        name="Jaipur Sanganer",
        lat=26.8242,
        lon=75.8122,
        elevation_m=390.0,
    ),
    "AWS_GUWAHATI_01": StationMetadata(
        station_id="AWS_GUWAHATI_01",
        name="Guwahati Borjhar",
        lat=26.1063,
        lon=91.5857,
        elevation_m=54.0,
    ),
    "AWS_HYDERABAD_01": StationMetadata(
        station_id="AWS_HYDERABAD_01",
        name="Hyderabad Begumpet",
        lat=17.4530,
        lon=78.4676,
        elevation_m=545.0,
    ),
    "AWS_THIRUVANANTHAPURAM_01": StationMetadata(
        station_id="AWS_THIRUVANANTHAPURAM_01",
        name="Thiruvananthapuram Observatory",
        lat=8.4844,
        lon=76.9530,
        elevation_m=64.0,
    ),
    "AWS_SHIMLA_01": StationMetadata(
        station_id="AWS_SHIMLA_01",
        name="Shimla Ridge Station",
        lat=31.1048,
        lon=77.1734,
        elevation_m=2202.0,
    ),
}


class LiveWeatherAdapter:
    """
    Fetches real-time weather observations from Open-Meteo and converts
    them to ATHER AWSReading objects.

    Implements:
    - Per-request caching with configurable TTL
    - Graceful error handling per station
    - Unit normalization to match AWSReading schema
    """

    OPEN_METEO_CURRENT_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(
        self,
        stations: Optional[Dict[str, StationMetadata]] = None,
        cache_ttl_seconds: int = 30,
        request_timeout: int = 10,
    ):
        self.stations = stations or STATION_REGISTRY
        self.cache_ttl = cache_ttl_seconds
        self.timeout = request_timeout

        # Cache: station_id -> (timestamp_fetched, AWSReading)
        self._cache: Dict[str, Tuple[float, AWSReading]] = {}
        # Cache for batch fetch
        self._batch_cache: Optional[Tuple[float, List[AWSReading]]] = None

    def _is_cache_valid(self, cache_time: float) -> bool:
        return (time.time() - cache_time) < self.cache_ttl

    def fetch_station(self, station_id: str) -> Optional[AWSReading]:
        """
        Fetches current weather for a single station.
        Returns None if the station is not found or the API call fails.
        """
        if station_id not in self.stations:
            logger.warning(f"Station {station_id} not found in registry")
            return None

        # Check cache
        if station_id in self._cache:
            cache_time, cached_reading = self._cache[station_id]
            if self._is_cache_valid(cache_time):
                return cached_reading

        meta = self.stations[station_id]
        reading = self._fetch_from_api(meta)
        if reading is not None:
            self._cache[station_id] = (time.time(), reading)
        return reading

    def fetch_all_stations(self) -> List[AWSReading]:
        """
        Fetches current weather for all registered stations.
        Uses batch API call where possible, with per-station error isolation.
        Returns list of successfully fetched readings (may be fewer than total stations).
        """
        # Check batch cache
        if self._batch_cache is not None:
            cache_time, cached_readings = self._batch_cache
            if self._is_cache_valid(cache_time):
                return cached_readings

        readings: List[AWSReading] = []

        # Open-Meteo supports multi-location in a single call
        station_list = list(self.stations.values())
        lats = [s.lat for s in station_list]
        lons = [s.lon for s in station_list]

        try:
            params = {
                "latitude": ",".join(str(l) for l in lats),
                "longitude": ",".join(str(l) for l in lons),
                "current": "temperature_2m,relative_humidity_2m,surface_pressure,dew_point_2m,wind_speed_10m,wind_direction_10m",
                "timezone": "auto",
            }

            resp = requests.get(
                self.OPEN_METEO_CURRENT_URL,
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            # Open-Meteo returns a list when multiple locations are requested
            if isinstance(data, list):
                results = data
            else:
                # Single location response
                results = [data]

            for i, result in enumerate(results):
                if i >= len(station_list):
                    break
                meta = station_list[i]
                reading = self._parse_current_response(result, meta)
                if reading is not None:
                    readings.append(reading)
                    self._cache[meta.station_id] = (time.time(), reading)

        except requests.RequestException as e:
            logger.error(f"Batch fetch from Open-Meteo failed: {e}")
            # Fallback: try individual fetches for any stations not yet cached
            for meta in station_list:
                if meta.station_id in self._cache:
                    cache_time, cached = self._cache[meta.station_id]
                    if self._is_cache_valid(cache_time):
                        readings.append(cached)
                        continue
                # Try individual fetch
                reading = self._fetch_from_api(meta)
                if reading is not None:
                    readings.append(reading)

        except Exception as e:
            logger.error(f"Unexpected error during batch fetch: {e}")

        if readings:
            self._batch_cache = (time.time(), readings)

        return readings

    def _fetch_from_api(self, meta: StationMetadata) -> Optional[AWSReading]:
        """Fetches current weather for a single station from Open-Meteo."""
        try:
            params = {
                "latitude": meta.lat,
                "longitude": meta.lon,
                "current": "temperature_2m,relative_humidity_2m,surface_pressure,dew_point_2m,wind_speed_10m,wind_direction_10m",
                "timezone": "auto",
            }

            resp = requests.get(
                self.OPEN_METEO_CURRENT_URL,
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return self._parse_current_response(data, meta)

        except requests.Timeout:
            logger.warning(f"Timeout fetching data for station {meta.station_id}")
        except requests.RequestException as e:
            logger.warning(f"API error for station {meta.station_id}: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error for station {meta.station_id}: {e}")

        return None

    def _parse_current_response(
        self, data: dict, meta: StationMetadata
    ) -> Optional[AWSReading]:
        """
        Parses Open-Meteo current weather response into an AWSReading.

        Open-Meteo current response format:
        {
            "current": {
                "time": "2024-01-15T14:00",
                "temperature_2m": 28.5,
                "relative_humidity_2m": 65,
                "surface_pressure": 1012.3,
                "dew_point_2m": 21.2,
                "wind_speed_10m": 12.5,
                "wind_direction_10m": 240
            },
            "elevation": 11.0
        }
        """
        try:
            current = data.get("current", {})

            temperature = current.get("temperature_2m")
            humidity = current.get("relative_humidity_2m")
            pressure = current.get("surface_pressure")
            dew_point = current.get("dew_point_2m")
            time_str = current.get("time")

            # Validate essential fields
            if temperature is None or humidity is None or pressure is None:
                logger.warning(
                    f"Missing essential fields for {meta.station_id}: "
                    f"temp={temperature}, rh={humidity}, press={pressure}"
                )
                return None

            # Parse timestamp
            if time_str:
                try:
                    timestamp = datetime.fromisoformat(time_str)
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    timestamp = datetime.now(timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)

            # Use elevation from API response if available, otherwise from registry
            elevation = data.get("elevation", meta.elevation_m)
            if elevation is None:
                elevation = meta.elevation_m

            return AWSReading(
                station_id=meta.station_id,
                timestamp=timestamp,
                temperature_c=float(temperature),
                pressure_hpa=float(pressure),
                humidity_pct=float(humidity),
                dew_point_c=float(dew_point) if dew_point is not None else None,
                lat=meta.lat,
                lon=meta.lon,
                elevation_m=float(elevation),
            )

        except Exception as e:
            logger.error(f"Error parsing response for {meta.station_id}: {e}")
            return None

    def get_station_metadata(self) -> Dict[str, StationMetadata]:
        """Returns the station registry for frontend display."""
        return self.stations.copy()

    def get_neighbors(
        self, station_id: str, readings: List[AWSReading]
    ) -> List[AWSReading]:
        """
        Returns all readings except the target station, for spatial layer analysis.
        """
        return [r for r in readings if r.station_id != station_id]
