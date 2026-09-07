"""
End-to-end unit tests for ATHER pipeline anomaly detection and self-healing.
"""
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from ather.pipeline import AtherPipeline
from ather.data.schema import AWSReading, FaultType

def test_pipeline_end_to_end():
    pipeline = AtherPipeline()

    # Create dummy calibration data
    timestamps = [datetime(2026, 1, 1) + timedelta(minutes=10*i) for i in range(1000)]
    clean_df = pd.DataFrame({
        "timestamp": timestamps,
        "temperature_c": np.random.normal(12.0, 2.0, 1000),
        "pressure_hpa": np.random.normal(990.0, 3.0, 1000),
        "humidity_pct": np.random.uniform(50.0, 80.0, 1000),
        "dew_point_c": np.random.normal(7.0, 2.0, 1000),
        "station_id": "AWS_JENA_01",
        "lat": 50.93,
        "lon": 11.58,
        "elevation_m": 207.0
    })

    pipeline.train_and_calibrate(clean_df, calibration_samples=200)

    # 1. Test normal reading
    normal_reading = AWSReading(
        station_id="AWS_JENA_01",
        timestamp=datetime.now(),
        temperature_c=12.5,
        pressure_hpa=990.0,
        humidity_pct=65.0,
        dew_point_c=6.0,
        elevation_m=207.0
    )
    alert_norm = pipeline.process_reading(normal_reading)
    assert not alert_norm.is_anomaly
    assert alert_norm.root_cause == FaultType.NORMAL

    # 2. Test sudden spike reading
    spike_reading = AWSReading(
        station_id="AWS_JENA_01",
        timestamp=datetime.now() + timedelta(minutes=10),
        temperature_c=35.5, # +23°C sudden jump
        pressure_hpa=990.0,
        humidity_pct=65.0,
        dew_point_c=6.0,
        elevation_m=207.0
    )
    alert_spike = pipeline.process_reading(spike_reading)
    assert alert_spike.is_anomaly
    assert alert_spike.root_cause in [FaultType.SENSOR_SPIKE, FaultType.SINGLE_CHANNEL_FAULT]
    assert alert_spike.corrected_values["temperature_c"] != 35.5
