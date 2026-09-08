"""
ATHER Backend Core API
======================
FastAPI server orchestrating weather station management, anomaly detection,
Vane meteorological grid rendering data, and multi-protocol ingestion.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any

from .stations.service import station_service
from .weather.grid_service import grid_service
from .weather.open_meteo import open_meteo_service
from .ingestion.adapter import IngestionAdapter

app = FastAPI(
    title="ATHER Core API",
    description="Intelligent Weather-Station Monitoring and Anomaly-Detection Platform",
    version="1.0.0"
)

# Enable CORS for local development and demo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "service": "ATHER Platform Backend",
        "stations_loaded": len(station_service._stations),
        "version": "1.0.0"
    }

@app.get("/api/stations")
def get_stations_geojson(
    min_lon: Optional[float] = Query(None, description="Bounding box minimum longitude"),
    min_lat: Optional[float] = Query(None, description="Bounding box minimum latitude"),
    max_lon: Optional[float] = Query(None, description="Bounding box maximum longitude"),
    max_lat: Optional[float] = Query(None, description="Bounding box maximum latitude"),
    limit: Optional[int] = Query(None, description="Max stations to return"),
    status: Optional[str] = Query(None, description="Filter by status: NORMAL, WARNING, ANOMALY, OFFLINE")
):
    """
    Returns weather stations in GeoJSON format optimized for MapLibre GPU clustering.
    Supports viewport bounding box spatial filtering to ensure fast 60fps interaction.
    """
    return station_service.get_geojson(
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        limit=limit,
        status=status
    )

@app.get("/api/stations/search")
def search_stations(q: str = Query(..., min_length=1), limit: int = 10):
    """Search stations by name, town, country, or station ID."""
    return station_service.search(q, limit=limit)

@app.get("/api/stations/{station_id}")
def get_station_details(station_id: str):
    """Returns comprehensive metadata and current telemetry for a specific station."""
    stn = station_service.get_station(station_id)
    if not stn:
        raise HTTPException(status_code=404, detail=f"Station '{station_id}' not found")
    return stn

@app.get("/api/stations/{station_id}/observations")
def get_station_observations(station_id: str, hours: int = Query(24, ge=1, le=168)):
    """Returns time-series observation trends for charts, sparklines, and diurnal analysis."""
    stn = station_service.get_station(station_id)
    if not stn:
        raise HTTPException(status_code=404, detail=f"Station '{station_id}' not found")
    return {
        "station_id": station_id,
        "hours": hours,
        "series": station_service.get_observations_history(station_id, hours=hours)
    }

@app.get("/api/weather/metadata")
def get_weather_metadata():
    """Returns grid dimensions, bounding box, and variable definitions for Vane rendering."""
    return grid_service.get_grid_metadata()

@app.get("/api/weather/grid")
def get_weather_grid(variable: str = Query("temperature", enum=["temperature", "wind", "pressure_msl"])):
    """
    Provides gridded meteorological scalar/vector data matrix for Vane MapLibre WebGL layers.
    """
    if variable == "temperature":
        return grid_service.generate_temperature_field()
    elif variable == "wind":
        return grid_service.generate_wind_field()
    else:
        raise HTTPException(status_code=400, detail=f"Variable '{variable}' not supported.")

@app.get("/api/weather/current")
def get_current_weather(
    lat: float = Query(..., description="Latitude of location"),
    lon: float = Query(..., description="Longitude of location")
):
    """
    Fetches real-time localized current weather from Open-Meteo for the specified coordinate.
    """
    try:
        return open_meteo_service.get_current_weather(lat, lon)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Open-Meteo weather fetch error: {str(e)}")

@app.get("/api/anomalies")
def get_anomalies():
    """Returns active anomaly metrics and breakdown for the ATHER anomaly monitoring panel."""
    return station_service.get_anomalies_summary()

@app.post("/api/ingest")
def ingest_observation(payload: Dict[str, Any]):
    """
    Multi-protocol ingestion endpoint accepting WeeWX, WOW-BE, or native ATHER packets.
    Instantly runs through the Anomaly Detection engine and updates station state.
    """
    try:
        stn_id, normalized_data = IngestionAdapter.parse_payload(payload)
        updated_stn = station_service.ingest_observation(stn_id, normalized_data)
        return {
            "status": "success",
            "station_id": stn_id,
            "station": updated_stn
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
