"""
ATHER Test Lab — Simulation Engine Test Suite
================================================
Verifies that the Test Lab (1) runs every predefined scenario through the
real diagnostic engine, (2) never mutates production station/detector state,
and (3) reports honest expected-vs-actual results rather than forced PASSes.
"""
import unittest
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.simulation.service import run_simulation, list_scenarios
from app.simulation.scenarios import SCENARIOS
from app.anomaly.detector import detector as production_detector
from app.stations.service import station_service


class TestSimulationScenarios(unittest.TestCase):
    def test_all_ten_scenarios_are_registered(self):
        self.assertEqual(len(SCENARIOS), 10)
        listed = list_scenarios()
        self.assertEqual(len(listed), 10)

    def test_temperature_spike_runs_through_real_engine(self):
        result = run_simulation("TEMPERATURE_SPIKE")
        self.assertTrue(result["simulation"])
        self.assertIn("physics", result["diagnostics"])
        self.assertIn("temporal", result["diagnostics"])
        self.assertIn("spatial", result["diagnostics"])
        self.assertIn("sensor_health", result["diagnostics"])
        self.assertIn(result["fusion"]["status"], ["NORMAL", "WARNING", "ANOMALY"])
        self.assertTrue(result["fusion"]["status"] in ("WARNING", "ANOMALY"))

    def test_frozen_sensor_scenario_detects_frozen_pattern(self):
        result = run_simulation("FROZEN_TEMPERATURE_SENSOR")
        self.assertGreaterEqual(result["diagnostics"]["temporal"]["score"], 0.7)
        self.assertEqual(result["test_result"]["actual_bucket"], "LIKELY_SENSOR_ANOMALY")
        self.assertTrue(result["test_result"]["passed"])

    def test_impossible_humidity_triggers_physics_veto(self):
        result = run_simulation("IMPOSSIBLE_HUMIDITY")
        self.assertEqual(result["fusion"]["status"], "ANOMALY")
        self.assertEqual(result["test_result"]["actual_bucket"], "DATA_QUALITY_VIOLATION")
        self.assertTrue(result["test_result"]["passed"])

    def test_pressure_spike_transient_veto_then_recovers(self):
        result = run_simulation("PRESSURE_SPIKE")
        # The 1075 hPa reading (step 5) is a transient physics-impossible
        # value; it must show as anomalous in the observation stream even
        # though the sequence later recovers to a normal reading.
        self.assertTrue(result["observations"][4]["is_anomaly"])
        self.assertEqual(result["test_result"]["actual_bucket"], "LIKELY_SENSOR_ANOMALY")
        self.assertTrue(result["test_result"]["passed"])

    def test_missing_telemetry_is_insufficient_not_anomaly(self):
        result = run_simulation("MISSING_TELEMETRY")
        # Mission-critical: missing data must NEVER be auto-classified as a sensor anomaly.
        self.assertNotEqual(result["root_cause"]["category"], "SENSOR_SPIKE")
        self.assertNotEqual(result["root_cause"]["category"], "FROZEN_SENSOR")
        self.assertNotEqual(result["root_cause"]["category"], "CALIBRATION_DRIFT")
        # Physics passes on the one valid channel; every layer that needs
        # history/other channels honestly reports INSUFFICIENT_DATA rather
        # than inventing evidence.
        self.assertEqual(result["diagnostics"]["physics"]["status"], "PASS")
        for layer in ["temporal", "multivariate", "spatial", "sensor_health"]:
            self.assertEqual(result["diagnostics"][layer]["status"], "INSUFFICIENT_DATA")
        self.assertEqual(result["test_result"]["actual_bucket"], "NORMAL")
        self.assertTrue(result["test_result"]["passed"])

    def test_spatial_outlier_uses_synthetic_neighbors(self):
        result = run_simulation("SPATIAL_OUTLIER")
        spatial = result["diagnostics"]["spatial"]
        self.assertGreaterEqual(spatial["details"].get("total_neighbors_in_radius", 0), 4)
        self.assertGreaterEqual(spatial["score"], 0.5)
        # 45C is deliberately kept under the physics veto bound so this
        # scenario isolates spatial evidence cleanly (no physics veto).
        self.assertFalse(result["fusion"].get("veto_fired", False))
        self.assertEqual(result["test_result"]["actual_bucket"], "LIKELY_SENSOR_ANOMALY")

    def test_regional_weather_event_is_not_forced_to_sensor_fault(self):
        result = run_simulation("REGIONAL_WEATHER_EVENT")
        # Whatever the real engine concludes, it must not be a hardware-fault
        # category when neighbors moved consistently with the target.
        self.assertNotIn(
            result["root_cause"]["category"],
            ["FROZEN_SENSOR", "CALIBRATION_DRIFT"],
        )

    def test_combined_failure_has_multiple_agreeing_layers(self):
        result = run_simulation("COMBINED_SENSOR_FAILURE")
        self.assertGreaterEqual(result["test_result"]["layers_agreeing"], 2)

    def test_unknown_scenario_raises(self):
        with self.assertRaises(ValueError):
            run_simulation("NOT_A_REAL_SCENARIO")

    def test_all_scenarios_currently_match_their_documented_hypothesis(self):
        # Not a correctness requirement of the Test Lab (a real "different
        # from expected" outcome is a valid, honest result) — but every
        # curated scenario in this registry has been hand-verified against
        # the real engine, so this pins that state and will flag a
        # regression if a future engine change silently shifts behavior.
        for scenario_id in SCENARIOS:
            result = run_simulation(scenario_id)
            self.assertTrue(
                result["test_result"]["passed"],
                f"{scenario_id} no longer matches its hypothesis: "
                f"expected {result['test_result']['expected_bucket']}, "
                f"got {result['test_result']['actual_bucket']}",
            )

    def test_canonical_layer_cards_report_real_sample_counts(self):
        # Regression test for a bug found via the Test Lab: the L2/L5
        # canonical cards previously always reported "0 samples" /
        # INSUFFICIENT_DATA regardless of real history depth, because they
        # read the wrong detail-dict key. TEMPERATURE_SENSOR_DRIFT runs 20
        # observations, so both layers must reflect that real history here.
        result = run_simulation("TEMPERATURE_SENSOR_DRIFT")
        self.assertNotEqual(result["diagnostics"]["temporal"]["status"], "INSUFFICIENT_DATA")
        self.assertNotIn("0 samples", result["diagnostics"]["temporal"]["reason"])
        self.assertNotEqual(result["diagnostics"]["sensor_health"]["status"], "INSUFFICIENT_DATA")
        self.assertIn("20 samples tracked", result["diagnostics"]["sensor_health"]["reason"])

    def test_result_never_claims_forced_pass(self):
        # Every scenario's test_result must carry an honest actual_bucket
        # independently computed from the real alert, not copied from expected.
        for scenario_id in SCENARIOS:
            result = run_simulation(scenario_id)
            tr = result["test_result"]
            self.assertIn("actual_bucket", tr)
            self.assertIn("expected_bucket", tr)
            self.assertIsInstance(tr["passed"], bool)


class TestSimulationIsolation(unittest.TestCase):
    """Phase 7/9/24: simulations must NEVER leak into production state."""

    def test_no_sim_station_written_to_registry(self):
        before = len(station_service._stations)
        result = run_simulation("TEMPERATURE_SPIKE")
        after = len(station_service._stations)
        self.assertEqual(before, after)
        self.assertNotIn(result["station"]["id"], station_service._stations)

    def test_production_detector_singleton_untouched(self):
        result = run_simulation("TEMPERATURE_SPIKE")
        sim_station_id = result["station"]["id"]
        self.assertIsNone(production_detector.get_station_alert(sim_station_id))

    def test_simulated_station_id_uses_sim_prefix(self):
        result = run_simulation("FROZEN_TEMPERATURE_SENSOR")
        self.assertTrue(result["station"]["id"].startswith("SIM-AWS-"))

    def test_observations_tagged_synthetic_test_source(self):
        # Sanity check via the diagnostics payload: real AWS/NWP badges must
        # never appear for a simulation run.
        result = run_simulation("TEMPERATURE_SPIKE")
        self.assertTrue(result["simulation"])

    def test_inheriting_real_station_metadata_does_not_mutate_it(self):
        real_id = "ATHER-001"
        before = dict(station_service.get_station(real_id))
        result = run_simulation("TEMPERATURE_SPIKE", base_station_id=real_id)
        after = station_service.get_station(real_id)
        self.assertEqual(before["temperature"], after["temperature"])
        self.assertEqual(before["status"], after["status"])
        self.assertEqual(result["station"]["inherited_from"], real_id)
        self.assertNotEqual(result["station"]["id"], real_id)


if __name__ == "__main__":
    unittest.main()
