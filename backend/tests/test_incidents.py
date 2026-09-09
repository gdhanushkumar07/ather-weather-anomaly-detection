"""
ATHER Incident Workflow Test Suite (Phase 13-15)
==================================================
"""
import unittest
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.incidents.service import IncidentStore
from app.stations.service import station_service


class TestIncidentWorkflow(unittest.TestCase):
    def setUp(self):
        self.store = IncidentStore()
        # ATHER-COW-0137 is a real, deterministic ANOMALY station in the
        # existing test fixtures (see test_backend.py::test_station_loading).
        self.anomaly_station_id = "ATHER-COW-0137"
        self.normal_station_id = "ATHER-IND-002"

    def test_new_incident_created_for_actionable_anomaly(self):
        incident = self.store.get_or_create(self.anomaly_station_id)
        self.assertIsNotNone(incident)
        self.assertEqual(incident["state"], "NEW")
        self.assertEqual(incident["station_id"], self.anomaly_station_id)
        self.assertIn("initial_snapshot", incident)

    def test_no_incident_forced_for_normal_station(self):
        stn = station_service.get_station(self.normal_station_id)
        if stn and stn.get("status") == "NORMAL":
            incident = self.store.get_or_create(self.normal_station_id)
            self.assertIsNone(incident)

    def test_state_machine_transitions(self):
        self.store.get_or_create(self.anomaly_station_id)
        inc = self.store.acknowledge(self.anomaly_station_id)
        self.assertEqual(inc["state"], "ACKNOWLEDGED")
        inc = self.store.investigate(self.anomaly_station_id)
        self.assertEqual(inc["state"], "INVESTIGATING")
        inc = self.store.resolve(self.anomaly_station_id)
        self.assertEqual(inc["state"], "RESOLVED")
        # 1 creation + 3 transitions = 4 history entries
        self.assertEqual(len(inc["history"]), 4)

    def test_resolving_a_still_active_condition_opens_a_fresh_incident(self):
        # Real incident-management semantics: RESOLVED means the operator
        # closed THAT incident. If the underlying anomaly condition is still
        # firing on the next evaluation, that is honestly a new incident
        # (the engine never silently reopens or silently auto-resolves).
        first = self.store.get_or_create(self.anomaly_station_id)
        self.store.resolve(self.anomaly_station_id)
        second = self.store.get_or_create(self.anomaly_station_id)
        self.assertEqual(second["state"], "NEW")
        self.assertNotEqual(first["incident_id"], second["incident_id"])


    def test_dismiss_transition(self):
        self.store.get_or_create(self.anomaly_station_id)
        inc = self.store.dismiss(self.anomaly_station_id)
        self.assertEqual(inc["state"], "DISMISSED")

    def test_escalation_preview_is_structured_and_marked_preview_only(self):
        self.store.get_or_create(self.anomaly_station_id)
        preview = self.store.build_escalation_preview(self.anomaly_station_id)
        self.assertIsNotNone(preview)
        self.assertTrue(preview["is_preview_only"])
        self.assertIn("recipient", preview)
        self.assertIn("severity", preview)
        self.assertIn("root_cause", preview)
        self.assertIn("recommended_action", preview)

    def test_mark_escalated_does_not_flip_workflow_state(self):
        self.store.get_or_create(self.anomaly_station_id)
        self.store.acknowledge(self.anomaly_station_id)
        inc = self.store.mark_escalated(self.anomaly_station_id)
        self.assertTrue(inc["escalated"])
        self.assertIsNotNone(inc["escalated_at"])
        # Escalating is an audit-trail action, not a state transition.
        self.assertEqual(inc["state"], "ACKNOWLEDGED")

    def test_unknown_station_returns_none(self):
        self.assertIsNone(self.store.get_or_create("NOT-A-REAL-STATION-ID"))
        self.assertIsNone(self.store.acknowledge("NOT-A-REAL-STATION-ID"))


if __name__ == "__main__":
    unittest.main()
