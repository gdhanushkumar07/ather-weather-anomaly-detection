"""
Layer 1 PINN Test Suite.

Verifies the physics-informed neural network integrated into
engine/layer1_physics.py:
  1. Trained artifacts load and the engine reports itself available.
  2. A physically consistent reading produces near-zero residuals and no
     score contribution (must not regress the existing rule-based tests).
  3. Leave-one-out reconstruction gives a physically sensible expected
     value for a missing channel (self-healing input) — checked against
     the closed-form hypsometric formula the rule layer itself uses.
  4. evaluate()'s detail dict always carries physics_score, physics_reason,
     expected_value, and physics_residual as required by the Layer 1 spec.
  5. The PINN never overrides or weakens a hard veto (rules keep authority).
"""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import CONFIG
from schema import AWSReading
from engine.layer1_physics import PhysicsValidationLayer, get_pinn_engine


class TestLayer1PINN(unittest.TestCase):
    def setUp(self):
        self.layer = PhysicsValidationLayer()

    def test_01_pinn_artifacts_load(self):
        """Trained weights + normalization stats load successfully."""
        engine = get_pinn_engine()
        self.assertTrue(engine.available, "PINN engine should be available once trained (run engine/train_pinn.py)")

    def test_02_output_shape_always_present(self):
        """evaluate() always exposes physics_score/physics_reason/expected_value/physics_residual."""
        reading = AWSReading(station_id="PINN_SHAPE_01", temperature_c=24.0, pressure_hpa=1012.0,
                              humidity_pct=60.0, elevation_m=200.0)
        _, _, _, detail = self.layer.evaluate(reading)
        for key in ("physics_score", "physics_reason", "expected_value", "physics_residual"):
            self.assertIn(key, detail)

    def test_03_consistent_reading_near_zero_residual_no_score(self):
        """A physically ordinary reading must not pick up a PINN score contribution."""
        reading = AWSReading(station_id="PINN_NORMAL_01", temperature_c=22.5, pressure_hpa=1013.2,
                              humidity_pct=55.0, elevation_m=500.0)
        score, veto, reason, detail = self.layer.evaluate(reading)
        self.assertFalse(veto)
        self.assertLess(score, 0.3)
        # Residuals should be small relative to the configured tolerances.
        resid = detail["physics_residual"]
        if "temperature_c" in resid:
            self.assertLess(abs(resid["temperature_c"]), CONFIG.pinn.temp_consistency_tolerance_c * 2)
        if "humidity_pct" in resid:
            self.assertLess(abs(resid["humidity_pct"]), CONFIG.pinn.humidity_consistency_tolerance_pct * 2)

    def test_04_leaveoneout_expected_pressure_matches_hypsometric_physics(self):
        """
        Masking pressure and asking the PINN to reconstruct it from
        (T, RH, altitude) should land close to the same closed-form
        hypsometric value the rule layer itself computes — evidence the
        network genuinely learned the pressure-altitude law, not just an
        arbitrary regression.
        """
        engine = get_pinn_engine()
        self.assertTrue(engine.available)

        temp_c, elev_m = 22.0, 500.0
        phys = CONFIG.physics
        exponent = phys.gravity / (phys.gas_constant * phys.temp_lapse_rate)
        base = 1.0 - (phys.temp_lapse_rate * elev_m) / phys.sea_level_temp_k
        hypsometric_expected = phys.sea_level_pressure_hpa * (base ** exponent)

        pinn_expected = engine.leave_one_out_expected(temp_c, None, 55.0, elev_m, "pressure_hpa")
        self.assertIsNotNone(pinn_expected)
        self.assertLess(abs(pinn_expected - hypsometric_expected), 40.0)

    def test_05_veto_authority_unaffected_by_pinn(self):
        """Hard physical impossibilities still veto at score 1.0 regardless of PINN opinion."""
        reading = AWSReading(station_id="PINN_VETO_01", temperature_c=24.0, pressure_hpa=1012.0,
                              humidity_pct=118.0, elevation_m=50.0)
        score, veto, reason, detail = self.layer.evaluate(reading)
        self.assertTrue(veto)
        self.assertEqual(score, 1.0)
        self.assertIn("humidity", reason.lower())

    def test_06_insufficient_channels_skips_pinn_gracefully(self):
        """With fewer than 2 valid channels, the PINN check must no-op, not crash."""
        reading = AWSReading(station_id="PINN_SPARSE_01", temperature_c=22.0, pressure_hpa=None, humidity_pct=None)
        score, veto, reason, detail = self.layer.evaluate(reading)
        self.assertFalse(veto)
        self.assertEqual(detail["expected_value"], {})
        self.assertEqual(detail["physics_residual"], {})


if __name__ == "__main__":
    unittest.main()
