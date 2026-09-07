"""
Unit tests for Layer 1: Thermodynamic Physics Validation (MetPy).
"""
from datetime import datetime
import pytest
from ather.data.schema import AWSReading
from ather.engine.layer1_physics import PhysicsValidationLayer

@pytest.fixture
def physics_layer():
    return PhysicsValidationLayer()

def test_normal_atmospheric_reading(physics_layer):
    reading = AWSReading(
        station_id="TEST_STATION",
        timestamp=datetime.now(),
        temperature_c=18.5,
        pressure_hpa=990.0,
        humidity_pct=65.0,
        dew_point_c=11.8,
        elevation_m=207.0
    )
    score, is_veto, reason = physics_layer.evaluate(reading)
    assert score == 0.0
    assert not is_veto
    assert reason is None

def test_dew_point_exceeds_ambient_veto(physics_layer):
    reading = AWSReading(
        station_id="TEST_STATION",
        timestamp=datetime.now(),
        temperature_c=15.0,
        pressure_hpa=1000.0,
        humidity_pct=95.0,
        dew_point_c=25.0,  # Impossible: dew point > ambient temp
        elevation_m=207.0
    )
    score, is_veto, reason = physics_layer.evaluate(reading)
    assert score == 1.0
    assert is_veto
    assert "Dew point" in reason

def test_out_of_bounds_temperature_veto(physics_layer):
    reading = AWSReading(
        station_id="TEST_STATION",
        timestamp=datetime.now(),
        temperature_c=85.0,  # Beyond terrestrial record
        pressure_hpa=1000.0,
        humidity_pct=50.0,
        elevation_m=207.0
    )
    score, is_veto, reason = physics_layer.evaluate(reading)
    assert score == 1.0
    assert is_veto
    assert "terrestrial boundaries" in reason

def test_barometric_altitude_discrepancy(physics_layer):
    reading = AWSReading(
        station_id="TEST_STATION",
        timestamp=datetime.now(),
        temperature_c=15.0,
        pressure_hpa=750.0,  # Unusually low for 207m elevation (standard is ~989 hPa)
        humidity_pct=50.0,
        elevation_m=207.0
    )
    score, is_veto, reason = physics_layer.evaluate(reading)
    assert score > 0.5
    assert not is_veto  # Not a hard thermodynamic veto, but an altitude discrepancy
    assert "Barometric Discrepancy" in reason
