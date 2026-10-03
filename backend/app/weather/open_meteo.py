"""
SkyGuard AI — Open-Meteo NWP reference client
--------------------------------------------
Open-Meteo is MODEL output. SkyGuard uses it only as the observed-vs-model
reference layer and as the baseline the simulated AWS feed is seeded from —
never as a station observation.

Upstream discipline (Open-Meteo's free API counts EVERY LOCATION in a
multi-location request as one call, and Render's outbound IP is shared):

  * one request path for the whole process: every upstream call goes through
    `_request()`, which holds a lock and enforces a minimum spacing between
    calls (effective concurrency = 1, from the poller and on-demand paths alike)
  * the background poller is the only bulk fetcher: multi-location batches,
    de-duplicated coordinates, only stale/missing locations, sent sequentially
  * single-flight: a second batch refresh while one runs is served from cache
  * per-status handling: 429 respects Retry-After, backs off 2/5/10/20 s with
    jitter; an hourly/daily quota stops the poll and sets a cooldown until the
    quota resets; 5xx/timeouts back off; 400/401/403/404 are not retried
  * the cache is never cleared on failure: readers get the last valid values
    with their fetch time (stale-while-revalidate); no value is ever invented

Configuration (environment):
  WEATHER_POLL_INTERVAL_SECONDS      3600  background refresh cadence
  WEATHER_CACHE_TTL_SECONDS          3000  a location older than this is refetched
  WEATHER_BATCH_SIZE                 50    locations per request
  WEATHER_MIN_REQUEST_INTERVAL_S     1.5   minimum spacing between upstream calls
  WEATHER_MAX_RETRIES                4     retries per batch (2/5/10/20 s + jitter)
  OPEN_METEO_API_KEY                 -     optional; uses the commercial endpoint (own quota)
"""

import email.utils
import logging
import os
import random
import socket
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple

log = logging.getLogger("skyguard.weather")
if not log.handlers:
    # The app configures no logging, so INFO would be dropped; ingestion logs
    # are what diagnoses production upstream problems (WEATHER_LOG_LEVEL).
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    log.addHandler(_h)
    log.setLevel(os.environ.get("WEATHER_LOG_LEVEL", "INFO").upper())
    log.propagate = False

# WMO Weather interpretation codes (WW)
WMO_WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail"
}

def degrees_to_cardinal(deg: Optional[float]) -> str:
    if deg is None:
        return "CALM"
    val = int((deg / 22.5) + 0.5)
    cardinals = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
    ]
    return cardinals[(val % 16)]

import os
import ssl
from typing import List


def _tls_context() -> ssl.SSLContext:
    """Verified TLS. certifi's CA bundle is used when available because
    python.org macOS builds ship without system CA certificates."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()



def select_pressure(current: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    """The pressure ATHER uses, together with WHICH Open-Meteo field supplied it.

    Selection is unchanged: `pressure_msl` when present, otherwise
    `surface_pressure`. What is new is the recorded convention, so a fallback to
    surface pressure can never be mistaken for sea-level pressure downstream:

        pressure_msl used        -> "MSL"
        surface_pressure used    -> "SURFACE"
        neither available        -> (None, None)

    This is PROVENANCE only. The value is returned exactly as Open-Meteo gave it
    (no correction is applied).
    """
    msl = current.get("pressure_msl")
    if msl:
        return msl, "MSL"
    surface = current.get("surface_pressure")
    if surface:
        return surface, "SURFACE"
    return None, None


def with_pressure_provenance(data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures a formatted weather record carries `pressureConvention`.

    Records written before the field existed (disk cache) are completed ONLY when
    it is logically certain: `pressure` is always either pressure_msl or
    surface_pressure, so a `pressure` that differs from the record's own
    `surfacePressure` must have come from pressure_msl. If they are equal the
    source field cannot be told apart, so the convention stays None (UNKNOWN).
    No conclusion is drawn from the magnitude of the pressure.
    """
    if data.get("pressureConvention") is not None or "pressureConvention" in data:
        return data
    p, sp = data.get("pressure"), data.get("surfacePressure")
    data = dict(data)
    data["pressureConvention"] = "MSL" if (p is not None and sp is not None and p != sp) else None
    return data


CURRENT_VARS = ("temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,"
                "pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m")
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CUSTOMER_FORECAST_URL = "https://customer-api.open-meteo.com/v1/forecast"
USER_AGENT = "SkyGuard-AI-Weather/1.1 (academic-monitoring)"
RETRY_DELAYS_S = (2.0, 5.0, 10.0, 20.0)
NEGATIVE_CACHE_S = 300.0


def _env_f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _key(lat: float, lon: float) -> str:
    return f"{round(lat, 3)}_{round(lon, 3)}"


class UpstreamError(Exception):
    """One classified upstream failure."""

    def __init__(self, kind: str, status: Optional[int], message: str,
                 retry_after: Optional[float] = None, scope: Optional[str] = None):
        super().__init__(message)
        self.kind = kind            # rate_limited | client_error | config_error | server_error | network | bad_payload
        self.status = status
        self.retry_after = retry_after
        self.scope = scope          # for rate limits: minute | hour | day | None (unknown)

    @property
    def retryable(self) -> bool:
        return self.kind in ("rate_limited", "server_error", "network") and self.scope not in ("hour", "day")


class UpstreamUnavailable(Exception):
    """The upstream is in a cooldown (quota exhausted) or recently failed here."""


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            dt = email.utils.parsedate_to_datetime(value)
            return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
        except Exception:
            return None


def _rate_limit_scope(reason: str) -> Optional[str]:
    r = (reason or "").lower()
    return "day" if "daily" in r else "hour" if "hourly" in r else "minute" if "minutely" in r else None


def _quota_reset(scope: str, now: float) -> float:
    t = datetime.fromtimestamp(now, tz=timezone.utc)
    if scope == "day":
        nxt = (t + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        nxt = (t + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return nxt.timestamp() + 30.0


def _format(item: Dict[str, Any], lat: float, lon: float) -> Dict[str, Any]:
    current = item.get("current") or {}
    weather_code = current.get("weather_code", 0)
    wind_deg = current.get("wind_direction_10m")
    pressure, pressure_convention = select_pressure(current)
    return {
        "latitude": lat,
        "longitude": lon,
        "temperature": current.get("temperature_2m"),
        "apparentTemperature": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "pressure": pressure,
        "pressureConvention": pressure_convention,
        "surfacePressure": current.get("surface_pressure"),
        "windSpeed": current.get("wind_speed_10m"),
        "windGusts": current.get("wind_gusts_10m"),
        "windDirectionDeg": wind_deg,
        "windDirection": degrees_to_cardinal(wind_deg),
        "precipitation": current.get("precipitation", 0.0),
        "weatherCode": weather_code,
        "condition": WMO_WEATHER_CODES.get(weather_code, "Fair"),
        "timestamp": current.get("time"),
        "source": "NWP_MODEL_REFERENCE",
    }


class OpenMeteoService:
    def __init__(self, cache_ttl_seconds: Optional[float] = None):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = cache_ttl_seconds if cache_ttl_seconds is not None else _env_f("WEATHER_CACHE_TTL_SECONDS", 3000)
        self.batch_size = int(_env_f("WEATHER_BATCH_SIZE", 50))
        self.min_interval_s = _env_f("WEATHER_MIN_REQUEST_INTERVAL_S", 1.5)
        self.max_retries = int(_env_f("WEATHER_MAX_RETRIES", len(RETRY_DELAYS_S)))
        self._cache_file = os.path.join(os.path.dirname(__file__), ".weather_cache.json")
        self._load_disk_cache()
        self._ctx = _tls_context()
        self._sleep = time.sleep                 # injectable for tests
        self._request_lock = threading.Lock()    # ONE upstream call at a time, process-wide
        self._refresh_lock = threading.Lock()    # single-flight batch refresh
        self._last_request_at = 0.0
        self._failed_at: Dict[str, float] = {}   # on-demand negative cache
        self.blocked_until = 0.0                 # quota cooldown (hourly/daily limit)
        self.blocked_reason: Optional[str] = None
        self.stats = {"requests": 0, "locations_requested": 0, "rate_limited": 0, "retries": 0}
        # Outcome of the most recent batch refresh — lets the reference adapter
        # distinguish "source down" from "everything already cached".
        self.last_report: Dict[str, Any] = {}

    # ── disk cache (last valid values survive restarts on persistent disks) ──
    def _load_disk_cache(self):
        try:
            if os.path.exists(self._cache_file):
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
        except Exception as e:
            log.warning("[WEATHER] could not load disk cache: %s", e)

    def _save_disk_cache(self):
        try:
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f)
        except Exception:
            pass

    # ── the single upstream request path ────────────────────────────────
    def blocked(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) < self.blocked_until

    def _request(self, lats: List[float], lons: List[float]) -> Any:
        """One paced upstream call. Raises UpstreamError (classified)."""
        params = {
            "latitude": ",".join(f"{x:.4f}" for x in lats),
            "longitude": ",".join(f"{x:.4f}" for x in lons),
            "current": CURRENT_VARS,
        }
        api_key = os.environ.get("OPEN_METEO_API_KEY", "").strip()
        if api_key:
            # Commercial endpoint: its own quota instead of the free tier's
            # per-IP limit (Render's outbound IP is shared). Never logged.
            params["apikey"] = api_key
        base = CUSTOMER_FORECAST_URL if api_key else FORECAST_URL
        url = f"{base}?{urllib.parse.urlencode(params, safe=',')}"
        with self._request_lock:
            wait = self._last_request_at + self.min_interval_s - time.time()
            if wait > 0:
                self._sleep(wait)
            self._last_request_at = time.time()
            self.stats["requests"] += 1
            self.stats["locations_requested"] += len(lats)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, context=self._ctx, timeout=15) as response:
                    status = getattr(response, "status", 200)
                    raw = response.read()
            except urllib.error.HTTPError as e:
                try:
                    detail = e.read().decode("utf-8", "replace")
                    reason = (json.loads(detail) or {}).get("reason") or detail
                except Exception:
                    reason = str(e)
                reason = str(reason)[:200]
                hdrs = getattr(e, "headers", None)
                retry_after = _parse_retry_after(hdrs.get("Retry-After") if hdrs is not None else None)
                code = e.code
                if code == 429:
                    self.stats["rate_limited"] += 1
                    raise UpstreamError("rate_limited", 429, f"HTTP 429: {reason}", retry_after, _rate_limit_scope(reason))
                if code in (401, 403, 404):
                    raise UpstreamError("config_error", code, f"HTTP {code}: {reason} (check endpoint/configuration)")
                if 400 <= code < 500:
                    raise UpstreamError("client_error", code, f"HTTP {code}: {reason}")
                raise UpstreamError("server_error", code, f"HTTP {code}: {reason}", retry_after)
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
                raise UpstreamError("network", None, f"{type(e).__name__}: {e}"[:200])
        if status != 200:
            raise UpstreamError("server_error" if status >= 500 else "client_error", status, f"HTTP {status}")
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise UpstreamError("bad_payload", status, f"unparseable response: {e}")
        if isinstance(data, dict) and data.get("error"):
            raise UpstreamError("client_error", status, f"API error: {data.get('reason')}")
        return data

    def _request_with_retry(self, lats: List[float], lons: List[float], label: str) -> Any:
        attempt = 0
        while True:
            try:
                return self._request(lats, lons)
            except UpstreamError as e:
                if e.kind == "rate_limited" and e.scope in ("hour", "day"):
                    self.blocked_until = _quota_reset(e.scope, time.time())
                    self.blocked_reason = f"Open-Meteo {e.scope}ly quota exhausted"
                    log.warning("[WEATHER] %s status=429 scope=%s — cooldown until %s",
                                label, e.scope, datetime.fromtimestamp(self.blocked_until, tz=timezone.utc).isoformat())
                    raise
                if not e.retryable or attempt >= self.max_retries:
                    if e.kind == "rate_limited":
                        # minute limit still active after all retries: brief cooldown
                        self.blocked_until = time.time() + max(60.0, e.retry_after or 0.0)
                        self.blocked_reason = "Open-Meteo rate limit (retries exhausted)"
                    log.warning("[WEATHER] %s failed kind=%s status=%s attempts=%d: %s",
                                label, e.kind, e.status, attempt + 1, e)
                    raise
                base = RETRY_DELAYS_S[min(attempt, len(RETRY_DELAYS_S) - 1)]
                delay = e.retry_after if e.retry_after is not None else base * random.uniform(0.8, 1.25)
                attempt += 1
                self.stats["retries"] += 1
                log.info("[WEATHER] %s status=%s retry_after=%s retry attempt=%d delay=%.1fs",
                         label, e.status, e.retry_after, attempt + 1, delay)
                self._sleep(delay)

    # ── on-demand single location (cache-first, never retries in a request) ──
    def get_current_weather(self, lat: float, lon: float) -> Dict[str, Any]:
        k = _key(lat, lon)
        now = time.time()
        entry = self.cache.get(k)
        if entry and now - entry["cached_at"] < self.cache_ttl:
            return with_pressure_provenance(entry["data"])
        if self.blocked(now) or now - self._failed_at.get(k, 0.0) < NEGATIVE_CACHE_S:
            if entry:
                return with_pressure_provenance(entry["data"])      # last valid value, with its own timestamp
            raise UpstreamUnavailable(self.blocked_reason or "Open-Meteo recently failed for this location")
        try:
            raw = self._request([lat], [lon])
        except UpstreamError as e:
            self._failed_at[k] = now
            if e.kind == "rate_limited" and e.scope in ("hour", "day"):
                self.blocked_until = _quota_reset(e.scope, now)
                self.blocked_reason = f"Open-Meteo {e.scope}ly quota exhausted"
            elif e.kind == "rate_limited":
                self.blocked_until = now + max(60.0, e.retry_after or 0.0)
                self.blocked_reason = "Open-Meteo rate limit"
            if entry:
                return with_pressure_provenance(entry["data"])
            raise
        item = raw[0] if isinstance(raw, list) else raw
        data = _format(item, lat, lon)
        self.cache[k] = {"cached_at": now, "data": data}
        self._save_disk_cache()
        return data

    # ── background bulk refresh (the poller) ────────────────────────────
    def get_batch_weather(
        self,
        coords: List[Any],
        chunk_size: Optional[int] = None,
        cache_only: bool = False,
    ) -> List[Optional[Dict[str, Any]]]:
        """Returns the cached reference for every coordinate (in input order,
        None where nothing was ever fetched), refreshing stale/missing
        locations first unless cache_only. Never makes parallel requests."""
        chunk_size = max(1, chunk_size or self.batch_size)
        now = time.time()

        def from_cache() -> List[Optional[Dict[str, Any]]]:
            out = []
            for lat, lon in coords:
                e = self.cache.get(_key(lat, lon))
                out.append(with_pressure_provenance(e["data"]) if e else None)
            return out

        if cache_only:
            return from_cache()

        unique: Dict[str, Tuple[float, float]] = {}
        for lat, lon in coords:
            unique.setdefault(_key(lat, lon), (lat, lon))
        stale = [k for k in unique if k not in self.cache or now - self.cache[k]["cached_at"] >= self.cache_ttl]
        report = {"requested": len(coords), "unique": len(unique), "to_fetch": len(stale), "fetched": 0,
                  "errors": 0, "failed_locations": 0, "deferred_locations": 0, "batches": 0,
                  "last_error": None, "at": now, "skipped": None}

        if not stale:
            self.last_report = report
            log.info("[WEATHER] cache hit stations=%d (all fresh)", len(unique))
            return from_cache()
        if self.blocked(now):
            report.update(skipped="cooldown", deferred_locations=len(stale), last_error=self.blocked_reason)
            self.last_report = report
            log.info("[WEATHER] poll skipped: %s (until %s); serving cache", self.blocked_reason,
                     datetime.fromtimestamp(self.blocked_until, tz=timezone.utc).isoformat())
            return from_cache()
        if not self._refresh_lock.acquire(blocking=False):
            report["skipped"] = "refresh_in_progress"
            self.last_report = report
            return from_cache()
        try:
            chunks = [stale[i:i + chunk_size] for i in range(0, len(stale), chunk_size)]
            report["batches"] = len(chunks)
            log.info("[WEATHER] poll started stations=%d unique_coordinates=%d stale=%d batches=%d",
                     len(coords), len(unique), len(stale), len(chunks))
            updated = False
            for n, keys in enumerate(chunks, start=1):
                if self.blocked():
                    report["deferred_locations"] += sum(len(c) for c in chunks[n - 1:])
                    break
                pts = [unique[k] for k in keys]
                try:
                    raw = self._request_with_retry([p[0] for p in pts], [p[1] for p in pts], f"batch={n}/{len(chunks)}")
                except UpstreamError as e:
                    report["errors"] += 1
                    report["failed_locations"] += len(keys)
                    report["last_error"] = str(e)[:200]
                    continue            # previous values stay in the cache; other batches continue
                items = raw if isinstance(raw, list) else [raw]
                if len(items) != len(keys):
                    report["errors"] += 1
                    report["failed_locations"] += len(keys)
                    report["last_error"] = f"batch={n}: {len(items)} results for {len(keys)} locations"
                    continue
                t = time.time()
                for k, (lat, lon), item in zip(keys, pts, items):
                    self.cache[k] = {"cached_at": t, "data": _format(item, lat, lon)}
                report["fetched"] += len(keys)
                updated = True
                log.info("[WEATHER] batch=%d/%d status=200 locations=%d", n, len(chunks), len(keys))
            if updated:
                self._save_disk_cache()
        finally:
            self._refresh_lock.release()
        stale_left = sum(1 for k in unique if k not in self.cache or time.time() - self.cache[k]["cached_at"] >= self.cache_ttl)
        report["stale_after"] = stale_left
        self.last_report = report
        log.info("[WEATHER] poll completed success=%d failed=%d deferred=%d stale_stations=%d",
                 report["fetched"], report["failed_locations"], report["deferred_locations"], stale_left)
        return from_cache()


open_meteo_service = OpenMeteoService()
