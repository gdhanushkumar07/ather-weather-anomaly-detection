"""
Data Provenance & Freshness Test Suite (Phase 1-4, 20, 27)
============================================================
Verifies that ATHER never presents NWP model reference data as measured
AWS in-situ telemetry, that freshness is derived from real observation
timestamps (never request time), and that hardware-fault root causes are
never asserted against a non-physical-sensor source.
"""

import unittest
import sys
import os
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from schema import (
    AWSReading, FaultType, ObservationSource, Freshness,
    classify_freshness, station_dict_to_reading,
)
from app.anomaly.detector import AnomalyDetector
from app.stations.service import station_service


class TestFreshnessClassification(unittest.TestCase):
    """Direct unit tests for classify_freshness() — Phase 4."""

    def test_live_when_recent(self):
        now = datetime.now(timezone.utc)
        obs = now - timedelta(minutes=10)
        self.assertEqual(
            classify_freshness(obs, now, cadence_minutes=90.0, has_value=True),
            Freshness.LIVE,
        )

    def test_stale_when_older_than_cadence(self):
        now = datetime.now(timezone.utc)
        obs = now - timedelta(hours=6)
        self.assertEqual(
            classify_freshness(obs, now, cadence_minutes=90.0, has_value=True),
            Freshness.STALE,
        )

    def test_missing_when_no_value(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(
            classify_freshness(now, now, cadence_minutes=90.0, has_value=False),
            Freshness.MISSING,
        )

    def test_unknown_when_no_observation_timestamp(self):
        # A value exists but its true observation time cannot be verified —
        # must NOT be silently treated as LIVE.
        now = datetime.now(timezone.utc)
        self.assertEqual(
            classify_freshness(None, now, cadence_minutes=90.0, has_value=True),
            Freshness.UNKNOWN,
        )

    def test_never_uses_request_time_as_observation_time(self):
        # A stale observation timestamp must classify as STALE even though
        # "now" (the request/received time) is always fresh — freshness must
        # be computed from the OBSERVATION time, never from request time.
        received = datetime.now(timezone.utc)
        stale_obs = received - timedelta(hours=10)
        result = classify_freshness(stale_obs, received, cadence_minutes=90.0, has_value=True)
        self.assertEqual(result, Freshness.STALE)


class TestStationDictProvenance(unittest.TestCase):
    """station_dict_to_reading() must propagate explicit provenance, never
    default an untagged station to AWS_IN_SITU (Phase 1-3, 27)."""

    def test_untagged_station_defaults_to_unknown_source(self):
        reading = station_dict_to_reading({"id": "X1", "temperature": 25.0})
        self.assertEqual(reading.source, ObservationSource.UNKNOWN)

    def test_explicit_nwp_source_is_preserved(self):
        reading = station_dict_to_reading({
            "id": "X2",
            "temperature": 30.0,
            "dataSource": ObservationSource.NWP_MODEL_REFERENCE,
            "observationTimestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.assertEqual(reading.source, ObservationSource.NWP_MODEL_REFERENCE)
        self.assertEqual(reading.freshness, Freshness.LIVE)

    def test_explicit_aws_source_is_preserved(self):
        reading = station_dict_to_reading({
            "id": "X3",
            "temperature": 22.0,
            "dataSource": ObservationSource.AWS_IN_SITU,
            "observationTimestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.assertEqual(reading.source, ObservationSource.AWS_IN_SITU)

    def test_stale_nwp_timestamp_is_flagged_stale_not_live(self):
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        reading = station_dict_to_reading({
            "id": "X4",
            "temperature": 30.0,
            "dataSource": ObservationSource.NWP_MODEL_REFERENCE,
            "observationTimestamp": old_ts,
            "sourceCadenceMinutes": 90.0,
        })
        self.assertEqual(reading.freshness, Freshness.STALE)

    def test_missing_observation_timestamp_is_unknown_not_live(self):
        # A real observed value with NO verifiable observation time must
        # never be presented as LIVE (Phase 4).
        reading = station_dict_to_reading({
            "id": "X5",
            "temperature": 28.0,
            "dataSource": ObservationSource.AWS_IN_SITU,
        })
        self.assertEqual(reading.freshness, Freshness.UNKNOWN)


class TestWeatherUnionStationsAreLabeledNWP(unittest.TestCase):
    """The ~296 WeatherUnionInfra.csv-registered Indian AWS stations have NO
    real telemetry API integrated — every numeric value comes from Open-Meteo.
    They must be labeled NWP_MODEL_REFERENCE, never AWS_IN_SITU (Phase 3, 27)."""

    def test_csv_station_is_tagged_nwp_not_aws(self):
        zwl = station_service.get_station("ZWL003467")
        self.assertIsNotNone(zwl)
        self.assertEqual(zwl.get("dataSource"), ObservationSource.NWP_MODEL_REFERENCE)
        self.assertEqual(zwl.get("awsTelemetryStatus"), "TELEMETRY_UNAVAILABLE")

    def test_csv_station_canonical_observation_reports_nwp_source(self):
        result = station_service.get_station_anomaly("ZWL003467")
        self.assertIsNotNone(result)
        self.assertEqual(
            result["observation"]["source"], ObservationSource.NWP_MODEL_REFERENCE
        )
        self.assertNotEqual(result["observation"]["source"], "AWS Station Data")
        self.assertEqual(result["aws_telemetry_status"], "TELEMETRY_UNAVAILABLE")

    def test_flagship_mesonet_station_is_tagged_aws_in_situ(self):
        # data/stations.json entries came from a real crowdsourced mesonet
        # scrape (not a model) — but are a frozen snapshot with unverifiable
        # per-station age, so freshness must be UNKNOWN, never LIVE.
        stn = station_service.get_station("ATHER-001")
        self.assertIsNotNone(stn)
        self.assertEqual(stn.get("dataSource"), ObservationSource.AWS_IN_SITU)
        result = station_service.get_station_anomaly("ATHER-001")
        self.assertEqual(result["observation"]["freshness"], Freshness.UNKNOWN)


class TestRootCauseSourceAwareness(unittest.TestCase):
    """Root cause must never assert a physical sensor hardware fault
    (FROZEN_SENSOR, SENSOR_SPIKE, CALIBRATION_DRIFT, SINGLE_CHANNEL_FAULT)
    against a NWP model reference reading — there is no hardware to blame
    (Phase 14, 27)."""

    def setUp(self):
        self.detector = AnomalyDetector()

    def test_frozen_pattern_on_nwp_source_is_not_labeled_frozen_sensor(self):
        stn_id = "STN_NWP_FROZEN"
        now = datetime.now(timezone.utc)
        alert = None
        for i in range(14, 0, -1):
            r = AWSReading(
                station_id=stn_id,
                timestamp=now - timedelta(minutes=i * 10),
                temperature_c=21.435,
                pressure_hpa=1012.0 + (i * 0.1),
                humidity_pct=50.0 + (i * 0.2),
                source=ObservationSource.NWP_MODEL_REFERENCE,
            )
            alert = self.detector.evaluate_reading(r)

        self.assertTrue(alert.is_anomaly)
        self.assertNotEqual(alert.root_cause, FaultType.FROZEN_SENSOR)
        self.assertEqual(alert.root_cause, FaultType.MODEL_REFERENCE_INCONSISTENCY)

    def test_same_pattern_on_aws_source_still_reports_frozen_sensor(self):
        # Sanity check: the guard must not suppress legitimate hardware
        # diagnoses for genuine AWS_IN_SITU telemetry.
        stn_id = "STN_AWS_FROZEN"
        now = datetime.now(timezone.utc)
        alert = None
        for i in range(14, 0, -1):
            r = AWSReading(
                station_id=stn_id,
                timestamp=now - timedelta(minutes=i * 10),
                temperature_c=21.435,
                pressure_hpa=1012.0 + (i * 0.1),
                humidity_pct=50.0 + (i * 0.2),
                source=ObservationSource.AWS_IN_SITU,
            )
            alert = self.detector.evaluate_reading(r)

        self.assertTrue(alert.is_anomaly)
        self.assertEqual(alert.root_cause, FaultType.FROZEN_SENSOR)

    def test_nwp_source_never_reports_days_to_failure(self):
        stn_id = "STN_NWP_DTF"
        now = datetime.now(timezone.utc)
        r = AWSReading(
            station_id=stn_id,
            timestamp=now,
            temperature_c=25.0,
            pressure_hpa=1012.0,
            humidity_pct=55.0,
            source=ObservationSource.NWP_MODEL_REFERENCE,
        )
        alert = self.detector.evaluate_reading(r)
        self.assertIsNone(alert.estimated_days_to_failure)


if __name__ == "__main__":
    unittest.main()
