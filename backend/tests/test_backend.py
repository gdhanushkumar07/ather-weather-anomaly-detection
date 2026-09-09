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
        
        # Check flagship reference station (computed as NORMAL by engine, not hardcoded mock anomaly)
        stn_001 = station_service.get_station("ATHER-001")
        self.assertIsNotNone(stn_001)
        self.assertEqual(stn_001["status"], "NORMAL")
        self.assertEqual(stn_001["temperature"], 32.4)
        self.assertIsNone(stn_001.get("anomaly"))

        # Check real engine-detected anomaly station (severe barometric divergence)
        stn_anom = station_service.get_station("ATHER-COW-0137")
        self.assertIsNotNone(stn_anom)
        self.assertEqual(stn_anom["status"], "ANOMALY")
        self.assertIsNotNone(stn_anom.get("anomaly"))
        self.assertEqual(stn_anom["anomaly"]["severity"], "HIGH")

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

    def test_weather_union_stations_loading(self):
        stns = station_service.get_all_stations()
        self.assertEqual(len(stns), 1951)

        # Verify Indian stations count (4 existing flagship + 296 WeatherUnion AWS)
        indian_stns = [s for s in stns if s.get("country") == "India"]
        self.assertEqual(len(indian_stns), 300)

        # Check sample Indian AWS station from CSV
        zwl = station_service.get_station("ZWL003467")
        self.assertIsNotNone(zwl)
        self.assertEqual(zwl["name"], "Banashankari AWS")
        self.assertEqual(zwl["country"], "India")
        self.assertEqual(zwl["region"], "Karnataka")
        self.assertAlmostEqual(zwl["latitude"], 12.936787, places=5)
        self.assertAlmostEqual(zwl["longitude"], 77.556079, places=5)
        self.assertEqual(zwl["status"], "OFFLINE")
        self.assertIsNone(zwl["temperature"])
        self.assertIsNone(zwl["pressure"])
        self.assertIsNone(zwl["humidity"])

        # Check search functionality for newly integrated stations
        by_locality = station_service.search("Banashankari")
        self.assertTrue(any(s["id"] == "ZWL003467" for s in by_locality))

        by_id = station_service.search("ZWL003467")
        self.assertEqual(len(by_id), 1)
        self.assertEqual(by_id[0]["id"], "ZWL003467")

        by_city = station_service.search("Bengaluru", limit=100)
        self.assertGreater(len(by_city), 10)

        # Verify rain gauge device types were excluded (e.g. ZWL003133 from Paldi is a rain gauge)
        rain_gauge = station_service.get_station("ZWL003133")
        self.assertIsNone(rain_gauge)

    def test_weather_union_telemetry_ingestion(self):
        # Ingest nominal telemetry for ZWL004900 (Rajarajeshwari Nagar AWS)
        payload = {
            "id": "ZWL004900",
            "temperature": 27.2,
            "pressure": 1011.5,
            "humidity": 65,
            "windSpeed": 12.0,
            "condition": "Partly Cloudy"
        }
        updated = station_service.ingest_observation("ZWL004900", payload)
        self.assertEqual(updated["status"], "NORMAL")
        self.assertEqual(updated["temperature"], 27.2)

        # Ingest anomalous temperature spike
        spike_payload = {
            "id": "ZWL004900",
            "temperature": 53.5,
            "pressure": 1011.5,
            "humidity": 20,
            "windSpeed": 15.0
        }
        updated_spike = station_service.ingest_observation("ZWL004900", spike_payload)
        self.assertEqual(updated_spike["status"], "ANOMALY")
        self.assertIsNotNone(updated_spike["anomaly"])

if __name__ == "__main__":
    unittest.main()
