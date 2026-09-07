"""
FastAPI route handlers for telemetry ingestion, live detection, and benchmark monitoring.
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ather.data.schema import AWSReading, AnomalyAlert, FaultType
from ather.pipeline import AtherPipeline
from ather.data.loader import JenaDataLoader
from ather.simulator.generator import StationNetworkSimulator

router = APIRouter(prefix="/api/v1", tags=["ATHER Telemetry"])

# Global pipeline instance initialized on startup
pipeline = AtherPipeline()
data_loader: Optional[JenaDataLoader] = None
simulator: Optional[StationNetworkSimulator] = None
current_stream_idx = 50000

class DetectionRequest(BaseModel):
    reading: AWSReading
    neighbors: Optional[List[AWSReading]] = None
    fast_path_only: bool = False

class FaultInjectionTrigger(BaseModel):
    fault_type: FaultType
    magnitude: float = 12.0
    channel: str = "temperature_c"

@router.post("/detect", response_model=AnomalyAlert)
def detect_anomaly(req: DetectionRequest):
    """
    Evaluates a single AWS reading through the 5-layer anomaly detection pipeline.
    """
    alert = pipeline.process_reading(
        reading=req.reading,
        neighbor_readings=req.neighbors,
        fast_path_only=req.fast_path_only
    )
    return alert

@router.get("/stream/next")
def get_next_reading(
    inject_fault: Optional[str] = Query(None, description="Inject fault: spike, frozen, drift, impossible_physics"),
    channel: str = "temperature_c"
):
    """
    Advances and returns the next simulated reading from the Jena dataset.
    Supports real-time fault injection triggers for live dashboard demos.
    """
    global current_stream_idx, data_loader, simulator

    if data_loader is None:
        data_loader = JenaDataLoader()
        df = data_loader.load_dataframe(nrows=60000)
        simulator = StationNetworkSimulator(df)

    df = data_loader.load_dataframe(nrows=current_stream_idx + 10)
    row = df.iloc[current_stream_idx]
    current_stream_idx = (current_stream_idx + 1) % len(df)

    t = float(row["temperature_c"])
    p = float(row["pressure_hpa"])
    rh = float(row["humidity_pct"])
    tdew = float(row["dew_point_c"]) if "dew_point_c" in row and pd.notna(row["dew_point_c"]) else None

    # Handle real-time fault injection requests from dashboard buttons
    if inject_fault == "spike":
        if channel == "temperature_c":
            t += 14.5
        elif channel == "pressure_hpa":
            p -= 22.0
        else:
            rh = min(100.0, rh + 45.0)

    elif inject_fault == "frozen":
        # Keep value constant from previous sample
        t = 12.34

    elif inject_fault == "drift":
        # Introduce cumulative drift
        t += 3.8

    elif inject_fault == "impossible_physics":
        # Break thermodynamic law: T_dew > T
        t = 10.0
        rh = 99.0
        tdew = 24.0  # Impossible dew point

    reading = AWSReading(
        station_id=row["station_id"],
        timestamp=row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"],
        temperature_c=t,
        pressure_hpa=p,
        humidity_pct=rh,
        dew_point_c=tdew,
        lat=float(row["lat"]),
        lon=float(row["lon"]),
        elevation_m=float(row["elevation_m"])
    )

    # Fetch contemporary neighbors from network simulator
    neighbors = simulator.get_all_stations_at_timestamp(row["timestamp"])

    # Process through pipeline
    alert = pipeline.process_reading(reading, neighbor_readings=neighbors)

    return {
        "reading": reading.to_dict(),
        "alert": alert.model_dump(),
        "neighbors_count": len(neighbors)
    }

@router.get("/station/health")
def get_station_health(station_id: str = "AWS_JENA_01"):
    """
    Returns current health status and predictive maintenance projection for a station.
    """
    tracker = pipeline.layer5_drift._get_tracker(station_id)
    error_rate = (tracker.anomaly_count / max(1, tracker.total_readings))
    health = max(5.0, min(100.0, 100.0 - error_rate * 100.0))

    return {
        "station_id": station_id,
        "health_index": round(health, 1),
        "total_readings_processed": tracker.total_readings,
        "anomalies_detected": tracker.anomaly_count,
        "status": "OPERATIONAL" if health > 70 else ("WARNING" if health > 40 else "CRITICAL")
    }

import pandas as pd
