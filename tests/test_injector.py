"""
Unit tests for synthetic fault injection pipeline.
"""
import pandas as pd
import numpy as np
from ather.simulator.injector import FaultInjector
from ather.data.schema import FaultType

def test_fault_injection_spikes():
    # Synthetic clean time series
    dates = pd.date_range("2026-01-01", periods=500, freq="10min")
    df = pd.DataFrame({
        "timestamp": dates,
        "temperature_c": np.linspace(10, 20, 500),
        "pressure_hpa": np.full(500, 1000.0),
        "humidity_pct": np.full(500, 60.0),
        "dew_point_c": np.full(500, 5.0),
        "station_id": "TEST",
        "lat": 50.0,
        "lon": 10.0,
        "elevation_m": 100.0
    })

    injector = FaultInjector(random_seed=42)
    injected = injector.inject_spikes(df, fraction=0.04)

    assert injected.anomaly_labels.sum() > 0
    assert (injected.fault_types == FaultType.SENSOR_SPIKE.value).sum() > 0
    assert len(injected.data) == len(df)

def test_fault_injection_frozen():
    dates = pd.date_range("2026-01-01", periods=200, freq="10min")
    df = pd.DataFrame({
        "timestamp": dates,
        "temperature_c": np.sin(np.linspace(0, 10, 200)) * 5 + 15,
        "pressure_hpa": np.full(200, 1000.0),
        "humidity_pct": np.full(200, 60.0),
        "station_id": "TEST",
        "lat": 50.0,
        "lon": 10.0,
        "elevation_m": 100.0
    })

    injector = FaultInjector(random_seed=42)
    injected = injector.inject_frozen(df, num_runs=2, run_length_range=(8, 12))

    assert (injected.fault_types == FaultType.FROZEN_SENSOR.value).sum() > 0
