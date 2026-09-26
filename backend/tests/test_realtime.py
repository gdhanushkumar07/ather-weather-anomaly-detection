"""
Tests for the real-time pipeline: normalization, ingestion, de-duplication,
late/stale data, source failure, event publication, station state, incident
creation and lifecycle, simulation, replay, the engine fixes found by running
continuously (L2 persistence span, L2 MAD floor, L5 reference residual, L4
neighbour keys), and an end-to-end integration test over real HTTP + SSE.
"""
import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.anomaly.detector import AnomalyDetector  # noqa: E402
from app.incidents import db as incident_db  # noqa: E402
from app.incidents import service as incident_service  # noqa: E402
from app.pipeline import events as ev  # noqa: E402
from app.pipeline.events import EventBroker  # noqa: E402
from app.pipeline.models import ObservationIn, RejectedObservation  # noqa: E402
from app.pipeline.normalize import convert, normalize  # noqa: E402
from app.pipeline.processor import ObservationProcessor  # noqa: E402
from app.pipeline.store import TimeSeriesStore  # noqa: E402
from app.sources.base import DEGRADED, DOWN, SourceAdapter  # noqa: E402
from app.sources.noaa_isd import parse_isd_record  # noqa: E402
from app.sources.simulation import FaultBook, SimStation, SyntheticNetwork  # noqa: E402
from app.stations.service import station_service  # noqa: E402
from schema import AWSReading, FaultType  # noqa: E402

UTC = timezone.utc


def _temp_env(testcase):
    """Point incidents + time-series at fresh temp files for one test class."""
    tmp = tempfile.mkdtemp()
    testcase._old_env = {k: os.environ.get(k) for k in ("ATHER_INCIDENTS_DB_PATH", "ATHER_TIMESERIES_DB_PATH")}
    os.environ["ATHER_INCIDENTS_DB_PATH"] = os.path.join(tmp, "incidents.db")
    os.environ["ATHER_TIMESERIES_DB_PATH"] = os.path.join(tmp, "ts.db")
    incident_db.reset_for_tests()
    return tmp


def _restore_env(testcase):
    for k, v in testcase._old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _cluster(n=8, lat=12.95, lon=77.58, prefix="TST"):
    """Registers n test stations ~2 km apart in the catalogue."""
    ids = []
    for i in range(n):
        sid = f"{prefix}-{i:02d}"
        station_service._stations[sid] = {
            "id": sid, "name": f"Test AWS {i}", "latitude": lat + 0.018 * (i % 3), "longitude": lon + 0.018 * (i // 3),
            "elevation": 5.0, "country": "India", "region": "Test", "town": "Test", "status": "NORMAL",
        }
        ids.append(sid)
    return ids


def _obs(sid, t, temp=24.0, rh=65.0, p=1010.0, source="AWS_IN_SITU", **kw):
    return ObservationIn(station_id=sid, observed_at=t, source=source, adapter="test",
                         temperature=temp, humidity=rh, pressure=p, **kw)


def _processor(tmp):
    return ObservationProcessor(detector=AnomalyDetector(), station_service=station_service,
                                store=TimeSeriesStore(path=os.path.join(tmp, "proc.db")),
                                incident_service=incident_service)


# ─────────────────────────────────────────────────────────────────────────
class TestNormalization(unittest.TestCase):
    def test_unit_conversions(self):
        self.assertAlmostEqual(convert("temperature", 77.0, "degF"), 25.0)
        self.assertAlmostEqual(convert("temperature", 300.15, "K"), 27.0)
        self.assertAlmostEqual(convert("pressure", 101325.0, "Pa"), 1013.25)
        self.assertAlmostEqual(convert("wind_speed", 10.0, "m/s"), 36.0)
        self.assertAlmostEqual(convert("humidity", 0.55, "fraction"), 55.0)

    def test_unsupported_unit_rejected(self):
        with self.assertRaises(RejectedObservation) as cm:
            convert("pressure", 1.0, "psi")
        self.assertEqual(cm.exception.code, "UNSUPPORTED_UNIT")

    def test_future_timestamp_rejected(self):
        now = datetime.now(UTC)
        with self.assertRaises(RejectedObservation) as cm:
            normalize(_obs("X", now + timedelta(hours=1)), received_at=now)
        self.assertEqual(cm.exception.code, "FUTURE_TIMESTAMP")

    def test_naive_timestamp_assumed_utc_and_late_flagged(self):
        now = datetime.now(UTC)
        n = normalize(_obs("X", (now - timedelta(hours=8)).replace(tzinfo=None)), received_at=now)
        self.assertIn("TIMESTAMP_ASSUMED_UTC", n.flags)
        self.assertIn("LATE_ARRIVAL", n.flags)

    def test_nan_is_missing_and_corrupt_magnitude_rejected(self):
        o = ObservationIn(station_id="X", observed_at=datetime.now(UTC), source="AWS_IN_SITU", temperature="nan")
        self.assertIsNone(o.temperature)
        with self.assertRaises(Exception):
            ObservationIn(station_id="X", observed_at=datetime.now(UTC), source="AWS_IN_SITU", pressure=1e9)

    def test_physically_impossible_value_is_NOT_rejected_by_schema(self):
        # RH 130 % must reach Layer 1 so ATHER can flag the sensor.
        n = normalize(_obs("X", datetime.now(UTC), rh=130.0))
        self.assertEqual(n.values["humidity"], 130.0)

    def test_observation_id_is_deterministic(self):
        t = datetime(2026, 1, 1, tzinfo=UTC)
        self.assertEqual(normalize(_obs("X", t)).observation_id, normalize(_obs("X", t)).observation_id)
        self.assertNotEqual(normalize(_obs("X", t)).observation_id,
                            normalize(_obs("X", t, source="SIMULATED_AWS")).observation_id)


# ─────────────────────────────────────────────────────────────────────────
class TestProcessor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = _temp_env(cls)
        cls.ids = _cluster(8)

    @classmethod
    def tearDownClass(cls):
        for sid in cls.ids:
            station_service._stations.pop(sid, None)
        _restore_env(cls)

    def setUp(self):
        incident_db.reset_for_tests()
        self.proc = _processor(tempfile.mkdtemp())
        self.t0 = datetime.now(UTC) - timedelta(minutes=60)

    def _tick(self, k, overrides=None):
        t = self.t0 + timedelta(minutes=k)
        batch = []
        for i, sid in enumerate(self.ids):
            kw = {"temp": 24.0 + 0.05 * (i % 3) + 0.01 * k, "rh": 65.0 - 0.02 * k, "p": 1010.0 + 0.01 * i}
            kw.update((overrides or {}).get(sid, {}))
            batch.append(normalize(_obs(sid, t, **kw), received_at=t + timedelta(seconds=1), cadence_s=60))
        return {o["observation_id"]: o for o in self.proc.process_batch(batch)}, batch

    def test_healthy_network_is_nominal_and_persisted(self):
        for k in range(5):
            outs, batch = self._tick(k)
        statuses = {o["detection"]["overall_status"] for o in outs.values()}
        self.assertEqual(statuses, {"nominal"})
        rows = self.proc.store.history(self.ids[0], 0)
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(self.proc.health), 8)

    def test_duplicate_observation_is_idempotent(self):
        _, batch = self._tick(0)
        again = self.proc.process_batch([batch[0]])
        self.assertEqual(again[0]["status"], "duplicate")
        self.assertEqual(len(self.proc.store.history(self.ids[0], 0)), 1)

    def test_out_of_order_observation_is_archived_late_not_evaluated(self):
        self._tick(0)
        self._tick(2)
        late = normalize(_obs(self.ids[0], self.t0 + timedelta(minutes=1)), cadence_s=60)
        out = self.proc.process_batch([late])[0]
        self.assertEqual(out["status"], "late")
        self.assertNotIn("detection", out)

    def test_isolated_spike_creates_anomaly_incident_with_evidence(self):
        for k in range(4):
            self._tick(k)
        outs, _ = self._tick(4, {self.ids[0]: {"temp": 36.0}})
        o = next(v for v in outs.values() if v["detection"]["station_id"] == self.ids[0])
        det = o["detection"]
        self.assertEqual(det["overall_status"], "anomaly")
        self.assertEqual(det["interpretation"], "likely_sensor_fault")
        self.assertIn("L4", det["triggered_layers"])
        self.assertIsNotNone(o["incident"])
        types = [t for t, _ in o["events"]]
        self.assertIn(ev.ANOMALY_DETECTED, types)
        self.assertIn(ev.INCIDENT_CREATED, types)
        inc = incident_service.get(o["incident"]["incident_id"])
        self.assertEqual(inc["context"]["detection_id"], det["detection_id"])
        self.assertTrue(inc["context"]["neighbors"])
        stages = [s["stage"] for s in inc["lifecycle"]]
        self.assertEqual(stages[:2], ["OBSERVATION", "DETECTION"])
        self.assertIn("RECOMMENDATION", stages)
        # Provenance is complete and persisted.
        stored = self.proc.store.detection(det["detection_id"])
        for key in ("data_source", "detector_version", "observation_timestamp", "processing_timestamp", "triggered_rules"):
            self.assertIn(key, stored["provenance"])

    def test_evolving_diagnosis_keeps_one_incident(self):
        for k in range(4):
            self._tick(k)
        for k in range(4, 8):   # a sustained step: SENSOR_SPIKE first, then re-diagnosed
            self._tick(k, {self.ids[0]: {"temp": 36.0 + 0.05 * k}})
        incs = incident_service.list_all(source="ALL", station_id=self.ids[0])
        self.assertEqual(len(incs), 1, [i["root_cause"] for i in incs])
        self.assertGreaterEqual(incs[0]["observation_count"], 2)

    def test_regional_change_is_weather_not_incident(self):
        for k in range(4):
            self._tick(k)
        shifted = {sid: {"temp": 24.0 - 7.0, "rh": 80.0} for sid in self.ids}
        outs, _ = self._tick(4, shifted)
        interps = {o["detection"]["interpretation"] for o in outs.values()}
        self.assertIn("likely_weather_event", interps)
        self.assertTrue(all(o.get("incident") is None for o in outs.values()))
        self.assertEqual(incident_service.list_all(source="ALL"), [])

    def test_impossible_humidity_is_physics_veto(self):
        for k in range(3):
            self._tick(k)
        outs, _ = self._tick(3, {self.ids[1]: {"rh": 130.0}})
        det = next(v for v in outs.values() if v["detection"]["station_id"] == self.ids[1])["detection"]
        self.assertEqual(det["overall_status"], "anomaly")
        self.assertIn("L1", det["triggered_layers"])
        self.assertEqual(det["diagnosis"]["rca_category"], "physically_impossible_reading")

    def test_missing_channel_is_degraded(self):
        for k in range(3):
            self._tick(k)
        outs, _ = self._tick(3, {self.ids[2]: {"rh": None}})
        det = next(v for v in outs.values() if v["detection"]["station_id"] == self.ids[2])["detection"]
        self.assertEqual(det["overall_status"], "degraded")

    def test_detector_failure_is_isolated(self):
        self._tick(0)
        real = self.proc.detector.evaluate_reading
        calls = {"n": 0}

        def flaky(reading, **kw):
            calls["n"] += 1
            if reading.station_id == self.ids[0]:
                raise RuntimeError("boom")
            return real(reading, **kw)

        self.proc.detector.evaluate_reading = flaky
        outs, _ = self._tick(1)
        statuses = sorted(o["status"] for o in outs.values())
        self.assertEqual(statuses.count("error"), 1)
        self.assertEqual(statuses.count("processed"), 7)
        self.assertEqual(len(self.proc.store.history(self.ids[0], 0)), 2)  # raw obs still archived


# ─────────────────────────────────────────────────────────────────────────
class TestEventBroker(unittest.TestCase):
    def test_sequence_replay_and_resync(self):
        async def run():
            b = EventBroker(history_size=5, subscriber_queue_size=3)
            b.attach_loop(asyncio.get_running_loop())
            for i in range(3):
                b.publish(ev.STATION_UPDATED, {"i": i})
            sub = b.subscribe(since_id=1)
            got = [sub.queue.get_nowait().data["i"] for _ in range(2)]
            self.assertEqual(got, [1, 2])
            for i in range(10):                      # overflow a slow client
                b.publish(ev.STATION_UPDATED, {"i": i})
            types = []
            while not sub.queue.empty():
                types.append(sub.queue.get_nowait().type)
            self.assertIn(ev.RESYNC_REQUIRED, types)
            stale = b.subscribe(since_id=0)          # older than the ring buffer
            self.assertEqual(stale.queue.get_nowait().type, ev.RESYNC_REQUIRED)
        asyncio.run(run())

    def test_threadsafe_publish(self):
        async def run():
            b = EventBroker()
            b.attach_loop(asyncio.get_running_loop())
            sub = b.subscribe()
            threading.Thread(target=lambda: b.publish(ev.ANOMALY_DETECTED, {"x": 1})).start()
            e = await asyncio.wait_for(sub.queue.get(), 2)
            self.assertEqual(e.type, ev.ANOMALY_DETECTED)
        asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────
class _FailingAdapter(SourceAdapter):
    name = "failing"
    cadence_s = 0.01
    max_backoff_s = 0.02

    async def poll(self):
        raise ConnectionError("upstream down")


class TestSourceFailure(unittest.TestCase):
    def test_failing_source_backs_off_and_goes_down_without_crashing(self):
        a = _FailingAdapter()
        states = []
        a.set_status_callback(lambda st, reason: states.append(st.state))

        async def run():
            task = asyncio.create_task(a.run(lambda items: asyncio.sleep(0)))
            await asyncio.sleep(0.3)
            a.stop()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        asyncio.run(run())
        self.assertEqual(states[:2], [DEGRADED, DOWN])
        self.assertGreaterEqual(a.status.consecutive_failures, 3)
        self.assertIn("upstream down", a.status.last_error)

    def test_reference_unavailable_is_reported_not_fatal(self):
        from app.pipeline.reference import compare
        r = compare({"temperature": 30.0}, -89.0, 0.0, "AWS_IN_SITU", reference_available=False)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "Reference source unavailable")


# ─────────────────────────────────────────────────────────────────────────
class TestEngineFixes(unittest.TestCase):
    def test_frozen_needs_minimum_time_span(self):
        det = AnomalyDetector()
        now = datetime.now(UTC)
        # 15 identical readings one minute apart (14 min) — healthy at 1-min cadence
        for i in range(15):
            a = det.evaluate_reading(AWSReading(station_id="F1", timestamp=now + timedelta(minutes=i),
                                                temperature_c=20.0 + 0.1 * (i % 2), pressure_hpa=1010.0,
                                                humidity_pct=60.0 + 0.1 * (i % 2)))
        self.assertNotEqual(a.root_cause, FaultType.FROZEN_SENSOR)

    def test_zscore_mad_floor_ignores_sub_resolution_moves(self):
        det = AnomalyDetector()
        now = datetime.now(UTC)
        for i in range(30):
            det.evaluate_reading(AWSReading(station_id="Z1", timestamp=now + timedelta(minutes=i),
                                            temperature_c=22.9 + 0.1 * (i % 2), pressure_hpa=1010.0 + 0.2 * (i % 3),
                                            humidity_pct=60.0 + 0.3 * (i % 2)))
        a = det.evaluate_reading(AWSReading(station_id="Z1", timestamp=now + timedelta(minutes=31),
                                            temperature_c=23.5, pressure_hpa=1010.2, humidity_pct=60.2))
        self.assertEqual(a.status, "NORMAL")

    def test_l5_diurnal_cycle_is_not_drift_when_neighbours_share_it(self):
        det = AnomalyDetector()
        now = datetime.now(UTC)
        a = None
        for i in range(120):  # 2 h at 1-min cadence, RH falling 8 %/h, T rising 1.5 °C/h
            t = now + timedelta(minutes=i)
            temp, rh = 22.0 + 1.5 * i / 60, 85.0 - 8.0 * i / 60
            nbrs = [AWSReading(station_id=f"N{j}", timestamp=t, temperature_c=temp + 0.3 * j,
                               humidity_pct=rh - 1.0 * j, pressure_hpa=1010.0, lat=12.9 + 0.02 * j, lon=77.5)
                    for j in range(4)]
            a = det.evaluate_reading(AWSReading(station_id="D1", timestamp=t, temperature_c=temp + 0.4,
                                                humidity_pct=rh + 0.5, pressure_hpa=1010.2, lat=12.91, lon=77.51),
                                     neighbors=nbrs)
        drift = a.layer_details["drift"]
        self.assertLess(a.layer_scores["drift"], 0.4, drift)
        self.assertEqual(drift["channel_drift"]["humidity_pct"]["reference_mode"], "SPATIAL")

    def test_l4_reports_neighbour_count(self):
        det = AnomalyDetector()
        nbrs = [AWSReading(station_id=f"N{j}", temperature_c=24.0, humidity_pct=60, pressure_hpa=1010,
                           lat=12.9 + 0.01 * j, lon=77.5) for j in range(4)]
        a = det.evaluate_reading(AWSReading(station_id="S", temperature_c=24.2, humidity_pct=60, pressure_hpa=1010,
                                            lat=12.91, lon=77.51), neighbors=nbrs)
        self.assertEqual(a.layer_details["spatial"]["neighbor_count"], 4)
        self.assertNotEqual(a.canonical_result["layers"]["spatial"]["status"], "INSUFFICIENT_DATA")

    def test_l3_reports_valid_channel_count(self):
        a = AnomalyDetector().evaluate_reading(AWSReading(station_id="M", temperature_c=24.0, humidity_pct=60,
                                                          pressure_hpa=1010))
        self.assertEqual(a.layer_details["multivariate"]["valid_channel_count"], 3)
        self.assertNotEqual(a.canonical_result["layers"]["multivariate"]["status"], "INSUFFICIENT_DATA")


# ─────────────────────────────────────────────────────────────────────────
class TestSimulation(unittest.TestCase):
    def _net(self):
        mk = lambda sid, lat: SimStation(sid, sid, lat, 77.5, 0, 25, 18, 1008, 10, 200, 0, 0, 0, 0)
        return SyntheticNetwork([mk("A", 12.90), mk("B", 12.92), mk("FAR", 14.0)], seed=1)

    def test_clean_signal_is_psychrometrically_consistent(self):
        v, _ = self._net().generate(time.time())["A"]
        self.assertLessEqual(v["dew_point"], v["temperature"])
        self.assertTrue(0 < v["humidity"] <= 100)

    def test_faults_apply_to_target_region_and_dropout(self):
        net, fb, t = self._net(), FaultBook(), time.time()
        fb.inject("A", "regional_event", None, "high", 600, started_at=t, station_latlon=(12.90, 77.5), radius_km=10)
        fb.inject("B", "dropout", None, "low", 600, started_at=t)
        out = net.generate(t + 1, fb)
        self.assertTrue(out["A"][1])            # affected by the regional event
        self.assertIsNone(out["B"][0])          # dropped out
        self.assertFalse(out["FAR"][1])         # outside the radius

    def test_stuck_fault_freezes_value(self):
        net, fb, t = self._net(), FaultBook(), time.time()
        fb.inject("A", "stuck", "temperature", "medium", 3600, started_at=t)
        vals = {net.generate(t + 60 * i, fb)["A"][0]["temperature"] for i in range(10)}
        self.assertEqual(len(vals), 1)

    def test_invalid_fault_rejected(self):
        with self.assertRaises(ValueError):
            FaultBook().inject("A", "meteor", None, "low", 600)
        with self.assertRaises(ValueError):
            FaultBook().inject("A", "impossible_rh", "pressure", "low", 600)


# ─────────────────────────────────────────────────────────────────────────
class TestNOAAParser(unittest.TestCase):
    def test_parses_isd_mandatory_fields(self):
        o = parse_isd_record({
            "STATION": "42182099999", "DATE": "2026-09-25T06:00:00", "LATITUDE": "28.58", "LONGITUDE": "77.2",
            "ELEVATION": "216.0", "NAME": "NEW DELHI/SAFDARJUNG, IN",
            "TMP": "+0312,1", "DEW": "+0245,1", "SLP": "10021,1", "WND": "270,1,N,0031,1",
        })
        self.assertEqual(o.station_id, "ISD-42182099999")
        self.assertAlmostEqual(o.temperature, 31.2)
        self.assertAlmostEqual(o.pressure, 1002.1)
        self.assertAlmostEqual(o.wind_speed, 3.1 * 3.6)
        self.assertTrue(60 < o.humidity < 75)
        self.assertIn("RH_DERIVED", o.meta["flags"])

    def test_missing_and_bad_quality_become_none(self):
        o = parse_isd_record({"STATION": "1", "DATE": "2026-09-25T06:00:00", "LATITUDE": "1", "LONGITUDE": "1",
                              "TMP": "+9999,9", "DEW": "+0245,3", "SLP": "99999,9", "WND": "999,9,C,0000,1"})
        self.assertIsNone(o.temperature)
        self.assertIsNone(o.dew_point)
        self.assertIsNone(o.pressure)


# ─────────────────────────────────────────────────────────────────────────
def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestEndToEndOverHTTP(unittest.TestCase):
    """observation -> ingestion -> 5-layer engine -> anomaly result ->
    incident -> persisted state -> API -> live SSE event."""

    @classmethod
    def setUpClass(cls):
        import uvicorn
        cls.tmp = _temp_env(cls)
        os.environ["ATHER_SIM_ENABLED"] = "0"
        os.environ["ATHER_REFERENCE_ENABLED"] = "0"
        os.environ["ATHER_PIPELINE_ENABLED"] = "1"
        cls.ids = _cluster(6, lat=22.57, lon=88.36, prefix="E2E")
        from app.main import app
        cls.port = _free_port()
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="warning"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                cls._get("/api/system/health")
                break
            except Exception:
                time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)
        for sid in cls.ids:
            station_service._stations.pop(sid, None)
        for k in ("ATHER_SIM_ENABLED", "ATHER_REFERENCE_ENABLED", "ATHER_PIPELINE_ENABLED"):
            os.environ.pop(k, None)
        _restore_env(cls)

    @classmethod
    def _get(cls, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{cls.port}{path}", timeout=10) as r:
            return json.loads(r.read())

    def _post(self, path, body, expect=202):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual(r.status, expect)
            return json.loads(r.read())

    def test_full_chain(self):
        snap = self._get("/api/network/state")
        events, stop = [], threading.Event()

        def listen():
            url = f"http://127.0.0.1:{self.port}/api/stream?since={snap['event_seq']}"
            with urllib.request.urlopen(url, timeout=30) as r:
                etype = None
                while not stop.is_set():
                    line = r.readline().decode().strip()
                    if line.startswith("event:"):
                        etype = line[6:].strip()
                    elif line.startswith("data:") and etype:
                        events.append((etype, json.loads(line[5:])))
                        if etype == ev.INCIDENT_CREATED:
                            return

        th = threading.Thread(target=listen, daemon=True)
        th.start()
        t0 = datetime.now(UTC) - timedelta(minutes=10)
        for k in range(5):
            t = (t0 + timedelta(minutes=k)).isoformat()
            obs = [{"station_id": sid, "observed_at": t, "source": "AWS_IN_SITU",
                    "temperature": 29.0 + 0.1 * i, "humidity": 70.0, "pressure": 1006.0,
                    "units": {}} for i, sid in enumerate(self.ids)]
            if k == 4:
                obs[0]["humidity"] = 131.0          # physically impossible
            res = self._post("/api/observations", {"observations": obs})
            self.assertEqual(res["accepted"], len(self.ids))
        # schema validation + unknown station rejected, not queued
        bad = self._post("/api/observations", {"observations": [
            {"station_id": "NOPE-1", "observed_at": t0.isoformat(), "source": "AWS_IN_SITU", "temperature": 20},
            {"station_id": self.ids[0], "observed_at": "not-a-date", "source": "AWS_IN_SITU"},
        ]})
        self.assertEqual(bad["accepted"], 0)
        self.assertEqual({r["code"] for r in bad["rejected"]}, {"UNKNOWN_STATION", "SCHEMA_INVALID"})

        th.join(timeout=15)
        stop.set()
        types = [e for e, _ in events]
        self.assertIn(ev.STATION_UPDATED, types)
        self.assertIn(ev.ANOMALY_DETECTED, types)
        self.assertIn(ev.INCIDENT_CREATED, types)
        created = next(d for e, d in events if e == ev.INCIDENT_CREATED)
        self.assertEqual(created["station_id"], self.ids[0])

        # persisted + served by the API
        inc = self._get(f"/api/incidents/{created['incident_id']}")
        self.assertEqual(inc["source"], "LIVE_AWS")
        self.assertEqual(inc["context"]["rca_category"], "physically_impossible_reading")
        live = self._get(f"/api/stations/{self.ids[0]}/live")
        self.assertEqual(live["health"]["overall_status"], "anomaly")
        det = self._get(f"/api/detections/{live['health']['detection_id']}")
        self.assertIn("L1", det["triggered_layers"])
        ts = self._get(f"/api/stations/{self.ids[0]}/timeseries?hours=1")
        self.assertEqual(len(ts["points"]), 5)
        hist = self._get(f"/api/stations/{self.ids[0]}/detections?hours=1")
        self.assertEqual(len(hist["detections"]), 5)
        health = self._get("/api/system/health")
        self.assertEqual(health["components"]["database"]["status"], "OK")
        self.assertGreaterEqual(health["metrics"]["totals"]["processed"], 25)
        self.assertGreaterEqual(health["metrics"]["totals"]["rejected"], 2)

    def test_staleness_monitor_opens_communication_incident(self):
        from app.pipeline.runtime import get_runtime
        rt = get_runtime()
        sid = "E2E-STALE"
        station_service._stations[sid] = {"id": sid, "name": "Stale AWS", "latitude": 22.4, "longitude": 88.1,
                                          "elevation": 5.0, "country": "India", "region": "Test", "town": "Test"}
        self.addCleanup(station_service._stations.pop, sid, None)
        now = datetime.now(UTC)
        rt.process_now([ObservationIn(station_id=sid, observed_at=now - timedelta(minutes=40),
                                      source="AWS_IN_SITU", adapter="push", temperature=28.0,
                                      humidity=70.0, pressure=1006.0)])
        rt.started_at = time.time() - 3600
        rt.check_staleness(time.time())
        self.assertEqual(rt.processor.health[sid]["freshness"], "STALE")
        self.assertEqual(rt.processor.health[sid]["overall_status"], "degraded")
        incs = incident_service.list_all(source="LIVE_AWS", station_id=sid)
        self.assertTrue(any(i["root_cause"] == "COMMUNICATION_OUTAGE" for i in incs))

    def test_replay_is_isolated_and_reports_markers(self):
        from app.pipeline.runtime import get_runtime
        from app.pipeline.replay import ReplayService
        rt = get_runtime()
        rt.simulation.catalogue = lambda: [rt.stations._stations[s] for s in self.ids]
        before_incidents = len(incident_service.list_all(source="ALL"))
        before_obs = rt.store.stats()["observations"]
        svc = ReplayService(rt)
        p = svc.validate({"station_id": self.ids[1], "fault_type": "spike", "parameter": "temperature",
                          "severity": "high", "window_minutes": 60, "interval_minutes": 5, "fault_start_minute": 30})
        res = svc.compute("rpl_test", p)
        keys = {m["key"] for m in res["markers"]}
        self.assertIn("fault_onset", keys)
        self.assertIn("anomaly", keys)
        self.assertIsNotNone(res["time_to_detection_min"])
        self.assertEqual(len(incident_service.list_all(source="ALL")), before_incidents)
        self.assertEqual(rt.store.stats()["observations"], before_obs)


if __name__ == "__main__":
    unittest.main()
