"""
Comprehensive Automated Test Suite for ATHER 5-Layer Anomaly Engine
==================================================================
Tests:
1. Normal station data
2. Temperature spike
3. Pressure anomaly
4. Humidity anomaly
5. Frozen sensor
6. Multivariate inconsistency
7. Spatial outlier
8. Sensor drift
9. Multiple simultaneous anomalies
10. Missing/null sensor values
"""

import unittest
import sys
import os
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from schema import AWSReading, FaultType
from engine.layer1_physics import PhysicsValidationLayer
from engine.layer2_temporal import TemporalPatternLayer
from engine.layer3_multivariate import MultivariateConsistencyLayer
from engine.layer4_spatial import SpatialNeighborLayer
from engine.layer5_drift import SensorDriftHealthLayer
from fusion.conformal_fusion import ConformalEvidenceFusion
from app.anomaly.detector import AnomalyDetector

class TestAtherAnomalyEngine(unittest.TestCase):
    def setUp(self):
        self.detector = AnomalyDetector()

    def test_01_normal_station_data(self):
        """1. Normal station data: nominal conditions within all physical and temporal envelopes."""
        reading = AWSReading(
            station_id="STN_NORM_01",
            temperature_c=22.5,
            pressure_hpa=1013.2,
            humidity_pct=55.0,
            dew_point_c=13.0,
            lat=17.38,
            lon=78.48,
            elevation_m=500.0
        )
        alert = self.detector.evaluate_reading(reading)
        self.assertFalse(alert.is_anomaly)
        self.assertEqual(alert.status, "NORMAL")
        self.assertEqual(alert.root_cause, FaultType.NORMAL)
        self.assertFalse(alert.veto_fired)
        self.assertLess(alert.severity_score, 0.40)

    def test_02_temperature_spike(self):
        """2. Temperature spike: sudden abrupt jump in temperature."""
        now = datetime.now(timezone.utc)
        stn_id = "STN_SPIKE_01"

        # Baseline reading
        r1 = AWSReading(
            station_id=stn_id,
            timestamp=now - timedelta(minutes=10),
            temperature_c=20.0,
            pressure_hpa=1012.0,
            humidity_pct=60.0
        )
        self.detector.evaluate_reading(r1)

        # Spiked reading: +18°C in 10 minutes
        r2 = AWSReading(
            station_id=stn_id,
            timestamp=now,
            temperature_c=38.0,
            pressure_hpa=1012.0,
            humidity_pct=60.0
        )
        alert = self.detector.evaluate_reading(r2)
        self.assertTrue(alert.is_anomaly)
        self.assertGreater(alert.layer_scores["temporal"], 0.60)
        self.assertIn(alert.root_cause, [FaultType.SENSOR_SPIKE, FaultType.SINGLE_CHANNEL_FAULT])
        self.assertTrue(any("spike" in r.lower() or "temp" in r.lower() for r in alert.reasons))

    def test_03_pressure_anomaly(self):
        """3. Pressure anomaly: non-physical barometric reading or rapid drop."""
        reading = AWSReading(
            station_id="STN_PRESS_01",
            temperature_c=22.0,
            pressure_hpa=250.0,  # Below physical threshold (300 hPa)
            humidity_pct=50.0,
            elevation_m=100.0
        )
        alert = self.detector.evaluate_reading(reading)
        self.assertTrue(alert.is_anomaly)
        self.assertEqual(alert.status, "ANOMALY")
        self.assertTrue(alert.veto_fired or alert.layer_scores["physics"] >= 0.8)
        self.assertTrue(any("pressure" in r.lower() for r in alert.reasons))

    def test_04_humidity_anomaly(self):
        """4. Humidity anomaly: impossible relative humidity > 100%."""
        reading = AWSReading(
            station_id="STN_HUMID_01",
            temperature_c=24.0,
            pressure_hpa=1012.0,
            humidity_pct=118.0,  # Impossible RH
            elevation_m=50.0
        )
        alert = self.detector.evaluate_reading(reading)
        self.assertTrue(alert.is_anomaly)
        self.assertTrue(alert.veto_fired)
        self.assertEqual(alert.status, "ANOMALY")
        self.assertEqual(alert.severity_score, 1.0)
        self.assertTrue(any("humidity" in r.lower() for r in alert.reasons))

    def test_05_frozen_sensor(self):
        """5. Frozen sensor: identical constant value repeated across window."""
        stn_id = "STN_FROZEN_01"
        now = datetime.now(timezone.utc)

        # Feed 14 identical temperature readings (2+ hours)
        for i in range(14, 0, -1):
            r = AWSReading(
                station_id=stn_id,
                timestamp=now - timedelta(minutes=i*10),
                temperature_c=21.435,
                pressure_hpa=1012.0 + (i * 0.1),
                humidity_pct=50.0 + (i * 0.2)
            )
            alert = self.detector.evaluate_reading(r)

        self.assertTrue(alert.is_anomaly)
        self.assertGreaterEqual(alert.layer_scores["temporal"], 0.90)
        self.assertEqual(alert.root_cause, FaultType.FROZEN_SENSOR)
        self.assertTrue(any("frozen" in r.lower() for r in alert.reasons))

    def test_06_multivariate_inconsistency(self):
        """6. Multivariate inconsistency: physically unfeasible combination (36°C & 98% RH)."""
        reading = AWSReading(
            station_id="STN_MULTI_01",
            temperature_c=36.0,
            pressure_hpa=1012.0,
            humidity_pct=98.0,  # Extreme vapor saturation at high ambient temperature
            elevation_m=200.0
        )
        alert = self.detector.evaluate_reading(reading)
        self.assertGreaterEqual(alert.layer_scores["multivariate"], 0.70)
        self.assertTrue(any("saturation" in r.lower() or "distribution" in r.lower() for r in alert.reasons))

    def test_07_spatial_outlier(self):
        """7. Spatial outlier: isolated station sharply diverges from neighboring cluster."""
        target = AWSReading(
            station_id="STN_TARGET_01",
            lat=20.0,
            lon=75.0,
            elevation_m=300.0,
            temperature_c=41.5,  # Outlier compared to neighbors
            pressure_hpa=1012.0,
            humidity_pct=50.0
        )

        # 4 Neighbors reporting ~24.0°C within 50 km
        neighbors = [
            AWSReading(station_id=f"NEIGHBOR_{i}", lat=20.0 + (i * 0.05), lon=75.0 + (i * 0.05), elevation_m=300.0,
                       temperature_c=24.0 + (i * 0.2), pressure_hpa=1012.0, humidity_pct=52.0)
            for i in range(1, 5)
        ]

        alert = self.detector.evaluate_reading(target, neighbors=neighbors)
        self.assertGreater(alert.layer_scores["spatial"], 0.60)
        self.assertTrue(any("neighbor" in r.lower() or "disagrees" in r.lower() for r in alert.reasons))

    def test_08_sensor_drift(self):
        """8. Sensor drift: cumulative calibration drift detected by CUSUM."""
        stn_id = "STN_DRIFT_01"
        now = datetime.now(timezone.utc)

        # Feed progressive upward bias
        for i in range(30):
            r = AWSReading(
                station_id=stn_id,
                timestamp=now - timedelta(minutes=(30 - i) * 10),
                temperature_c=20.0 + (i * 0.6), # Accumulating bias
                pressure_hpa=1013.0,
                humidity_pct=50.0
            )
            alert = self.detector.evaluate_reading(r)

        self.assertGreater(alert.layer_scores["drift"], 0.50)
        self.assertLess(alert.sensor_health_index, 90.0)

    def test_09_multiple_simultaneous_anomalies(self):
        """9. Multiple simultaneous anomalies: physics veto + temporal spike."""
        now = datetime.now(timezone.utc)
        stn_id = "STN_MULTI_FAULT_01"

        r1 = AWSReading(
            station_id=stn_id,
            timestamp=now - timedelta(minutes=10),
            temperature_c=18.0,
            pressure_hpa=1012.0,
            humidity_pct=50.0
        )
        self.detector.evaluate_reading(r1)

        # Reading with temperature spike (+25°C) and non-physical RH (110%)
        r2 = AWSReading(
            station_id=stn_id,
            timestamp=now,
            temperature_c=43.0,
            pressure_hpa=1012.0,
            humidity_pct=110.0
        )
        alert = self.detector.evaluate_reading(r2)
        self.assertTrue(alert.is_anomaly)
        self.assertTrue(alert.veto_fired)
        self.assertEqual(alert.status, "ANOMALY")
        self.assertGreaterEqual(alert.confidence_score, 0.95)
        self.assertGreaterEqual(len(alert.reasons), 2)

    def test_10_missing_null_sensor_values(self):
        """10. Missing/null sensor values: engine must not crash when sensor channels are null."""
        # Partially null reading
        reading_partial = AWSReading(
            station_id="STN_NULL_01",
            temperature_c=25.0,
            pressure_hpa=None,
            humidity_pct=None,
            elevation_m=None
        )
        alert1 = self.detector.evaluate_reading(reading_partial)
        self.assertIsNotNone(alert1)
        self.assertIn(alert1.status, ["NORMAL", "WARNING"])

        # Completely empty telemetry reading
        reading_empty = AWSReading(
            station_id="STN_EMPTY_01",
            temperature_c=None,
            pressure_hpa=None,
            humidity_pct=None,
            dew_point_c=None,
            elevation_m=None
        )
        alert2 = self.detector.evaluate_reading(reading_empty)
        self.assertIsNotNone(alert2)
        self.assertEqual(alert2.status, "NORMAL")
        self.assertFalse(alert2.is_anomaly)

    def test_11_zero_pressure_treated_as_missing(self):
        """11. 0.0 pressure is treated as missing/zero-substituted, NOT a physics veto."""
        stn_dict = {
            "id": "ATHER-ZEU-0210",
            "name": "Breznik",
            "temperature": 22.0,
            "pressure": 0.0,  # 0.0 null sentinel
            "humidity": 50.0,
            "latitude": 42.74,
            "longitude": 22.90
        }
        status, legacy_dict = self.detector.evaluate_station(stn_dict)
        alert = self.detector.get_station_alert("ATHER-ZEU-0210")
        self.assertIsNotNone(alert)
        self.assertFalse(alert.veto_fired)
        self.assertNotEqual(alert.status, "ANOMALY")
        # Raw reading should have pressure None, quality ZERO_SUBSTITUTED
        dq = alert.data_quality_summary
        self.assertIn("pressure_hpa", dq.get("zero_substituted_fields", []))

    def test_12_single_layer_evidence_low_confidence(self):
        """12. Single-layer evidence must be capped at <= 0.65 confidence."""
        now = datetime.now(timezone.utc)
        stn_id = "STN_SINGLE_LAYER_01"
        r1 = AWSReading(station_id=stn_id, timestamp=now - timedelta(minutes=10), temperature_c=20.0, pressure_hpa=1013.0, humidity_pct=50.0)
        self.detector.evaluate_reading(r1)
        # Only temporal spike triggers (physics, multivariate, spatial, drift normal)
        r2 = AWSReading(station_id=stn_id, timestamp=now, temperature_c=36.0, pressure_hpa=1013.0, humidity_pct=50.0)
        alert = self.detector.evaluate_reading(r2)
        self.assertLessEqual(alert.confidence_score, 0.65)

    def test_13_temporal_insufficient_data(self):
        """13. Temporal pattern layer returns INSUFFICIENT_DATA when history is inadequate."""
        reading = AWSReading(station_id="STN_NEW_01", temperature_c=22.0, pressure_hpa=1013.0, humidity_pct=50.0)
        alert = self.detector.evaluate_reading(reading)
        temporal_card = alert.canonical_result["layers"]["temporal"]
        self.assertEqual(temporal_card["status"], "INSUFFICIENT_DATA")

    def test_14_multivariate_missing_channels(self):
        """14. Multivariate analysis skips gracefully when fewer than 2 valid channels exist."""
        reading = AWSReading(station_id="STN_T_ONLY_01", temperature_c=22.0, pressure_hpa=None, humidity_pct=None)
        alert = self.detector.evaluate_reading(reading)
        multi_card = alert.canonical_result["layers"]["multivariate"]
        self.assertEqual(multi_card["status"], "INSUFFICIENT_DATA")
        self.assertEqual(multi_card["score"], 0.0)

    def test_15_spatial_insufficient_neighbors(self):
        """15. Spatial layer returns INSUFFICIENT_DATA when fewer than 2 neighbors are available."""
        target = AWSReading(station_id="STN_ISOLATED_01", lat=10.0, lon=10.0, temperature_c=40.0, pressure_hpa=1013.0, humidity_pct=50.0)
        # Only 1 neighbor
        neighbor = [AWSReading(station_id="NEIGHBOR_SOLO", lat=10.05, lon=10.05, temperature_c=22.0, pressure_hpa=1013.0, humidity_pct=50.0)]
        alert = self.detector.evaluate_reading(target, neighbors=neighbor)
        spatial_card = alert.canonical_result["layers"]["spatial"]
        self.assertEqual(spatial_card["status"], "INSUFFICIENT_DATA")


if __name__ == "__main__":
    unittest.main()
