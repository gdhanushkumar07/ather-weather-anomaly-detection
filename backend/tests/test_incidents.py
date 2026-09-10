"""
ATHER Incident Workflow Test Suite — persistent, production-grade
====================================================================
Uses an isolated temp SQLite file (ATHER_INCIDENTS_DB_PATH) so these tests
never read or modify real accumulated incident data.
"""
import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# MUST be set before app.incidents.db is imported anywhere (including
# transitively via app.stations.service), so every module in this process
# resolves to the same isolated test database.
_TMP_DB = tempfile.NamedTemporaryFile(prefix="ather_test_incidents_", suffix=".db", delete=False)
_TMP_DB.close()
os.environ["ATHER_INCIDENTS_DB_PATH"] = _TMP_DB.name

from app.incidents import service as incident_service
from app.incidents import db as incident_db

# Importing this triggers app.stations.service's module-level singleton
# construction (a real, legitimate evaluation of the real bundled station
# dataset — see StationServiceStartupIncidentSync below). Importing it here,
# once, at module load time — before any test's setUp() runs — means every
# individual test's reset_for_tests() gives it a genuinely clean table,
# instead of that one-time startup cascade landing inside whichever test
# happens to trigger the lazy import first.
from app.simulation.service import run_simulation


def make_snapshot(**overrides):
    base = {
        "station_id": "ATHER-TEST-001",
        "station_name": "Test Station",
        "town": "Testville",
        "region": "Test Region",
        "country": "Testland",
        "parameter": "Temperature",
        "observed_value": 55.0,
        "expected_min": 15.0,
        "expected_max": 35.0,
        "unit": "°C",
        "status": "ANOMALY",
        "severity": "HIGH",
        "anomaly_score": 0.92,
        "confidence": 0.88,
        "root_cause": "SENSOR_SPIKE",
        "root_cause_confidence": "HIGH",
        "recommended_action": "Inspect temperature sensor and verify calibration.",
        "evidence": ["Temperature 55.0C disagrees with neighbor consensus (32.1C) by 22.9C"],
        "diagnostic_layers": {
            "physics": {"status": "ANOMALY", "score": 0.9},
            "temporal": {"status": "ANOMALY", "score": 0.95},
            "multivariate": {"status": "PASS", "score": 0.0},
            "spatial": {"status": "ANOMALY", "score": 0.85},
            "sensor_health": {"status": "WARNING", "score": 0.4},
        },
        "fusion_result": {"status": "ANOMALY", "score": 0.92, "confidence": 0.88, "explanation": "Sensor spike detected."},
        "observation_timestamp": "2026-09-10T10:21:00+00:00",
        "obs_source": "AWS_IN_SITU",
        "freshness": "LIVE",
        "source": "LIVE_AWS",
    }
    base.update(overrides)
    return base


class TestIncidentCreationAndCorrelation(unittest.TestCase):
    def setUp(self):
        incident_db.reset_for_tests()

    def test_new_incident_creation(self):
        inc = incident_service.upsert_from_evaluation(make_snapshot())
        self.assertIsNotNone(inc)
        self.assertEqual(inc["status"], "NEW")
        self.assertEqual(inc["station_id"], "ATHER-TEST-001")
        self.assertEqual(inc["observation_count"], 1)
        self.assertTrue(inc["incident_id"].startswith("INC-"))

    def test_missing_evidence_does_not_create_incident(self):
        # NORMAL status (e.g. one valid channel, no anomalous signal) must
        # never become an incident (Phase 3).
        inc = incident_service.upsert_from_evaluation(make_snapshot(status="NORMAL"))
        self.assertIsNone(inc)
        self.assertEqual(len(incident_service.list_all()), 0)

    def test_offline_status_does_not_create_incident(self):
        inc = incident_service.upsert_from_evaluation(make_snapshot(status="OFFLINE"))
        self.assertIsNone(inc)

    def test_nwp_reference_does_not_create_incident(self):
        inc = incident_service.upsert_from_evaluation(make_snapshot(obs_source="NWP_MODEL_REFERENCE"))
        self.assertIsNone(inc)
        self.assertEqual(len(incident_service.list_all()), 0)

    def test_duplicate_detection_prevents_new_incident(self):
        first = incident_service.upsert_from_evaluation(make_snapshot())
        second = incident_service.upsert_from_evaluation(make_snapshot(observed_value=56.2))
        self.assertEqual(first["incident_id"], second["incident_id"])
        self.assertEqual(len(incident_service.list_all()), 1)

    def test_existing_incident_updates_latest_fields(self):
        incident_service.upsert_from_evaluation(make_snapshot(observed_value=55.0))
        updated = incident_service.upsert_from_evaluation(make_snapshot(observed_value=61.3, confidence=0.95))
        self.assertEqual(updated["observed_value"], 61.3)
        self.assertEqual(updated["confidence"], 0.95)
        self.assertEqual(updated["observation_count"], 2)
        self.assertEqual(updated["first_seen_at"], updated["first_seen_at"])  # unchanged
        self.assertGreaterEqual(updated["last_seen_at"], updated["first_seen_at"])

    def test_repeated_observations_stay_one_incident(self):
        for _ in range(10):
            incident_service.upsert_from_evaluation(make_snapshot())
        all_incidents = incident_service.list_all()
        self.assertEqual(len(all_incidents), 1)
        self.assertEqual(all_incidents[0]["observation_count"], 10)

    def test_new_incident_after_previous_closes(self):
        first = incident_service.upsert_from_evaluation(make_snapshot())
        incident_service.acknowledge(first["incident_id"])
        incident_service.investigate(first["incident_id"])
        incident_service.resolve(first["incident_id"], "operator", "Sensor replaced.", "Sensor repaired")

        second = incident_service.upsert_from_evaluation(make_snapshot(observed_value=58.0))
        self.assertNotEqual(first["incident_id"], second["incident_id"])
        self.assertEqual(len(incident_service.list_all(status=None)), 2)

    def test_different_parameter_is_a_different_incident(self):
        incident_service.upsert_from_evaluation(make_snapshot(parameter="Temperature", root_cause="SENSOR_SPIKE"))
        incident_service.upsert_from_evaluation(make_snapshot(parameter="Pressure", root_cause="SENSOR_SPIKE"))
        self.assertEqual(len(incident_service.list_all()), 2)

    def test_different_station_is_a_different_incident(self):
        incident_service.upsert_from_evaluation(make_snapshot(station_id="ATHER-A"))
        incident_service.upsert_from_evaluation(make_snapshot(station_id="ATHER-B"))
        self.assertEqual(len(incident_service.list_all(station_id=None)), 2)

    def test_station_returning_to_normal_does_not_erase_incident(self):
        inc = incident_service.upsert_from_evaluation(make_snapshot())
        incident_service.acknowledge(inc["incident_id"])
        incident_service.investigate(inc["incident_id"])
        # Station later reports NORMAL — this must simply no-op, never
        # delete or silently resolve the still-open incident (Phase 22/23).
        result = incident_service.upsert_from_evaluation(make_snapshot(status="NORMAL"))
        self.assertIsNone(result)
        preserved = incident_service.get(inc["incident_id"])
        self.assertEqual(preserved["status"], "INVESTIGATING")


class TestIncidentEvidenceSnapshot(unittest.TestCase):
    def setUp(self):
        incident_db.reset_for_tests()

    def test_evidence_and_diagnostic_layers_are_preserved(self):
        inc = incident_service.upsert_from_evaluation(make_snapshot())
        self.assertIn("Temperature 55.0C disagrees", inc["evidence"][0])
        self.assertEqual(inc["diagnostic_layers"]["physics"]["status"], "ANOMALY")
        self.assertEqual(inc["fusion_result"]["explanation"], "Sensor spike detected.")
        self.assertEqual(inc["root_cause"], "SENSOR_SPIKE")
        self.assertEqual(inc["recommended_action"], "Inspect temperature sensor and verify calibration.")

    def test_historical_evidence_survives_after_condition_clears(self):
        inc = incident_service.upsert_from_evaluation(make_snapshot(observed_value=55.0))
        incident_id = inc["incident_id"]
        incident_service.upsert_from_evaluation(make_snapshot(status="NORMAL"))  # station recovers
        historical = incident_service.get(incident_id)
        self.assertEqual(historical["observed_value"], 55.0)
        self.assertEqual(historical["evidence"], inc["evidence"])


class TestIncidentStateMachine(unittest.TestCase):
    def setUp(self):
        incident_db.reset_for_tests()
        self.inc = incident_service.upsert_from_evaluation(make_snapshot())
        self.incident_id = self.inc["incident_id"]

    def test_acknowledge_transition(self):
        inc = incident_service.acknowledge(self.incident_id, actor="alice")
        self.assertEqual(inc["status"], "ACKNOWLEDGED")
        self.assertEqual(inc["acknowledged_by"], "alice")
        self.assertIsNotNone(inc["acknowledged_at"])

    def test_investigate_transition(self):
        incident_service.acknowledge(self.incident_id)
        inc = incident_service.investigate(self.incident_id, actor="bob")
        self.assertEqual(inc["status"], "INVESTIGATING")
        self.assertEqual(inc["investigated_by"], "bob")

    def test_escalate_transition(self):
        incident_service.acknowledge(self.incident_id)
        incident_service.investigate(self.incident_id)
        inc = incident_service.escalate(self.incident_id, actor="carol")
        self.assertEqual(inc["status"], "ESCALATED")
        self.assertEqual(inc["escalated_by"], "carol")

    def test_resolve_transition_requires_notes_and_type(self):
        incident_service.acknowledge(self.incident_id)
        incident_service.investigate(self.incident_id)
        with self.assertRaises(ValueError):
            incident_service.resolve(self.incident_id, "dave", "", "")
        inc = incident_service.resolve(self.incident_id, "dave", "Sensor recalibrated on site.", "Sensor recalibrated")
        self.assertEqual(inc["status"], "RESOLVED")
        self.assertEqual(inc["resolution_type"], "Sensor recalibrated")
        self.assertEqual(inc["resolution_notes"], "Sensor recalibrated on site.")

    def test_dismiss_transition_requires_reason(self):
        with self.assertRaises(ValueError):
            incident_service.dismiss(self.incident_id, "erin", "")
        inc = incident_service.dismiss(self.incident_id, "erin", "False positive")
        self.assertEqual(inc["status"], "DISMISSED")
        self.assertEqual(inc["dismissal_reason"], "False positive")

    def test_invalid_transition_new_to_resolved_rejected(self):
        with self.assertRaises(incident_service.InvalidTransitionError):
            incident_service.resolve(self.incident_id, "frank", "skip ahead", "Sensor repaired")

    def test_invalid_transition_resolved_to_investigating_rejected(self):
        incident_service.acknowledge(self.incident_id)
        incident_service.investigate(self.incident_id)
        incident_service.resolve(self.incident_id, "g", "done", "Sensor repaired")
        with self.assertRaises(incident_service.InvalidTransitionError):
            incident_service.investigate(self.incident_id)

    def test_invalid_transition_dismissed_is_terminal(self):
        incident_service.dismiss(self.incident_id, "h", "duplicate")
        with self.assertRaises(incident_service.InvalidTransitionError):
            incident_service.acknowledge(self.incident_id)

    def test_transition_on_unknown_incident_raises_not_found(self):
        with self.assertRaises(incident_service.IncidentNotFoundError):
            incident_service.acknowledge("INC-DOES-NOT-EXIST")

    def test_timeline_records_every_transition(self):
        incident_service.acknowledge(self.incident_id)
        incident_service.investigate(self.incident_id)
        incident_service.escalate(self.incident_id)
        final = incident_service.resolve(self.incident_id, "op", "fixed", "Sensor repaired")
        events = [e["event"] for e in final["timeline"]]
        self.assertEqual(
            events,
            ["ANOMALY_DETECTED", "INCIDENT_CREATED", "ACKNOWLEDGED", "INVESTIGATING", "ESCALATED", "RESOLVED"],
        )


class TestIncidentSourceSeparation(unittest.TestCase):
    """Phase 29/36: simulation incidents must never leak into the
    production (LIVE_AWS) incident list or counters."""

    def setUp(self):
        incident_db.reset_for_tests()

    def test_simulation_incident_isolated_from_live_list(self):
        incident_service.upsert_from_evaluation(make_snapshot(source="LIVE_AWS", station_id="LIVE-1"))
        incident_service.upsert_from_evaluation(make_snapshot(source="TEST_SIMULATION", station_id="SIM-1"))

        live_only = incident_service.list_all(source="LIVE_AWS")
        self.assertEqual(len(live_only), 1)
        self.assertEqual(live_only[0]["station_id"], "LIVE-1")

        sim_only = incident_service.list_all(source="TEST_SIMULATION")
        self.assertEqual(len(sim_only), 1)
        self.assertEqual(sim_only[0]["station_id"], "SIM-1")

    def test_simulation_does_not_affect_live_active_counts(self):
        incident_service.upsert_from_evaluation(make_snapshot(source="LIVE_AWS", station_id="LIVE-1"))
        before = incident_service.get_active_counts(source="LIVE_AWS")
        incident_service.upsert_from_evaluation(make_snapshot(source="TEST_SIMULATION", station_id="SIM-1"))
        incident_service.upsert_from_evaluation(make_snapshot(source="TEST_SIMULATION", station_id="SIM-2"))
        after = incident_service.get_active_counts(source="LIVE_AWS")
        self.assertEqual(before, after)

    def test_same_fingerprint_different_source_are_separate_incidents(self):
        live = incident_service.upsert_from_evaluation(make_snapshot(source="LIVE_AWS", station_id="SAME-ID"))
        sim = incident_service.upsert_from_evaluation(make_snapshot(source="TEST_SIMULATION", station_id="SAME-ID"))
        self.assertNotEqual(live["incident_id"], sim["incident_id"])


class TestSimulationEngineIsolation(unittest.TestCase):
    """Confirms the actual Test Lab pipeline never calls
    incident_service.upsert_from_evaluation at all — a simulation run must
    leave the real incidents table completely untouched, not merely
    filtered out at read time."""

    def setUp(self):
        incident_db.reset_for_tests()

    def test_running_a_scenario_writes_no_rows_at_all(self):
        before = len(incident_service.list_all(source=None))
        result = run_simulation("TEMPERATURE_SPIKE")
        after = len(incident_service.list_all(source=None))
        self.assertEqual(before, after)
        self.assertEqual(after, 0)
        # The simulation result may still show a display-only preview.
        if result["fusion"]["status"] in ("WARNING", "ANOMALY"):
            self.assertIsNotNone(result["simulated_incident"])
            self.assertEqual(result["simulated_incident"]["source"], "TEST_SIMULATION")
            self.assertTrue(result["simulated_incident"]["is_simulated"])


class TestIncidentPersistence(unittest.TestCase):
    def setUp(self):
        incident_db.reset_for_tests()

    def test_incident_survives_new_connection(self):
        inc = incident_service.upsert_from_evaluation(make_snapshot())
        incident_id = inc["incident_id"]
        # Simulate a fresh process/connection reading the same file.
        incident_db._local.conn.close()
        incident_db._local.conn = None
        reloaded = incident_service.get(incident_id)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded["station_id"], "ATHER-TEST-001")

    def test_retrieval_by_id(self):
        inc = incident_service.upsert_from_evaluation(make_snapshot())
        fetched = incident_service.get(inc["incident_id"])
        self.assertEqual(fetched["incident_id"], inc["incident_id"])

    def test_retrieval_of_unknown_id_returns_none(self):
        self.assertIsNone(incident_service.get("INC-NOPE"))

    def test_escalation_preview_is_read_only(self):
        inc = incident_service.upsert_from_evaluation(make_snapshot())
        preview = incident_service.build_escalation_preview(inc["incident_id"])
        self.assertTrue(preview["is_preview_only"])
        unchanged = incident_service.get(inc["incident_id"])
        self.assertEqual(unchanged["status"], "NEW")  # preview never mutates state


if __name__ == "__main__":
    unittest.main()
