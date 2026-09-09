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
from .anomaly.detector import detector
from .simulation import service as simulation_service
from .incidents import service as incident_service

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

@app.get("/api/stations/{station_id}/anomaly")
def get_station_anomaly(station_id: str):
    """Returns canonical §16 anomaly detection results, conformal confidence, and root cause diagnosis."""
    anomaly_data = station_service.get_station_anomaly(station_id)
    if not anomaly_data:
        raise HTTPException(status_code=404, detail=f"Station '{station_id}' not found")
    return anomaly_data

@app.get("/api/stations/{station_id}/debug")
def get_station_debug_trace(station_id: str):
    """
    Diagnostic & validation endpoint (§22) tracing raw value → normalized reading → 
    5 layer inputs & outputs → conformal fusion → root cause diagnosis.
    """
    stn = station_service.get_station(station_id)
    if not stn:
        raise HTTPException(status_code=404, detail=f"Station '{station_id}' not found")

    from schema import station_dict_to_reading
    reading = station_dict_to_reading(stn)
    alert = detector.get_station_alert(station_id)
    if not alert:
        detector.evaluate_station(stn)
        alert = detector.get_station_alert(station_id)

    return {
        "station_id": station_id,
        "station_metadata": {
            "name": stn.get("name"),
            "town": stn.get("town"),
            "coordinates": [stn.get("latitude"), stn.get("longitude")],
            "elevation": stn.get("elevation")
        },
        "raw_json_values": {
            "temperature": stn.get("temperature"),
            "pressure": stn.get("pressure"),
            "humidity": stn.get("humidity"),
            "windSpeed": stn.get("windSpeed"),
            "windDirection": stn.get("windDirection")
        },
        "normalized_reading": reading.to_dict(),
        "data_quality": reading.data_quality,
        "layer_scores": alert.layer_scores if alert else {},
        "layer_details": alert.layer_details if alert else {},
        "fusion": alert.layer_details.get("fusion") if alert else {},
        "diagnosis": {
            "status": alert.status if alert else "UNKNOWN",
            "is_anomaly": alert.is_anomaly if alert else False,
            "root_cause": alert.root_cause.value if alert else "UNKNOWN",
            "diagnosis_confidence": alert.diagnosis_confidence.value if alert else "UNKNOWN",
            "primary_signal": alert.primary_signal if alert else "",
            "evidence": alert.reasons if alert else [],
            "alternatives": alert.alternative_causes if alert else [],
            "operator_action": alert.operator_action if alert else ""
        },
        "explanation": alert.explanation if alert else "",
        "canonical_result": alert.canonical_result if alert else None
    }

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


# ─────────────────────────────────────────────────────────────────
# ATHER TEST LAB — Isolated Simulation Engine (Phase 5-12)
# ─────────────────────────────────────────────────────────────────

@app.get("/api/simulation/scenarios")
def get_simulation_scenarios():
    """Lists the predefined ATHER Test Lab fault-injection scenarios."""
    return {"scenarios": simulation_service.list_scenarios()}

@app.post("/api/simulation/run")
def run_simulation(payload: Dict[str, Any]):
    """
    Runs a predefined scenario through a fresh, isolated AnomalyDetector
    instance — the SAME diagnostic engine production uses. Never touches
    real station state, the production detector singleton, or real
    incidents. See app/simulation/service.py for the isolation guarantee.
    """
    scenario_id = payload.get("scenario_id")
    if not scenario_id:
        raise HTTPException(status_code=400, detail="scenario_id is required")
    base_station_id = payload.get("base_station_id")
    try:
        return simulation_service.run_simulation(scenario_id, base_station_id=base_station_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────────────────────────
# ATHER INCIDENT WORKFLOW (Phase 13-15)
# ─────────────────────────────────────────────────────────────────

@app.get("/api/incidents")
def list_incidents(state: str = None):
    """Lists tracked incident records for the Anomalies workspace
    (Active/Resolved/All tabs). Only reflects incidents that have actually
    been created (an actionable station was looked at at least once) — this
    is not a full historical anomaly log, and the in-memory store resets on
    backend restart."""
    return {"incidents": incident_service.incident_store.list_all(state=state)}

@app.get("/api/stations/{station_id}/incident")
def get_incident(station_id: str):
    """Returns the current incident record for a station (auto-created from
    diagnostic evidence if an actionable anomaly exists and none is open)."""
    incident = incident_service.incident_store.get_or_create(station_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"No incident data available for '{station_id}'")
    return incident

@app.post("/api/stations/{station_id}/incident/acknowledge")
def acknowledge_incident(station_id: str):
    incident = incident_service.incident_store.acknowledge(station_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Station '{station_id}' not found")
    return incident

@app.post("/api/stations/{station_id}/incident/investigate")
def investigate_incident(station_id: str):
    incident = incident_service.incident_store.investigate(station_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Station '{station_id}' not found")
    return incident

@app.post("/api/stations/{station_id}/incident/resolve")
def resolve_incident(station_id: str):
    incident = incident_service.incident_store.resolve(station_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Station '{station_id}' not found")
    return incident

@app.post("/api/stations/{station_id}/incident/dismiss")
def dismiss_incident(station_id: str):
    incident = incident_service.incident_store.dismiss(station_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Station '{station_id}' not found")
    return incident

@app.get("/api/stations/{station_id}/escalation-preview")
def get_escalation_preview(station_id: str):
    """Builds a preview of what an escalation alert WOULD contain. This never
    sends a real email/SMS/notification — see app/incidents/service.py."""
    preview = incident_service.incident_store.build_escalation_preview(station_id)
    if not preview:
        raise HTTPException(status_code=404, detail=f"Station '{station_id}' not found")
    return preview

@app.post("/api/stations/{station_id}/escalation-preview/mark-escalated")
def mark_escalated(station_id: str):
    incident = incident_service.incident_store.mark_escalated(station_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Station '{station_id}' not found")
    return incident
