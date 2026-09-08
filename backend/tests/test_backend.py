import unittest
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.anomaly.detector import detector
from app.stations.service import station_service
from app.ingestion.adapter import IngestionAdapter

class TestAtherBackend(unittest.TestCase):
    def test_station_loading(self):
        stns = station_service.get_all_stations()
        self.assertGreater(len(stns), 100)
        
        # Check flagship station
        stn_001 = station_service.get_station("ATHER-001")
        self.assertIsNotNone(stn_001)
        self.assertEqual(stn_001["status"], "ANOMALY")
        self.assertEqual(stn_001["temperature"], 32.4)
        self.assertEqual(stn_001["anomaly"]["parameter"], "Temperature")
        self.assertEqual(stn_001["anomaly"]["severity"], "HIGH")

    def test_geojson_generation(self):
        geojson = station_service.get_geojson(limit=20)
        self.assertEqual(geojson["type"], "FeatureCollection")
        self.assertEqual(len(geojson["features"]), 20)
        f0 = geojson["features"][0]
        self.assertIn("coordinates", f0["geometry"])
        self.assertIn("status", f0["properties"])
        self.assertIn("id", f0["properties"])

    def test_anomaly_detector_extremes(self):
        # Extreme high temp
        status, anomaly = detector.evaluate_station({"temperature": 52.0})
        self.assertEqual(status, "ANOMALY")
        self.assertEqual(anomaly["severity"], "HIGH")

        # Pressure drop
        status, anomaly = detector.evaluate_station({"pressure": 910.0})
        self.assertEqual(status, "ANOMALY")

        # Gale wind
        status, anomaly = detector.evaluate_station({"windSpeed": 85.0})
        self.assertEqual(status, "WARNING")

        # Normal condition
        status, anomaly = detector.evaluate_station({
            "temperature": 24.5,
            "pressure": 1013.2,
            "humidity": 55,
            "windSpeed": 12.0
        })
        self.assertEqual(status, "NORMAL")
        self.assertIsNone(anomaly)

    def test_ingestion_adapter(self):
        # WeeWX format
        weewx_payload = {
            "station_id": "ATHER-TEST-01",
            "outTemp": 77.0,
            "barometer": 29.92,
            "outHumidity": 50,
            "windSpeed": 10.0,
            "unit_system": "US"
        }
        stn_id, norm = IngestionAdapter.parse_payload(weewx_payload)
        self.assertEqual(stn_id, "ATHER-TEST-01")
        self.assertEqual(norm["temperature"], 25.0)
        self.assertAlmostEqual(norm["pressure"], 1013.2, places=1)

if __name__ == "__main__":
    unittest.main()
