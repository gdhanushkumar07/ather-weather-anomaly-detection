"""
PipelineRuntime — owns the continuously running parts of ATHER.

    adapters ─(ObservationIn)─> ingest(): validate · timestamp · normalize ·
    catalogue ─> stream ─> consumer (worker thread: ObservationProcessor)
    ─> EventBroker ─> /api/stream (SSE)

Background tasks: one per source adapter, the stream consumer, a staleness
monitor (stale station -> degraded; silent for 5 cadences -> communication
incident), a metrics heartbeat, fault expiry and retention pruning.

Configuration (environment, server-side only):
  ATHER_PIPELINE_ENABLED      1   start the runtime with the API
  ATHER_SIM_ENABLED           1   run the simulated AWS feed
  ATHER_SIM_INTERVAL_S        60  simulated observation cadence per station
  ATHER_SIM_MAX_STATIONS      -   limit simulated stations
  ATHER_REFERENCE_ENABLED     1   keep the Open-Meteo reference cache warm
  ATHER_RETENTION_HOURS       24  time-series retention
  ATHER_INGEST_TOKEN          -   if set, required on POST /api/observations
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from . import events as ev
from .events import EventBroker
from .metrics import PipelineMetrics
from .models import NormalizedObservation, ObservationIn, RejectedObservation
from .normalize import normalize
from .processor import ObservationProcessor, incident_event_payload, incident_source_for
from .store import TimeSeriesStore
from .stream import InMemoryObservationStream, StreamFull

log = logging.getLogger("ather.runtime")

ENV = os.environ.get


def _flag(name: str, default: str = "1") -> bool:
    return ENV(name, default).strip().lower() not in ("0", "false", "no", "off")


class PipelineRuntime:
    def __init__(self, *, detector, station_service, incident_service, store: Optional[TimeSeriesStore] = None,
                 sim_enabled: Optional[bool] = None, reference_enabled: Optional[bool] = None,
                 sim_interval_s: Optional[float] = None):
        from app.sources.external_stubs import IMDAWSAdapter, WeatherUnionAdapter
        from app.sources.noaa_isd import NOAAISDAdapter
        from app.sources.open_meteo_reference import OpenMeteoReferenceAdapter
        from app.sources.simulation import FaultBook, SimulationAdapter

        self.stations = station_service
        self.incidents = incident_service
        self.detector = detector
        self.metrics = PipelineMetrics()
        self.broker = EventBroker()
        self.stream = InMemoryObservationStream(maxsize=int(ENV("ATHER_STREAM_CAPACITY", "20000")))
        self.store = store or TimeSeriesStore()
        self.retention_h = float(ENV("ATHER_RETENTION_HOURS", "24"))
        self.faults = FaultBook()

        sim_enabled = _flag("ATHER_SIM_ENABLED") if sim_enabled is None else sim_enabled
        reference_enabled = _flag("ATHER_REFERENCE_ENABLED") if reference_enabled is None else reference_enabled
        interval = sim_interval_s or float(ENV("ATHER_SIM_INTERVAL_S", "60"))
        max_st = ENV("ATHER_SIM_MAX_STATIONS")

        self.reference = OpenMeteoReferenceAdapter(self._reference_coords, enabled=reference_enabled)
        self.simulation = SimulationAdapter(
            station_service, self.faults, interval_s=interval,
            max_stations=int(max_st) if max_st else None, reference_lookup=self._reference_for,
        )
        self.adapters = [
            self.simulation,
            NOAAISDAdapter(),
            WeatherUnionAdapter(self._weather_union_ids),
            IMDAWSAdapter(),
            self.reference,
        ]
        if not sim_enabled:
            self.simulation.configured = lambda: "Disabled by ATHER_SIM_ENABLED=0"
        for a in self.adapters:
            a.set_status_callback(self._on_source_status)
        self._cadence = {a.name: a.cadence_s for a in self.adapters}
        self._cadence["push"] = 300.0

        self.processor = ObservationProcessor(
            detector=detector, station_service=station_service, store=self.store,
            incident_service=incident_service, metrics=self.metrics,
            reference_available=lambda: self.reference.available,
        )
        self.state = "STOPPED"
        self.started_at: Optional[float] = None
        self._tasks: List[asyncio.Task] = []
        self._outage_incidents: Dict[str, str] = {}

    # ── helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def _reference_for(stn: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from app.weather.open_meteo import open_meteo_service
        e = open_meteo_service.cache.get(f"{round(stn['latitude'], 3)}_{round(stn['longitude'], 3)}")
        return e["data"] if e else None

    def _reference_coords(self):
        return [(s["latitude"], s["longitude"]) for s in self.simulation.catalogue()]

    def _weather_union_ids(self):
        return [s["id"] for s in self.simulation.catalogue()]

    def _on_source_status(self, status, reason: Optional[str]) -> None:
        self.broker.publish(ev.DATA_SOURCE_STATUS_CHANGED, status.to_dict() | {"reason": reason})

    # ── ingestion (spec §6 steps 1–7) ───────────────────────────────────
    def prepare(self, obs: ObservationIn, received_at: Optional[datetime] = None) -> NormalizedObservation:
        """Validate, normalize and attach catalogue metadata. Raises
        RejectedObservation with a structured code."""
        stn = self.stations._stations.get(obs.station_id)
        if stn is None:
            if obs.station is None:
                raise RejectedObservation(
                    "UNKNOWN_STATION",
                    f"Station '{obs.station_id}' is not in the ATHER catalogue and no station metadata was supplied.",
                    obs.station_id,
                )
            m = obs.station
            self.stations._stations[obs.station_id] = {
                "id": obs.station_id, "name": m.name or obs.station_id, "latitude": m.latitude,
                "longitude": m.longitude, "elevation": m.elevation, "region": m.region or "",
                "country": m.country or "", "town": ", ".join(p for p in (m.region, m.country) if p),
                "network": m.network or obs.adapter, "status": "NORMAL", "anomaly": None,
                "timestamp": None, "dataSource": obs.source,
            }
        norm = normalize(obs, received_at, cadence_s=self._cadence.get(obs.adapter, 300.0))
        norm.flags.extend(obs.meta.get("flags", []))
        return norm

    async def ingest(self, items: List[ObservationIn], block: bool = True) -> Dict[str, Any]:
        accepted, rejected = [], []
        received = datetime.now(timezone.utc)
        for obs in items:
            self.metrics.received.add()
            try:
                norm = self.prepare(obs, received)
                if block:
                    await self.stream.put(norm)
                else:
                    self.stream.put_nowait(norm)
                accepted.append(norm.observation_id)
            except RejectedObservation as e:
                self.metrics.rejected.add()
                rejected.append(e.to_dict())
            except StreamFull as e:
                self.metrics.rejected.add()
                rejected.append({"code": "STREAM_FULL", "message": str(e), "station_id": obs.station_id})
        return {"accepted": len(accepted), "observation_ids": accepted, "rejected": rejected}

    def process_now(self, items: List[ObservationIn]) -> Dict[str, Any]:
        """Synchronous path (legacy /api/ingest): process immediately and
        return the DetectionResult. Same processor, same events."""
        norms, rejected = [], []
        for obs in items:
            self.metrics.received.add()
            try:
                norms.append(self.prepare(obs))
            except RejectedObservation as e:
                self.metrics.rejected.add()
                rejected.append(e.to_dict())
        outcomes = self.processor.process_batch(norms) if norms else []
        self._publish_outcomes(outcomes)
        return {"outcomes": outcomes, "rejected": rejected}

    # ── lifecycle ───────────────────────────────────────────────────────
    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.broker.attach_loop(loop)
        self.state = "WARMING_UP"
        self.started_at = time.time()
        seeded = self.processor.seed_health_from_store()
        if seeded:
            ids = [sid for sid in self.processor._last_observed]
            n = await asyncio.to_thread(self.processor.warm_up, ids, 20)
            log.info("warm-up: %d stations, %d observations replayed into engine state", len(ids), n)
        self._tasks = [asyncio.create_task(self._consume(), name="consumer")]
        for a in self.adapters:
            self._tasks.append(asyncio.create_task(a.run(self._emit), name=f"source:{a.name}"))
        self._tasks += [
            asyncio.create_task(self._staleness_monitor(), name="staleness"),
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
            asyncio.create_task(self._housekeeping(), name="housekeeping"),
        ]
        self.state = "RUNNING"

    async def stop(self) -> None:
        self.state = "STOPPING"
        for a in self.adapters:
            a.stop()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self.state = "STOPPED"

    async def _emit(self, items: List[ObservationIn]) -> None:
        await self.ingest(items, block=True)

    def _publish_outcomes(self, outcomes: List[Dict[str, Any]]) -> None:
        now = time.time()
        for o in outcomes:
            for type_, data in o.get("events", []):
                self.broker.publish(type_, data)
            if o.get("observed_epoch"):
                self.metrics.end_to_end.add((now - o["observed_epoch"]) * 1000.0)

    async def _consume(self) -> None:
        while True:
            try:
                batch = await self.stream.get_batch(max_items=500, timeout=1.0)
                if not batch:
                    continue
                outcomes = await asyncio.to_thread(self.processor.process_batch, batch)
                self._publish_outcomes(outcomes)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # never let the consumer die
                self.metrics.errors.add()
                self.metrics.last_error = f"consumer: {e!r}"
                log.exception("consumer loop error")
                await asyncio.sleep(1.0)

    async def _staleness_monitor(self) -> None:
        while True:
            await asyncio.sleep(15.0)
            try:
                self.check_staleness(time.time())
            except Exception:
                log.exception("staleness monitor error")

    def check_staleness(self, now: float) -> None:
        """A station whose source adapter is healthy but which has gone
        quiet is a station-level communication problem. (If the whole
        adapter is down, that is shown as a source outage instead of
        hundreds of per-station incidents.)"""
        adapters = {a.name: a for a in self.adapters}
        for sid, h in list(self.processor.health.items()):
            cadence = h.get("cadence_s") or 300.0
            age = now - (h.get("last_observed_epoch") or now)
            adapter = adapters.get(h.get("adapter"))
            source_ok = adapter is None or adapter.status.state == "ACTIVE"
            if age > 3 * cadence and h.get("freshness") != "STALE" and source_ok:
                h["freshness"] = "STALE"
                h["previous_status"] = h.get("overall_status")
                h["overall_status"] = "degraded"
                h["summary"] = f"DEGRADED — no observation for {int(age)} s (expected every {int(cadence)} s)."
                payload = ObservationProcessor.station_event_payload(h)
                self.broker.publish(ev.STATION_UPDATED, payload)
                self.broker.publish(ev.STATION_STALE, payload | {"silent_s": int(age)})
            if (age > 5 * cadence and source_ok and sid not in self._outage_incidents
                    and self.started_at and now - self.started_at > 5 * cadence):
                self._open_outage_incident(sid, h, age, cadence)
            if age <= 3 * cadence and sid in self._outage_incidents:
                self._outage_incidents.pop(sid, None)  # recovered; operator closes the incident

    def _open_outage_incident(self, sid: str, h: Dict[str, Any], age: float, cadence: float) -> None:
        stn = self.stations._stations.get(sid, {})
        last = h.get("last_observed_at")
        snapshot = {
            "station_id": sid, "station_name": stn.get("name"), "town": stn.get("town"),
            "region": stn.get("region"), "country": stn.get("country"),
            "parameter": "Telemetry link", "status": "WARNING", "severity": "WARNING",
            "anomaly_score": None, "confidence": 0.9,
            "root_cause": "COMMUNICATION_OUTAGE", "root_cause_confidence": "HIGH",
            "recommended_action": "Investigate communications: check modem/power at the station and the upstream data link.",
            "evidence": [
                f"No observation received for {int(age)} s; expected cadence {int(cadence)} s.",
                f"Last observation at {last}.",
                "The source adapter itself is healthy, so the silence is specific to this station.",
            ],
            "observation_timestamp": last, "obs_source": h.get("source"), "freshness": "STALE",
            "source": incident_source_for(h.get("source") or ""),
            "context": {
                "interpretation": "communication_issue", "rca_category": "communication_issue",
                "rca_label": "Communication issue", "action_category": "investigate_communications",
                "action_label": "Investigate communications", "first_observation_at": last,
                "summary": f"DEGRADED — station silent for {int(age)} s.",
                "provenance": {"data_source": h.get("source"), "simulated": h.get("simulated"),
                               "injected_fault": h.get("injected_fault")},
            },
        }
        inc = self.incidents.upsert_from_evaluation(snapshot)
        if inc:
            self._outage_incidents[sid] = inc["incident_id"]
            h["active_incident_id"] = inc["incident_id"]
            self.metrics.incidents_created.add()
            self.broker.publish(ev.INCIDENT_CREATED, incident_event_payload(inc))

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            try:
                self.broker.publish(ev.SYSTEM_METRICS, self.system_health(compact=True))
            except Exception:
                log.exception("heartbeat error")

    async def _housekeeping(self) -> None:
        last_prune = 0.0
        while True:
            await asyncio.sleep(10.0)
            now = time.time()
            for f in self.faults.expire(now):
                self.broker.publish(ev.FAULT_CLEARED, f.to_dict())
            if now - last_prune > 600:
                last_prune = now
                try:
                    await asyncio.to_thread(self.store.prune, now - self.retention_h * 3600)
                except Exception:
                    log.exception("retention prune failed")

    # ── read models ─────────────────────────────────────────────────────
    def counts(self) -> Dict[str, int]:
        c = {"live_stations": 0, "nominal": 0, "suspect": 0, "degraded": 0, "anomaly": 0,
             "stale": 0, "watch": 0, "weather_events": 0, "simulated": 0, "measured": 0}
        for h in list(self.processor.health.values()):
            c["live_stations"] += 1
            c[h.get("overall_status", "nominal")] = c.get(h.get("overall_status", "nominal"), 0) + 1
            c["stale"] += h.get("freshness") == "STALE"
            c["watch"] += bool(h.get("watch"))
            c["weather_events"] += h.get("interpretation") == "likely_weather_event"
            c["simulated" if h.get("simulated") else "measured"] += 1
        c["catalogue_total"] = len(self.stations._stations)
        return c

    def system_health(self, compact: bool = False) -> Dict[str, Any]:
        m = self.metrics.snapshot()
        db_ok = self.store.ping()
        last = self.metrics.last_processed_at
        detector_state = "RUNNING" if last and time.time() - last < 180 else (
            "IDLE" if self.state == "RUNNING" else self.state)
        comp = {
            "ingestion": {"status": "RUNNING" if self.state == "RUNNING" else self.state},
            "detector": {"status": detector_state, "engine_version": _engine_version(),
                         "errors_total": m["totals"]["errors"], "last_error": m["last_error"]},
            "database": {"status": "OK" if db_ok else "ERROR"},
            "stream": {"status": "OK", **self.stream.stats()},
            "events": self.broker.stats(),
        }
        out = {
            "runtime_state": self.state,
            "started_at": self.started_at,
            "components": comp,
            "metrics": m,
            "counts": self.counts(),
            "sources": [a.status.to_dict() for a in self.adapters],
            "active_faults": len(self.faults.list(active_only=True)),
        }
        if not compact:
            try:
                comp["database"].update(self.store.stats())
            except Exception as e:
                comp["database"]["status"] = f"ERROR: {e}"
        return out

    def network_snapshot(self) -> Dict[str, Any]:
        seq = self.broker.last_event_id  # read FIRST so no later event is missed
        feed_types = {ev.ANOMALY_DETECTED, ev.WEATHER_EVENT_DETECTED, ev.STATION_RECOVERED, ev.STATION_STALE,
                      ev.INCIDENT_CREATED, ev.INCIDENT_UPDATED, ev.FAULT_INJECTED, ev.FAULT_CLEARED,
                      ev.DATA_SOURCE_STATUS_CHANGED}
        return {
            "event_seq": seq,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "counts": self.counts(),
            "stations": [ObservationProcessor.station_event_payload(h) for h in list(self.processor.health.values())],
            "incident_counts": self.incidents.get_active_counts(source="LIVE_AWS,SIMULATED_FEED"),
            "recent_events": self.broker.recent(40, feed_types),
            "system": self.system_health(compact=True),
        }


def _engine_version() -> str:
    from app.anomaly.detector import ENGINE_VERSION
    return ENGINE_VERSION


_runtime: Optional[PipelineRuntime] = None


def get_runtime() -> Optional[PipelineRuntime]:
    return _runtime


def set_runtime(rt: Optional[PipelineRuntime]) -> None:
    global _runtime
    _runtime = rt
