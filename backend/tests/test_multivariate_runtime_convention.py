"""
Stage 2 regression tests: runtime pressure-convention provenance and Test Lab
integration for the Multivariate layer.

The Multivariate models were trained on sea-level-equivalent pressure, so a
reading is only comparable when we KNOW its pressure is sea-level (or can be
converted with a supplied elevation). These tests pin that:

  * Open-Meteo records WHICH field supplied pressure (MSL vs the SURFACE fallback)
  * a convention is only ever DECLARED, never inferred from the source or the value
  * UNKNOWN blocks the models; MSL allows them; nothing is converted behind our back
  * Test Lab scenarios must declare their convention explicitly
"""
import io
import json
import os
import sys
import unittest
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.anomaly.detector import AnomalyDetector
from app.ingestion.adapter import IngestionAdapter, declared_pressure_convention
from app.simulation.scenarios import SCENARIOS, Scenario, ScenarioStep, list_scenarios
from app.simulation.service import run_scenario, run_simulation
from app.weather import open_meteo
from app.weather.open_meteo import OpenMeteoService, select_pressure, with_pressure_provenance
from engine import multivariate_features as mf
from engine.layer3_multivariate import MultivariateConsistencyLayer, resolve_pressure_convention
from schema import AWSReading, ObservationSource, station_dict_to_reading

LAYER = MultivariateConsistencyLayer()
DETECTOR = AnomalyDetector()

PUNE = (18.4923, 73.8619)


class _FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _open_meteo_payload(msl, surface):
    return {"current": {"time": "2026-09-27T08:00", "temperature_2m": 29.0, "relative_humidity_2m": 57,
                        "pressure_msl": msl, "surface_pressure": surface, "wind_speed_10m": 10.0,
                        "wind_direction_10m": 200, "weather_code": 1}}


def _service():
    svc = OpenMeteoService()
    svc.cache = {}
    svc._save_disk_cache = lambda: None            # never write the real disk cache from a test
    return svc


def _station_dict(convention=None, source=ObservationSource.AWS_IN_SITU, **kw):
    d = {"id": "RT-1", "name": "Runtime test", "latitude": PUNE[0], "longitude": PUNE[1],
         "temperature": 29.0, "pressure": 1010.6, "humidity": 57.0, "dataSource": source}
    if convention is not None:
        d["pressureConvention"] = convention
    d.update(kw)
    return d


def _mv(alert):
    return alert.canonical_result["layers"]["multivariate"]


# ═══════════════ 1, 2. Open-Meteo pressure provenance ═══════════════
class TestOpenMeteoProvenance(unittest.TestCase):
    def test_pressure_msl_is_recorded_as_msl(self):
        self.assertEqual(select_pressure({"pressure_msl": 1010.5, "surface_pressure": 950.2}), (1010.5, "MSL"))

    def test_surface_fallback_is_recorded_as_surface_never_msl(self):
        self.assertEqual(select_pressure({"pressure_msl": None, "surface_pressure": 950.2}), (950.2, "SURFACE"))
        self.assertEqual(select_pressure({"surface_pressure": 950.2}), (950.2, "SURFACE"))

    def test_no_pressure_has_no_convention(self):
        self.assertEqual(select_pressure({}), (None, None))

    def test_single_fetch_records_msl_and_keeps_the_value_unchanged(self):
        svc = _service()
        with mock.patch.object(open_meteo.urllib.request, "urlopen",
                               return_value=_FakeResponse(json.dumps(_open_meteo_payload(1010.5, 950.2)).encode())):
            out = svc.get_current_weather(18.4923, 73.8619)
        self.assertEqual(out["pressure"], 1010.5)                 # provenance, not correction
        self.assertEqual(out["pressureConvention"], "MSL")
        self.assertEqual(out["surfacePressure"], 950.2)

    def test_single_fetch_records_the_surface_fallback(self):
        svc = _service()
        with mock.patch.object(open_meteo.urllib.request, "urlopen",
                               return_value=_FakeResponse(json.dumps(_open_meteo_payload(None, 950.2)).encode())):
            out = svc.get_current_weather(18.4923, 73.8619)
        self.assertEqual(out["pressure"], 950.2)                  # the surface value, unchanged
        self.assertEqual(out["pressureConvention"], "SURFACE")

    def test_batch_fetch_records_the_convention_per_location(self):
        svc = _service()
        body = json.dumps([_open_meteo_payload(1010.5, 950.2), _open_meteo_payload(None, 949.0)]).encode()
        with mock.patch.object(open_meteo.urllib.request, "urlopen", return_value=_FakeResponse(body)):
            out = svc.get_batch_weather([(18.49, 73.86), (17.38, 78.48)], chunk_size=50)
        self.assertEqual([o["pressureConvention"] for o in out], ["MSL", "SURFACE"])
        self.assertEqual([o["pressure"] for o in out], [1010.5, 949.0])

    def test_legacy_cache_entry_is_completed_only_when_it_is_logically_certain(self):
        # pressure differs from the record's own surfacePressure => it can only be pressure_msl
        self.assertEqual(with_pressure_provenance({"pressure": 1010.5, "surfacePressure": 950.2})["pressureConvention"], "MSL")
        # equal => cannot tell which field supplied it => stays unknown (no magnitude guessing)
        self.assertIsNone(with_pressure_provenance({"pressure": 1008.0, "surfacePressure": 1008.0})["pressureConvention"])
        # an existing tag is never overwritten
        self.assertEqual(with_pressure_provenance({"pressure": 1, "surfacePressure": 1, "pressureConvention": "SURFACE"})["pressureConvention"], "SURFACE")

    def test_an_untagged_cached_entry_is_completed_when_served(self):
        svc = _service()
        svc.cache = {"18.492_73.862": {"cached_at": __import__("time").time(),
                                       "data": {"pressure": 1010.5, "surfacePressure": 950.2}}}
        out = svc.get_current_weather(18.4923, 73.8619)
        self.assertEqual(out["pressureConvention"], "MSL")


# ═══════════════ 3, 4. in-situ / ingest convention ═══════════════
class TestInSituAndIngestConvention(unittest.TestCase):
    def test_the_static_in_situ_snapshot_has_no_declared_convention(self):
        """data/stations.json is a scrape whose pressure token carries a unit but no
        convention (see normalize_stations.parse_pressure), so it is UNKNOWN."""
        r = station_dict_to_reading(_station_dict(convention=None))
        self.assertIsNone(r.pressure_convention)
        self.assertEqual(resolve_pressure_convention(r)[0], "UNKNOWN")

    def test_a_station_that_declares_msl_is_msl(self):
        r = station_dict_to_reading(_station_dict(convention="MSL"))
        self.assertEqual(resolve_pressure_convention(r), ("MSL", "declared_on_reading"))

    def test_ingest_payloads_only_carry_a_convention_when_the_sender_declares_it(self):
        native = {"id": "S1", "temperature": 20, "pressure": 1010, "humidity": 50}
        self.assertIsNone(IngestionAdapter.parse_payload(native)[1]["pressureConvention"])
        self.assertEqual(IngestionAdapter.parse_payload(dict(native, pressureConvention="msl"))[1]["pressureConvention"], "MSL")
        self.assertEqual(IngestionAdapter.parse_payload(dict(native, pressureConvention="SURFACE"))[1]["pressureConvention"], "SURFACE")

    def test_third_party_formats_are_not_assumed_to_be_any_convention(self):
        weewx = {"outTemp": 20.0, "barometer": 1010.0, "outHumidity": 50, "station_id": "W1"}
        wu = {"ID": "U1", "tempf": 68, "baromin": 29.85, "humidity": 50}
        self.assertIsNone(IngestionAdapter.parse_payload(weewx)[1]["pressureConvention"])
        self.assertIsNone(IngestionAdapter.parse_payload(wu)[1]["pressureConvention"])

    def test_invalid_or_unknown_declarations_are_ignored_not_trusted(self):
        for bad in ("banana", "", None, 5, "UNKNOWN"):
            self.assertIsNone(declared_pressure_convention({"pressureConvention": bad}))

    def test_a_new_packet_does_not_inherit_a_previous_stations_convention(self):
        from app.stations.service import station_service as svc
        sid = "UNITTEST-CONV"
        try:
            svc.ingest_observation(sid, {"temperature": 25.0, "pressure": 1005.0, "humidity": 50, "pressureConvention": "MSL"})
            self.assertEqual(svc.get_station(sid)["pressureConvention"], "MSL")
            svc.ingest_observation(sid, {"temperature": 25.5, "pressure": 1005.5, "humidity": 50})
            self.assertIsNone(svc.get_station(sid)["pressureConvention"])
        finally:
            svc._stations.pop(sid, None)
            svc._observation_history.pop(sid, None) if hasattr(svc, "_observation_history") else None


# ═══════════════ 5, 6, 11. UNKNOWN blocks, MSL allows, nothing is faked ═══════════════
class TestExecutionGate(unittest.TestCase):
    def _reading(self, conv, **kw):
        return station_dict_to_reading(_station_dict(convention=conv, **kw))

    def test_unknown_blocks_both_detectors(self):
        e = mock.patch.object(LAYER.artifacts.ecod, "decision_function", wraps=LAYER.artifacts.ecod.decision_function)
        i = mock.patch.object(LAYER.artifacts.iforest, "score_samples", wraps=LAYER.artifacts.iforest.score_samples)
        with e as es, i as isp:
            _s, _r, d = LAYER.evaluate(self._reading(None))
        self.assertEqual((es.call_count, isp.call_count), (0, 0))
        self.assertEqual(d["status"], "INSUFFICIENT_DATA")
        self.assertEqual(d["pressure_convention"], "UNKNOWN")
        self.assertFalse(d["detectors"]["ecod"]["executed"])
        self.assertFalse(d["detectors"]["isolation_forest"]["executed"])
        self.assertIn("Pressure convention unavailable", d["skip_reason"])

    def test_msl_allows_both_detectors(self):
        e = mock.patch.object(LAYER.artifacts.ecod, "decision_function", wraps=LAYER.artifacts.ecod.decision_function)
        i = mock.patch.object(LAYER.artifacts.iforest, "score_samples", wraps=LAYER.artifacts.iforest.score_samples)
        with e as es, i as isp:
            _s, _r, d = LAYER.evaluate(self._reading("MSL"))
        self.assertEqual((es.call_count, isp.call_count), (1, 1))
        self.assertEqual(d["status"], "EVALUATED")
        self.assertEqual(d["method_executed"], "ECOD+IsolationForest")
        self.assertTrue(d["detectors"]["ecod"]["executed"] and d["detectors"]["isolation_forest"]["executed"])

    def test_msl_pressure_is_used_as_is_with_no_conversion(self):
        _s, _r, d = LAYER.evaluate(self._reading("MSL"))
        self.assertNotIn("pressure_conversion", d)
        self.assertEqual(d["pressure_msl_equivalent_hpa"], 1010.6)

    def test_unknown_produces_no_features_and_no_converted_pressure(self):
        _s, _r, d = LAYER.evaluate(self._reading(None))
        self.assertNotIn("features", d)
        self.assertNotIn("pressure_msl_equivalent_hpa", d)
        self.assertNotIn("pressure_conversion", d)

    def test_surface_without_a_real_elevation_is_not_converted(self):
        _s, _r, d = LAYER.evaluate(self._reading("SURFACE", pressure=948.0))
        self.assertEqual(d["status"], "INSUFFICIENT_DATA")
        self.assertNotIn("pressure_conversion", d)
        self.assertFalse(d["detectors"]["ecod"]["executed"])

    def test_surface_with_a_supplied_elevation_is_converted_with_the_shared_formula(self):
        r = self._reading("SURFACE", pressure=948.0, elevation=560.0)
        _s, _r, d = LAYER.evaluate(r)
        self.assertEqual(d["status"], "EVALUATED")
        self.assertTrue(d["pressure_conversion"]["applied"])
        self.assertAlmostEqual(d["pressure_msl_equivalent_hpa"], mf.surface_to_msl_equivalent(948.0, 29.0, 560.0), places=1)

    def test_a_city_elevation_proxy_is_never_used_as_a_station_elevation(self):
        """SURFACE + no supplied elevation must not fall back to the matched city's proxy."""
        _s, _r, d = LAYER.evaluate(self._reading("SURFACE", pressure=948.0))
        self.assertNotIn("climatological_elevation_proxy", d)
        self.assertNotIn("features", d)


# ═══════════════ 7, 8. Test Lab ═══════════════
class TestTestLabConvention(unittest.TestCase):
    def test_every_registered_scenario_explicitly_declares_a_convention(self):
        for s in SCENARIOS.values():
            self.assertIn(s.pressure_convention, ("MSL", "SURFACE"), s.id)
        self.assertTrue(all("pressure_convention" in x for x in list_scenarios()))

    def test_a_scenario_without_a_declared_convention_cannot_be_built(self):
        with self.assertRaises(TypeError):
            Scenario(id="X", name="x", description="x", steps=[ScenarioStep(20.0, 1010.0, 50.0)])

    def test_undeclared_or_invalid_conventions_are_rejected(self):
        for bad in ("UNKNOWN", "", "msl"):
            with self.assertRaises(ValueError):
                Scenario(id="X", name="x", description="x", steps=[ScenarioStep(20.0, 1010.0, 50.0)], pressure_convention=bad)

    def test_a_surface_scenario_must_declare_its_own_elevation(self):
        with self.assertRaises(ValueError):
            Scenario(id="X", name="x", description="x", steps=[ScenarioStep(20.0, 948.0, 50.0)], pressure_convention="SURFACE")

    def test_msl_scenario_reaches_the_multivariate_layer_and_runs_both_detectors(self):
        r = run_simulation("MULTIVARIATE_INCONSISTENCY")
        d = r["diagnostics"]["multivariate"]["details"]
        self.assertEqual(r["scenario"]["pressure_convention"], "MSL")
        self.assertEqual(d["pressure_convention"], "MSL")
        self.assertEqual(d["method_executed"], "ECOD+IsolationForest")
        self.assertTrue(d["detectors"]["ecod"]["executed"] and d["detectors"]["isolation_forest"]["executed"])
        self.assertEqual(d["n_valid"], 3)

    def test_msl_scenarios_keep_their_expected_outcomes(self):
        for sid in ("MULTIVARIATE_INCONSISTENCY", "TEMPERATURE_SPIKE", "COMBINED_SENSOR_FAILURE"):
            r = run_simulation(sid)
            self.assertTrue(r["test_result"]["passed"], f"{sid}: {r['test_result']}")

    def test_surface_scenario_is_converted_with_its_declared_elevation(self):
        sc = Scenario(
            id="TEST_SURFACE", name="surface-pressure scenario", description="controlled SURFACE-pressure scenario",
            steps=[ScenarioStep(29.0, 948.0, 57.0)], pressure_convention="SURFACE", elevation_m=560.0,
            expected_bucket="NORMAL")
        r = run_scenario(sc)
        d = r["diagnostics"]["multivariate"]["details"]
        self.assertEqual(d["pressure_convention"], "SURFACE")
        self.assertTrue(d["pressure_conversion"]["applied"])
        self.assertEqual(d["pressure_conversion"]["elevation_m"], 560.0)
        self.assertAlmostEqual(d["pressure_msl_equivalent_hpa"], mf.surface_to_msl_equivalent(948.0, 29.0, 560.0), places=1)
        self.assertTrue(d["detectors"]["ecod"]["executed"])
        # the converted pressure is on the sea-level scale the models were trained on
        self.assertGreater(d["pressure_msl_equivalent_hpa"], 1000.0)

    def test_scenario_fault_magnitudes_are_unchanged(self):
        """Declaring a convention must not alter the injected values."""
        s = SCENARIOS["PRESSURE_SPIKE"]
        self.assertIn(1075.0, [st.pressure_hpa for st in s.steps])


# ═══════════════ on-demand Open-Meteo enrichment keeps its pressure provenance ═══════════════
class TestOnDemandNwpEnrichment(unittest.TestCase):
    """StationService.get_station fetches Open-Meteo for a station that has no
    observations. The pressure it copies must carry the convention Open-Meteo
    recorded, otherwise a known-MSL value would reach Multivariate as UNKNOWN."""

    def _run(self, convention, pressure):
        from app.stations.service import station_service as svc
        from app.weather.open_meteo import open_meteo_service
        from app.anomaly.detector import detector
        sid = f"UNITTEST-ENRICH-{convention}"
        w = {"temperature": 29.0, "humidity": 57, "pressure": pressure, "pressureConvention": convention,
             "surfacePressure": 950.0, "windSpeed": 10.0, "windDirection": "W", "condition": "Clear",
             "timestamp": "2026-09-27T08:00"}
        try:
            svc._stations[sid] = {"id": sid, "name": "enrich", "latitude": PUNE[0], "longitude": PUNE[1],
                                  "temperature": None, "pressure": None, "humidity": None, "status": "OFFLINE",
                                  "dataSource": ObservationSource.MISSING}
            with mock.patch.object(open_meteo_service, "get_current_weather", return_value=w):
                stn = svc.get_station(sid)
            alert = detector.get_station_alert(sid)
            return stn, alert
        finally:
            svc._stations.pop(sid, None)
            detector._spatial_pool.pop(sid, None)
            detector._alerts_cache.pop(sid, None)

    def test_msl_provenance_survives_the_on_demand_fetch_and_the_models_run(self):
        stn, alert = self._run("MSL", 1010.5)
        self.assertEqual(stn["pressureConvention"], "MSL")
        self.assertEqual(stn["dataSource"], ObservationSource.NWP_MODEL_REFERENCE)
        d = alert.canonical_result["layers"]["multivariate"]["details"]
        self.assertEqual(d["pressure_convention"], "MSL")
        self.assertEqual(d["method_executed"], "ECOD+IsolationForest")
        self.assertTrue(d["detectors"]["ecod"]["executed"] and d["detectors"]["isolation_forest"]["executed"])

    def test_a_surface_fallback_is_recorded_and_not_run_without_an_elevation(self):
        stn, alert = self._run("SURFACE", 950.0)
        self.assertEqual(stn["pressureConvention"], "SURFACE")
        d = alert.canonical_result["layers"]["multivariate"]["details"]
        self.assertEqual(d["pressure_convention"], "SURFACE")
        self.assertFalse(d["detectors"]["ecod"]["executed"])
        self.assertNotIn("pressure_conversion", d)          # nothing converted without a real elevation

    def test_an_unrecorded_convention_stays_unknown_and_blocks_the_models(self):
        stn, alert = self._run(None, 1010.5)
        self.assertIsNone(stn["pressureConvention"])
        d = alert.canonical_result["layers"]["multivariate"]["details"]
        self.assertEqual(d["pressure_convention"], "UNKNOWN")
        self.assertFalse(d["detectors"]["ecod"]["executed"])


# ═══════════════ 9, 10, 12. canonical API ═══════════════
class TestCanonicalContract(unittest.TestCase):
    def test_pressure_convention_reaches_the_canonical_response(self):
        for conv, want in (("MSL", "MSL"), (None, "UNKNOWN")):
            a = DETECTOR.evaluate_reading(station_dict_to_reading(_station_dict(convention=conv, id=f"CC-{want}")))
            c = a.canonical_result
            self.assertEqual(c["observation"]["pressure_convention"], want)
            self.assertEqual(c["layers"]["multivariate"]["details"]["pressure_convention"], want)

    def test_the_api_reports_actual_detector_execution(self):
        ran = _mv(DETECTOR.evaluate_reading(station_dict_to_reading(_station_dict(convention="MSL", id="EX-1"))))["details"]
        skipped = _mv(DETECTOR.evaluate_reading(station_dict_to_reading(_station_dict(convention=None, id="EX-2"))))["details"]
        self.assertEqual((ran["detectors"]["ecod"]["executed"], ran["detectors"]["isolation_forest"]["executed"]), (True, True))
        self.assertEqual((skipped["detectors"]["ecod"]["executed"], skipped["detectors"]["isolation_forest"]["executed"]), (False, False))
        self.assertIsNone(skipped["method_executed"])
        self.assertIn("skip_reason", skipped["detectors"]["ecod"])

    def test_required_multivariate_fields_are_present_in_every_case(self):
        cases = {
            "A msl 3ch": station_dict_to_reading(_station_dict(convention="MSL", id="F-A")),
            "B unknown 3ch": station_dict_to_reading(_station_dict(convention=None, id="F-B")),
            "C 2ch": station_dict_to_reading(_station_dict(convention="MSL", id="F-C", pressure=None)),
        }
        need = ("method_executed", "pressure_convention", "pressure_normalization_method", "baseline_scope",
                "valid_channels", "n_valid", "valid_channel_count", "detectors")
        for label, r in cases.items():
            d = _mv(DETECTOR.evaluate_reading(r))["details"]
            for key in need:
                self.assertIn(key, d, f"{label}: {key}")
            for det in ("ecod", "isolation_forest"):
                self.assertIn("executed", d["detectors"][det], f"{label}: {det}")

    def test_case_b_unknown_convention_is_reported_as_unavailable_with_the_reason(self):
        c = _mv(DETECTOR.evaluate_reading(station_dict_to_reading(_station_dict(convention=None, id="CB"))))
        self.assertEqual(c["status"], "INSUFFICIENT_DATA")
        self.assertEqual(c["score"], 0.0)
        self.assertIn("Pressure convention unavailable", c["reason"])
        self.assertNotIn("requires ≥2 valid channels", c["reason"])

    def test_case_c_two_channels_keeps_the_insufficient_data_behaviour(self):
        c = _mv(DETECTOR.evaluate_reading(station_dict_to_reading(_station_dict(convention="MSL", id="CC2", pressure=None))))
        self.assertEqual(c["status"], "INSUFFICIENT_DATA")
        self.assertEqual(c["details"]["n_valid"], 2)
        self.assertFalse(c["details"]["detectors"]["ecod"]["executed"])

    def test_valid_channel_counts_are_never_reported_as_zero(self):
        for conv in ("MSL", None):
            c = _mv(DETECTOR.evaluate_reading(station_dict_to_reading(_station_dict(convention=conv, id=f"VC-{conv}"))))
            self.assertEqual(c["details"]["n_valid"], 3)
            self.assertNotIn("(0 available)", c["reason"])

    def test_service_level_anomaly_response_carries_the_convention(self):
        from app.stations.service import station_service as svc
        sid = "UNITTEST-CANON"
        try:
            svc._stations[sid] = _station_dict(convention="MSL", id=sid, source=ObservationSource.NWP_MODEL_REFERENCE,
                                               dataSource=ObservationSource.NWP_MODEL_REFERENCE, status="NORMAL")
            res = svc.get_station_anomaly(sid)
            self.assertEqual(res["observation"]["pressure_convention"], "MSL")
            d = res["layers"]["multivariate"]["details"]
            self.assertEqual(d["method_executed"], "ECOD+IsolationForest")
            self.assertTrue(d["detectors"]["ecod"]["executed"])
        finally:
            svc._stations.pop(sid, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
