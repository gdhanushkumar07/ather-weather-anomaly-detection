"""
ATHER Live Station API Routes.
Provides endpoints for the frontend to fetch real-time AWS station data
with ATHER 5-layer anomaly detection results.

These routes are mounted alongside the existing telemetry routes.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from ather.data.live_adapter import LiveWeatherAdapter, STATION_REGISTRY
from ather.data.schema import AWSReading, AnomalyAlert
from ather.pipeline import AtherPipeline

logger = logging.getLogger(__name__)

ather_router = APIRouter(prefix="/api/v1/ather", tags=["ATHER Live Stations"])

# These are initialized by the lifespan handler in main.py
_live_adapter: Optional[LiveWeatherAdapter] = None
_pipeline: Optional[AtherPipeline] = None

# Cache for processed results
_results_cache: Optional[Dict[str, Any]] = None
_results_cache_time: float = 0.0
_RESULTS_CACHE_TTL = 30.0  # seconds


def init_ather_routes(pipeline: AtherPipeline, adapter: LiveWeatherAdapter):
    """Called during app startup to inject shared instances."""
    global _live_adapter, _pipeline
    _live_adapter = adapter
    _pipeline = pipeline


def _serialize_alert(alert: AnomalyAlert) -> dict:
    """Convert AnomalyAlert to a clean JSON-serializable dict."""
    return {
        "is_anomaly": alert.is_anomaly,
        "severity_score": round(alert.severity_score, 4),
        "confidence_score": round(alert.confidence_score, 4),
        "veto_fired": alert.veto_fired,
        "root_cause": alert.root_cause.value,
        "affected_channels": alert.affected_channels,
        "layer_scores": {k: round(v, 4) for k, v in alert.layer_scores.items()},
        "explanation": alert.explanation,
        "raw_values": {k: round(v, 2) for k, v in alert.raw_values.items()},
        "corrected_values": {k: round(v, 2) for k, v in alert.corrected_values.items()},
        "sensor_health_index": round(alert.sensor_health_index, 1),
        "estimated_days_to_failure": (
            round(alert.estimated_days_to_failure, 1)
            if alert.estimated_days_to_failure is not None
            else None
        ),
    }


def _serialize_station_result(
    reading: AWSReading,
    alert: AnomalyAlert,
    station_name: str,
) -> dict:
    """Build the unified station response object."""
    return {
        "station_id": reading.station_id,
        "name": station_name,
        "lat": reading.lat,
        "lon": reading.lon,
        "elevation_m": reading.elevation_m,
        "timestamp": reading.timestamp.isoformat(),
        "weather": {
            "temperature_c": round(reading.temperature_c, 1),
            "pressure_hpa": round(reading.pressure_hpa, 1),
            "humidity_pct": round(reading.humidity_pct, 1),
            "dew_point_c": (
                round(reading.dew_point_c, 1)
                if reading.dew_point_c is not None
                else None
            ),
        },
        "anomaly": _serialize_alert(alert),
    }


def _process_all_stations() -> List[dict]:
    """
    Fetch live data for all stations, run through ATHER pipeline,
    and return serialized results. Uses caching to avoid redundant work.
    """
    global _results_cache, _results_cache_time

    # Check cache
    if _results_cache is not None and (time.time() - _results_cache_time) < _RESULTS_CACHE_TTL:
        return _results_cache

    if _live_adapter is None or _pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="ATHER pipeline not initialized. Server is still starting up.",
        )

    # Fetch live data
    readings = _live_adapter.fetch_all_stations()
    if not readings:
        logger.warning("No readings fetched from Open-Meteo")
        return []

    results: List[dict] = []

    for reading in readings:
        try:
            # Get neighbor readings for spatial analysis
            neighbors = _live_adapter.get_neighbors(reading.station_id, readings)

            # Run through the full ATHER pipeline
            alert = _pipeline.process_reading(
                reading=reading,
                neighbor_readings=neighbors if len(neighbors) >= 2 else None,
                fast_path_only=False,
            )

            # Get station name from registry
            meta = STATION_REGISTRY.get(reading.station_id)
            station_name = meta.name if meta else reading.station_id

            result = _serialize_station_result(reading, alert, station_name)
            results.append(result)

        except Exception as e:
            logger.error(
                f"Error processing station {reading.station_id}: {e}",
                exc_info=True,
            )
            # Don't crash the whole response for one bad station
            continue

    # Update cache
    _results_cache = results
    _results_cache_time = time.time()

    return results


@ather_router.get("/stations")
def get_ather_stations():
    """
    Returns all monitored AWS stations with their latest weather data
    and ATHER 5-layer anomaly detection results.

    Each station includes:
    - station_id, name, lat, lon, elevation
    - weather: temperature_c, pressure_hpa, humidity_pct, dew_point_c
    - anomaly: is_anomaly, severity_score, confidence_score, root_cause,
               layer_scores, explanation, sensor_health_index, etc.
    """
    stations = _process_all_stations()

    anomaly_count = sum(1 for s in stations if s["anomaly"]["is_anomaly"])
    healthy_count = len(stations) - anomaly_count

    return {
        "status": "live",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "station_count": len(stations),
        "anomaly_count": anomaly_count,
        "healthy_count": healthy_count,
        "stations": stations,
    }


@ather_router.get("/stations/{station_id}")
def get_ather_station(station_id: str):
    """
    Returns a single station's latest weather data and anomaly detection results.
    """
    stations = _process_all_stations()

    for station in stations:
        if station["station_id"] == station_id:
            return station

    raise HTTPException(
        status_code=404,
        detail=f"Station '{station_id}' not found. Available stations: {[s['station_id'] for s in stations]}",
    )


@ather_router.get("/health")
def get_ather_health():
    """
    Returns ATHER system health status.
    """
    pipeline_ready = _pipeline is not None
    adapter_ready = _live_adapter is not None
    fusion_calibrated = (
        _pipeline.fusion.is_calibrated if _pipeline is not None else False
    )
    multivariate_fitted = (
        _pipeline.layer3_multivariate.is_fitted if _pipeline is not None else False
    )

    station_count = len(STATION_REGISTRY)

    return {
        "status": "operational" if (pipeline_ready and adapter_ready) else "initializing",
        "pipeline_ready": pipeline_ready,
        "adapter_ready": adapter_ready,
        "fusion_calibrated": fusion_calibrated,
        "multivariate_fitted": multivariate_fitted,
        "station_count": station_count,
        "data_source": "Open-Meteo Current Weather API (live)",
        "cache_ttl_seconds": _RESULTS_CACHE_TTL,
        "engine_layers": [
            "Layer 1: Physics Validation",
            "Layer 2: Temporal Pattern Analysis",
            "Layer 3: Multivariate Consistency",
            "Layer 4: Spatial Neighbor Analysis",
            "Layer 5: Sensor Drift & Health",
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
