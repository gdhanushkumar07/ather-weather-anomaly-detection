"""
Open-Meteo reference ingestion: batching, pacing, de-duplication, caching,
single-flight, and per-status failure handling (429 / Retry-After / quota
cooldown / 5xx / 4xx / timeouts). Every upstream call is mocked — these
tests never touch the network or the real disk cache.
"""
import io
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
from email.message import Message
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.weather import open_meteo  # noqa: E402
from app.weather.open_meteo import OpenMeteoService, UpstreamError, UpstreamUnavailable  # noqa: E402


def _payload(t=28.0):
    return {"current": {"time": "2026-10-03T08:00", "temperature_2m": t, "relative_humidity_2m": 60,
                        "pressure_msl": 1009.0, "surface_pressure": 950.0, "wind_speed_10m": 8.0,
                        "wind_direction_10m": 200, "weather_code": 1}}


class _Resp:
    def __init__(self, body, status=200):
        self.status, self._body = status, body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code, reason="", retry_after=None):
    h = Message()
    if retry_after is not None:
        h["Retry-After"] = str(retry_after)
    body = json.dumps({"error": True, "reason": reason}).encode()
    return urllib.error.HTTPError("https://api.open-meteo.com/v1/forecast", code, "err", h, io.BytesIO(body))


class FakeUpstream:
    """Scripted Open-Meteo: `script` is a list of responses ('ok' or an
    exception) consumed in order; afterwards every call succeeds. Records each
    call's location count and the maximum number of concurrent calls."""

    def __init__(self, script=None, delay=0.0):
        self.script = list(script or [])
        self.calls, self.urls = [], []
        self.delay = delay
        self.active = self.max_active = 0
        self.lock = threading.Lock()

    def __call__(self, req, context=None, timeout=None):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            url = req.full_url
            self.urls.append(url)
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            n = len(q["latitude"][0].split(","))
            self.calls.append(n)
            step = self.script.pop(0) if self.script else "ok"
            if isinstance(step, Exception):
                raise step
            body = [_payload() for _ in range(n)] if n > 1 else _payload()
            return _Resp(json.dumps(body).encode())
        finally:
            with self.lock:
                self.active -= 1


def _svc(**env):
    with mock.patch.dict(os.environ, {"WEATHER_MIN_REQUEST_INTERVAL_S": "0", **env}):
        s = OpenMeteoService()
    s.cache = {}
    s._save_disk_cache = lambda: None
    s.sleeps = []
    s._sleep = s.sleeps.append            # record waits instead of sleeping
    return s


def _coords(n, dup=0):
    pts = [(8.0 + i * 0.05, 72.0 + i * 0.05) for i in range(n)]
    return pts + pts[:dup]


class TestBatching(unittest.TestCase):
    def test_300_stations_use_few_sequential_batched_requests(self):
        svc, up = _svc(), FakeUpstream()
        coords = _coords(296, dup=4)                      # 300 inputs, 296 unique
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            out = svc.get_batch_weather(coords)
        self.assertEqual(len(up.calls), 6)                 # ceil(296/50), not 296
        self.assertEqual(sum(up.calls), 296)               # duplicates requested once
        self.assertEqual(up.max_active, 1)                 # never parallel
        self.assertTrue(all(o is not None for o in out))
        self.assertEqual(out[-1], out[3])                  # duplicate gets the same value

    def test_url_is_multi_location_current_only(self):
        svc, up = _svc(), FakeUpstream()
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            svc.get_batch_weather(_coords(3))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(up.urls[0]).query)
        self.assertEqual(len(q["latitude"][0].split(",")), 3)
        self.assertEqual(len(q["longitude"][0].split(",")), 3)
        self.assertNotIn("hourly", q)
        self.assertNotIn("daily", q)
        self.assertLessEqual(len(q["current"][0].split(",")), 10)

    def test_minimum_spacing_between_requests(self):
        svc, up = _svc(WEATHER_MIN_REQUEST_INTERVAL_S="1.5"), FakeUpstream()
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            svc.get_batch_weather(_coords(150))
        self.assertEqual(len(up.calls), 3)
        self.assertEqual(len([s for s in svc.sleeps if s > 1.0]), 2)    # paced between calls


class TestApiKey(unittest.TestCase):
    def test_api_key_switches_to_customer_endpoint(self):
        svc, up = _svc(), FakeUpstream()
        with mock.patch.dict(os.environ, {"OPEN_METEO_API_KEY": "k123"}), \
             mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            svc.get_batch_weather(_coords(2))
        self.assertTrue(up.urls[0].startswith("https://customer-api.open-meteo.com/"))
        self.assertIn("apikey=k123", up.urls[0])


class TestCache(unittest.TestCase):
    def test_fresh_cache_makes_no_request(self):
        svc, up = _svc(), FakeUpstream()
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            svc.get_batch_weather(_coords(60))
            svc.get_batch_weather(_coords(60))
            svc.get_current_weather(*_coords(1)[0])
        self.assertEqual(len(up.calls), 2)                 # first refresh only
        self.assertEqual(svc.last_report["to_fetch"], 0)

    def test_only_stale_locations_are_refetched(self):
        svc, up = _svc(), FakeUpstream()
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            svc.get_batch_weather(_coords(60))
            for k in list(svc.cache)[:7]:
                svc.cache[k]["cached_at"] -= 10_000
            svc.get_batch_weather(_coords(60))
        self.assertEqual(up.calls[-1], 7)

    def test_single_flight_concurrent_refreshes(self):
        svc, up = _svc(), FakeUpstream(delay=0.05)
        svc._sleep = lambda s: None
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            ts = [threading.Thread(target=svc.get_batch_weather, args=(_coords(100),)) for _ in range(5)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        self.assertEqual(sum(up.calls), 100)               # one refresh did the work
        self.assertEqual(up.max_active, 1)


class TestFailureHandling(unittest.TestCase):
    def test_429_respects_retry_after(self):
        svc, up = _svc(), FakeUpstream([_http_error(429, "Minutely API request limit exceeded.", retry_after=7)])
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            out = svc.get_batch_weather(_coords(10))
        self.assertIn(7.0, svc.sleeps)
        self.assertEqual(svc.last_report["fetched"], 10)
        self.assertTrue(all(out))

    def test_429_exponential_backoff_with_jitter_then_cooldown(self):
        svc = _svc()
        up = FakeUpstream([_http_error(429, "Minutely API request limit exceeded.")] * 5)
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            svc.get_batch_weather(_coords(120))          # 3 batches
        waits = svc.sleeps
        for w, base in zip(waits, (2, 5, 10, 20)):
            self.assertTrue(base * 0.8 <= w <= base * 1.25, (w, base))
        self.assertEqual(len(up.calls), 5)                 # 1 + 4 retries, then stop
        self.assertTrue(svc.blocked())                     # brief cooldown
        self.assertEqual(svc.last_report["deferred_locations"], 70)   # other batches deferred, not hammered

    def test_daily_quota_stops_and_cools_down_until_reset(self):
        svc = _svc()
        up = FakeUpstream([_http_error(429, "Daily API request limit exceeded. Please try again tomorrow.")])
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            svc.get_batch_weather(_coords(120))
            self.assertEqual(len(up.calls), 1)             # no retry against a daily quota
            self.assertGreater(svc.blocked_until - time.time(), 0)
            svc.get_batch_weather(_coords(120))            # within cooldown: no upstream call
            self.assertEqual(len(up.calls), 1)
            self.assertEqual(svc.last_report["skipped"], "cooldown")

    def test_5xx_and_timeouts_retry_then_succeed(self):
        svc = _svc()
        up = FakeUpstream([_http_error(503, "unavailable"), urllib.error.URLError("timed out")])
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            svc.get_batch_weather(_coords(10))
        self.assertEqual(len(up.calls), 3)
        self.assertEqual(svc.last_report["fetched"], 10)

    def test_400_is_not_retried_and_other_batches_continue(self):
        svc = _svc()
        up = FakeUpstream([_http_error(400, "bad latitude")])
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            svc.get_batch_weather(_coords(120))
        self.assertEqual(len(up.calls), 3)                 # failed batch once + 2 other batches
        self.assertEqual(svc.last_report["failed_locations"], 50)
        self.assertEqual(svc.last_report["fetched"], 70)
        self.assertFalse(svc.blocked())

    def test_partial_failure_keeps_last_valid_values(self):
        svc, up = _svc(), FakeUpstream()
        coords = _coords(60)
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            before = svc.get_batch_weather(coords)
        for k in svc.cache:
            svc.cache[k]["cached_at"] -= 10_000
        up.script = [_http_error(500, "boom")] * 5
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            after = svc.get_batch_weather(coords)
        self.assertEqual(after, before)                    # stale-but-real, never None or zeros
        self.assertEqual(svc.last_report["failed_locations"], 50)

    def test_on_demand_negative_cache_and_cooldown(self):
        svc = _svc()
        up = FakeUpstream([_http_error(500, "boom")])
        with mock.patch.object(open_meteo.urllib.request, "urlopen", up):
            with self.assertRaises(UpstreamError):
                svc.get_current_weather(12.9, 77.6)
            with self.assertRaises(UpstreamUnavailable):
                svc.get_current_weather(12.9, 77.6)        # recently failed: no second hit
        self.assertEqual(len(up.calls), 1)


class TestPoller(unittest.TestCase):
    def test_adapter_waits_out_quota_and_retries_partial_sooner(self):
        from app.sources.open_meteo_reference import OpenMeteoReferenceAdapter
        svc = _svc()
        with mock.patch.object(OpenMeteoReferenceAdapter, "_service", staticmethod(lambda: svc)):
            a = OpenMeteoReferenceAdapter(lambda: _coords(10))
            svc.blocked_until = time.time() + 1800
            self.assertGreaterEqual(a.backoff_delay(), 1800)
            svc.blocked_until = 0
            svc.last_report = {"failed_locations": 50}
            self.assertLess(a.success_delay(), a.cadence_s)
            svc.last_report = {"failed_locations": 0}
            self.assertEqual(a.success_delay(), a.cadence_s)


if __name__ == "__main__":
    unittest.main()
