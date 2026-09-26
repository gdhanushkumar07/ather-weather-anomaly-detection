"""
Layer Lab (UI demonstration service) — guarantees the dashboard relies on:
  - PhysicsValidationLayer.explain() never disagrees with evaluate()
  - checks that depend on an already-invalid input are skipped, not double-counted
  - the lab never touches the live detector's station state
  - a timestamp is mandatory (season/time of day are never assumed)
"""
import os
import sys
import unittest
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from schema import AWSReading
from engine.layer1_physics import PhysicsValidationLayer

T = datetime(2026, 5, 15, 9, 30, tzinfo=timezone.utc)


class TestPhysicsExplain(unittest.TestCase):
    def setUp(self):
        self.layer = PhysicsValidationLayer()

    def _both(self, **kw):
        r = AWSReading(station_id="X", observation_timestamp=T, **kw)
        return self.layer.evaluate(r), self.layer.explain(r)

    def test_explain_verdict_matches_evaluate(self):
        for kw in (dict(temperature_c=30, pressure_hpa=1005, humidity_pct=40),
                   dict(temperature_c=30, pressure_hpa=1005, humidity_pct=104),
                   dict(temperature_c=60, pressure_hpa=1005, humidity_pct=40),
                   dict(temperature_c=30, pressure_hpa=1005, humidity_pct=60, dew_point_c=33),
                   dict(temperature_c=37, pressure_hpa=1005, humidity_pct=95)):
            (score, veto, _, _), ex = self._both(**kw)
            self.assertEqual(ex["verdict"]["veto"], veto, kw)
            self.assertAlmostEqual(ex["verdict"]["score"], round(score, 3), msg=kw)
            vetoes = [c for c in ex["checks"] if c["status"] == "veto"]
            self.assertEqual(bool(vetoes), veto, kw)

    def test_single_root_cause_is_reported_once(self):
        _, ex = self._both(temperature_c=38, pressure_hpa=1000, humidity_pct=104)
        vetoes = [c["id"] for c in ex["checks"] if c["status"] == "veto"]
        self.assertEqual(vetoes, ["humidity_range"])
        _, ex = self._both(temperature_c=38, pressure_hpa=1000, humidity_pct=50, dew_point_c=41)
        self.assertEqual([c["id"] for c in ex["checks"] if c["status"] == "veto"], ["dew_point"])

    def test_every_check_is_reported(self):
        _, ex = self._both(temperature_c=25, pressure_hpa=1010, humidity_pct=60)
        ids = [c["id"] for c in ex["checks"]]
        for cid in ("humidity_range", "temperature_range", "pressure_range", "dew_point", "wet_bulb", "hypsometric", "pinn"):
            self.assertIn(cid, ids)


class TestLabService(unittest.TestCase):
    def test_analyze_requires_timestamp_and_never_touches_live_detector(self):
        from app.layers import lab_service
        from app.anomaly.detector import detector
        with self.assertRaises(ValueError):
            lab_service.analyze({"latitude": 28.6, "longitude": 77.2, "temperature_c": 30, "pressure_hpa": 1005, "humidity_pct": 40})
        before = set(detector.layer3.states)
        out = lab_service.analyze({"latitude": 28.6, "longitude": 77.2, "timestamp": "2026-05-15T09:30:00Z",
                                   "temperature_c": 30, "pressure_hpa": 1005, "humidity_pct": 40})
        self.assertEqual(set(detector.layer3.states), before)
        self.assertIn("checks", out["physics"])
        self.assertIn("layer_score", out["multivariate"])


if __name__ == "__main__":
    unittest.main()
