"""
Layer 3 / Layer 5 evaluation contract.

Layer 3 evaluates only when the reading's pressure convention is DECLARED
(MSL, or SURFACE + authoritative elevation); Layer 5 evaluates only once a
channel has >= MIN_SAMPLES_FOR_DRIFT valid samples. When they evaluate, their
evidence must reach fusion; when they cannot, the real reason is reported.
The pressure convention must survive the real-time pipeline contract.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.anomaly.detector import AnomalyDetector  # noqa: E402
from app.pipeline.models import ObservationIn  # noqa: E402
from app.pipeline.normalize import normalize  # noqa: E402
from engine.layer5_drift import MIN_SAMPLES_FOR_DRIFT  # noqa: E402
from schema import AWSReading  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 9, 27, 6, 0, tzinfo=UTC)


def reading(sid, i=0, conv="MSL", elev=0.0, t=28.0, p=1009.0, rh=62.0, lat=12.95, lon=77.58):
    return AWSReading(station_id=sid, timestamp=T0 + timedelta(minutes=10 * i), temperature_c=t,
                      pressure_hpa=p, humidity_pct=rh, lat=lat, lon=lon, elevation_m=elev,
                      pressure_convention=conv, source="AWS_IN_SITU")


def neighbours(i, n=4, t=28.0, p=1009.0, rh=62.0):
    return [reading(f"N{j}", i, t=t + 0.2 * j, p=p + 0.1 * j, rh=rh - 0.5 * j, lat=12.95 + 0.02 * (j + 1)) for j in range(n)]


def avail(alert):
    return alert.canonical_result["evidence_availability"]


def fusion_avail(alert):
    return alert.layer_details["fusion"]["evidence_availability"]


class TestLayer3PressureContract(unittest.TestCase):
    def test_A_msl_pressure_evaluates(self):
        a = AnomalyDetector().evaluate_reading(reading("A", conv="MSL"))
        self.assertTrue(avail(a)["multivariate"]["available"], avail(a)["multivariate"])
        self.assertEqual(a.layer_details["multivariate"]["status"], "EVALUATED")
        self.assertTrue(fusion_avail(a)["multivariate"]["available"])

    def test_B_surface_pressure_with_elevation_evaluates_via_conversion(self):
        a = AnomalyDetector().evaluate_reading(reading("B", conv="SURFACE", elev=920.0, p=912.0, t=24.0))
        d = a.layer_details["multivariate"]
        self.assertTrue(avail(a)["multivariate"]["available"], d.get("skip_reason") or d.get("note"))
        self.assertEqual(d.get("pressure_convention"), "SURFACE")

    def test_B2_surface_pressure_without_elevation_is_not_invented(self):
        a = AnomalyDetector().evaluate_reading(reading("B2", conv="SURFACE", elev=0.0, p=912.0))
        self.assertFalse(avail(a)["multivariate"]["available"])
        self.assertIn("elevation", (avail(a)["multivariate"]["reason"] or "").lower())

    def test_C_unknown_convention_not_evaluated_with_reason(self):
        a = AnomalyDetector().evaluate_reading(reading("C", conv=None))
        self.assertFalse(avail(a)["multivariate"]["available"])
        self.assertIn("convention", (avail(a)["multivariate"]["reason"] or "").lower())
        self.assertFalse(fusion_avail(a)["multivariate"]["available"])


class TestLayer5AvailabilityContract(unittest.TestCase):
    def test_D_insufficient_history_not_evaluated(self):
        det = AnomalyDetector()
        for i in range(MIN_SAMPLES_FOR_DRIFT - 1):
            a = det.evaluate_reading(reading("D", i), neighbors=neighbours(i))
        self.assertEqual(a.layer_details["drift"]["status"], "INSUFFICIENT_DATA")
        self.assertFalse(avail(a)["drift"]["available"])
        self.assertIn("insufficient history", avail(a)["drift"]["reason"])
        self.assertNotEqual(a.canonical_result["layers"]["sensor_health"]["status"], "PASS")

    def test_E_sufficient_history_evaluated(self):
        det = AnomalyDetector()
        for i in range(MIN_SAMPLES_FOR_DRIFT + 2):
            a = det.evaluate_reading(reading("E", i, t=28.0 + 0.01 * i), neighbors=neighbours(i))
        self.assertEqual(a.layer_details["drift"]["status"], "EVALUATED")
        self.assertTrue(avail(a)["drift"]["available"])
        self.assertTrue(fusion_avail(a)["drift"]["available"])

    def test_F_detected_drift_reaches_fusion(self):
        det = AnomalyDetector()
        for i in range(30):  # station drifts +0.6 °C per step away from stable neighbours
            a = det.evaluate_reading(reading("F", i, t=28.0 + 0.6 * i), neighbors=neighbours(i))
        self.assertGreater(a.layer_scores["drift"], 0.0)
        self.assertTrue(fusion_avail(a)["drift"]["available"])
        self.assertNotEqual(a.canonical_result["layers"]["sensor_health"]["status"], "INSUFFICIENT_DATA")

    def test_G_layer3_and_layer5_both_reach_fusion(self):
        det = AnomalyDetector()
        for i in range(MIN_SAMPLES_FOR_DRIFT + 2):
            a = det.evaluate_reading(reading("G", i), neighbors=neighbours(i))
        fa = fusion_avail(a)
        self.assertTrue(fa["multivariate"]["available"])
        self.assertTrue(fa["drift"]["available"])


class TestPipelineCarriesConvention(unittest.TestCase):
    def test_convention_survives_ingest_normalize(self):
        o = ObservationIn(station_id="X", observed_at=T0, source="AWS_IN_SITU", pressure=1009.0,
                          temperature=28.0, humidity=60.0, pressure_convention="msl")
        self.assertEqual(normalize(o, received_at=T0).pressure_convention, "MSL")

    def test_undeclared_convention_stays_unknown(self):
        o = ObservationIn(station_id="X", observed_at=T0, source="AWS_IN_SITU", pressure=1009.0)
        self.assertIsNone(normalize(o, received_at=T0).pressure_convention)

    def test_invalid_convention_rejected(self):
        with self.assertRaises(Exception):
            ObservationIn(station_id="X", observed_at=T0, source="AWS_IN_SITU", pressure_convention="QNH-ish")

    def test_simulator_inherits_reference_convention(self):
        from app.sources.simulation import SyntheticNetwork
        base = {"latitude": 12.9, "longitude": 77.5, "name": "S"}
        msl = SyntheticNetwork.from_station_dicts([dict(base, id="S1")], lambda s: {"pressure": 1012.0, "pressureConvention": "MSL"})
        sfc = SyntheticNetwork.from_station_dicts([dict(base, id="S2")], lambda s: {"pressure": 950.0, "pressureConvention": "SURFACE"})
        unk = SyntheticNetwork.from_station_dicts([dict(base, id="S3")], lambda s: {"pressure": 1012.0, "pressureConvention": None})
        none = SyntheticNetwork.from_station_dicts([dict(base, id="S4")], lambda s: None)
        self.assertEqual(msl.stations["S1"].p_convention, "MSL")
        self.assertEqual(sfc.stations["S2"].p_convention, "SURFACE")
        self.assertIsNone(unk.stations["S3"].p_convention)
        self.assertEqual(none.stations["S4"].p_convention, "MSL")  # generator's own synthetic sea-level baseline


if __name__ == "__main__":
    unittest.main()
