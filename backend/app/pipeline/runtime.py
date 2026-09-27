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
  ATHER_SIM_INTERVAL_S        60 (600 on Render) simulated observation cadence per station;
                                  must fit processing capacity (see _emit backpressure)
  ATHER_SIM_MAX_STATIONS      -   limit simulated stations
  ATHER_SIM_WARMUP_CYCLES     8   simulated history cycles processed at start-up for the
                                  demo region, through the full engine
  ATHER_SIM_HISTORY_STATIONS  40  stations (nearest the demo station) warmed with history;
                                  every other station starts from one current observation
  ATHER_DEMO_STATION          -   baseline demo station (default: densest neighbourhood)
  ATHER_REFERENCE_ENABLED     1   keep the Open-Meteo reference cache warm
  ATHER_RETENTION_HOURS       24  time-series retention
  ATHER_INGEST_TOKEN          -   if set, required on POST /api/observations
"""
import asyncio
import logging
import os
import threading
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
        # The source cadence must fit what the engine can process. Layer 3
        # (ECOD + Isolation Forest) costs ~80 ms/observation locally and
        # ~0.7 s on a Render instance, so 296 stations every 60 s cannot be
        # sustained there; 10 minutes (a standard AWS reporting interval)
        # leaves ~3x headroom. Override with ATHER_SIM_INTERVAL_S.
        interval = sim_interval_s or float(ENV("ATHER_SIM_INTERVAL_S", "600" if ENV("RENDER") else "60"))
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
        # Station -> observation time of the newest observation RECEIVED from
        # it (set at ingest, before the queue). Communication health is judged
        # on this; a station whose data waits in ATHER's own queue is not silent.
        self._last_received: Dict[str, float] = {}
        self.sim_cycles_skipped = 0
        # One engine, one writer: live consumer, synchronous ingest and the
        # start-up warm-up all serialize on this lock.
        self._proc_lock = threading.Lock()
        self.warmup: Dict[str, Any] = {"state": "NOT_STARTED"}

    # ── helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def _reference_for(stn: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from app.weather.open_meteo import open_meteo_service
        from app.weather.open_meteo import with_pressure_provenance
        e = open_meteo_service.cache.get(f"{round(stn['latitude'], 3)}_{round(stn['longitude'], 3)}")
        return with_pressure_provenance(e["data"]) if e else None

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
                self._note_received(norm)
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

    def _note_received(self, norm: NormalizedObservation) -> None:
        t_obs = norm.observed_at.timestamp()
        if t_obs > self._last_received.get(norm.station_id, 0.0):
            self._last_received[norm.station_id] = t_obs

    def process_now(self, items: List[ObservationIn]) -> Dict[str, Any]:
        """Synchronous path (legacy /api/ingest): process immediately and
        return the DetectionResult. Same processor, same events."""
        norms, rejected = [], []
        for obs in items:
            self.metrics.received.add()
            try:
                norms.append(self.prepare(obs))
                self._note_received(norms[-1])
            except RejectedObservation as e:
                self.metrics.rejected.add()
                rejected.append(e.to_dict())
        outcomes = self._process(norms) if norms else []
        self._publish_outcomes(outcomes)
        return {"outcomes": outcomes, "rejected": rejected}

    def _process(self, batch: List[NormalizedObservation]) -> List[Dict[str, Any]]:
        with self._proc_lock:
            return self.processor.process_batch(batch)

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
        if not self.simulation.configured():
            self.simulation.live_ids = set()   # stations join the live feed once warmed
            self._tasks.append(asyncio.create_task(self._simulation_warmup(), name="sim-warmup"))
        for a in self.adapters:
            self._tasks.append(asyncio.create_task(a.run(self._emit), name=f"source:{a.name}"))
        self._tasks += [
            asyncio.create_task(self._staleness_monitor(), name="staleness"),
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
            asyncio.create_task(self._housekeeping(), name="housekeeping"),
        ]
        self.state = "RUNNING"

    async def _simulation_warmup(self) -> None:
        """Start-up of the SIMULATED network, cheap enough for a small instance:

        1. Baseline: every station outside the demo region gets one CURRENT
           simulated observation through the normal ingest path, so all of the
           network has real current telemetry within one processing pass. Its
           history then accumulates from ordinary live cycles, and layers that
           need history say "not evaluated (n/required)" until they have it.
        2. Demo region (ATHER_SIM_HISTORY_STATIONS nearest the demo station):
           ATHER_SIM_WARMUP_CYCLES cycles of recent simulated history, then it
           joins the live feed — so a fully evaluated station exists at once.

        Everything goes through the same generator and the same processor (all
        five layers, fusion, storage, incident policy); nothing is bypassed or
        invented. History observations carry their simulated observation time
        (received = observed); the feed stays labelled SIMULATED."""
        sim = self.simulation
        try:
            cycles = max(0, int(ENV("ATHER_SIM_WARMUP_CYCLES", "8")))
            n_hist = max(0, int(ENV("ATHER_SIM_HISTORY_STATIONS", "40")))
            demo = ENV("ATHER_DEMO_STATION") or await asyncio.to_thread(sim.demo_station_id)
            order = await asyncio.to_thread(sim.warmup_order, demo)
            region, rest = order[:n_hist], order[n_hist:]
            self.warmup = {"state": "RUNNING", "cycles": cycles, "cadence_s": sim.cadence_s,
                           "stations_total": len(order), "stations_ready": 0, "history_stations": len(region),
                           "observations_processed": 0, "demo_station_id": demo, "started_at": time.time()}
            if rest:
                sim.live_ids.update(rest)
                await self.ingest(sim.observations_at(float(int(time.time())), rest), block=True)
                self.warmup["stations_ready"] = len(sim.live_ids)
                sim.status.note = (f"Start-up: {len(rest)} simulated stations received a current baseline observation; "
                                   f"warming {len(region)} demo-region stations with {cycles} cycles of history.")
            for i in range(0, len(region), max(1, len(region))):
                ids = region[i:i + len(region)]
                t_end = float(int(time.time()))
                times = [t_end - k * sim.cadence_s for k in range(cycles, 0, -1)]
                while times:
                    t = times.pop(0)
                    if not times and time.time() - t >= sim.cadence_s:
                        # processing took longer than a cadence: keep the simulated
                        # series continuous up to the present before joining live
                        times.append(t + sim.cadence_s)
                    norms = []
                    for obs in sim.observations_at(t, [s for s in ids if self.processor._last_observed.get(s, 0.0) < t]):
                        try:
                            norm = self.prepare(obs, obs.observed_at)
                        except RejectedObservation:
                            self.metrics.rejected.add()
                            continue
                        self.metrics.received.add()
                        self._note_received(norm)
                        norms.append(norm)
                    if norms:
                        outcomes = await asyncio.to_thread(self._process, norms)
                        for o in outcomes:
                            for type_, data in o.get("events", []):
                                if type_.startswith("INCIDENT"):
                                    self.broker.publish(type_, data)
                        self.warmup["observations_processed"] += len(norms)
                sim.live_ids.update(ids)
                # Join the live feed now (normal ingest path, current time),
                # rather than waiting up to one cadence for the next cycle.
                await self.ingest(sim.observations_at(float(int(time.time())), ids), block=True)
                self.warmup["stations_ready"] = len(sim.live_ids)
                sim.status.note = (f"Start-up: all {len(sim.live_ids)} simulated stations live; "
                                   f"{len(ids)} demo-region stations warmed with {cycles} cycles of history.")
            self.warmup |= {"state": "COMPLETE", "completed_at": time.time()}
            sim.live_ids = None
            sim.status.note = (f"Simulated telemetry for real WeatherUnion AWS locations, one observation per "
                               f"station every {int(sim.cadence_s)} s. "
                               f"Not measured data.")
            log.info("simulation warm-up complete: %s", self.warmup)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # never block the live feed on a warm-up failure
            log.exception("simulation warm-up failed")
            self.warmup |= {"state": "FAILED", "error": repr(e)}
            sim.live_ids = None

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
        # Backpressure: never generate a new simulated cycle while the previous
        # one is still waiting to be processed, or the queue (and every
        # station's data age) grows without bound. The skip is visible: the
        # source goes DEGRADED with the reason, and no station-level
        # communication incidents are raised while the source is not ACTIVE.
        if items and items[0].adapter == self.simulation.name and self.stream.depth >= max(1, len(items) // 2):
            self.sim_cycles_skipped += 1
            if not self.simulation.status.note.startswith("Processing backlog"):
                self._sim_note = self.simulation.status.note
            self.simulation.status.note = (f"Processing backlog: {self.stream.depth} observations still queued, "
                                           f"cycle skipped ({self.sim_cycles_skipped} so far).")
            self.simulation._set_state("DEGRADED", self.simulation.status.note)
            return
        if items and items[0].adapter == self.simulation.name:
            # Keep the simulated cadence regular: a station that just joined the
            # live feed at the end of its warm-up is not reported again early.
            half = 0.5 * self.simulation.cadence_s
            items = [o for o in items
                     if o.observed_at.timestamp() - self._last_received.get(o.station_id, 0.0) >= half]
        if items and items[0].adapter == self.simulation.name and self.simulation.status.note.startswith("Processing backlog"):
            self.simulation.status.note = getattr(self, "_sim_note", "")
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
                outcomes = await asyncio.to_thread(self._process, batch)
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
        warming = self.simulation.live_ids
        for sid, h in list(self.processor.health.items()):
            if warming is not None and h.get("adapter") == self.simulation.name and sid not in warming:
                continue  # history still being warmed; not yet on the live feed
            cadence = h.get("cadence_s") or 300.0
            # Age of the newest observation RECEIVED from the station (not the
            # newest processed one): processing lag is a system condition,
            # reported separately, never a station communication fault.
            last_rx = max(self._last_received.get(sid, 0.0), h.get("last_observed_epoch") or 0.0) or now
            age = now - last_rx
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
                # Telemetry resumed: record it on the SAME incident (existing
                # lifecycle: the operator resolves it); a later outage updates
                # that incident while open instead of opening a duplicate.
                iid = self._outage_incidents.pop(sid)
                inc = self.incidents.record_event(iid, "TELEMETRY_RESTORED",
                                                  f"Telemetry resumed; newest observation {int(age)} s old.")
                if inc:
                    self.broker.publish(ev.INCIDENT_UPDATED, incident_event_payload(inc))

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
    def _backlogged(self) -> bool:
        qw = self.metrics.queue_wait.snapshot().get("p50_ms")
        return bool(self.stream.depth and qw and qw / 1000.0 > self.simulation.cadence_s)

    def _warming(self, sid: str, h: Dict[str, Any]) -> bool:
        ids = self.simulation.live_ids
        return ids is not None and h.get("adapter") == self.simulation.name and sid not in ids

    def counts(self) -> Dict[str, int]:
        c = {"live_stations": 0, "nominal": 0, "suspect": 0, "degraded": 0, "anomaly": 0,
             "stale": 0, "watch": 0, "weather_events": 0, "simulated": 0, "measured": 0}
        for sid, h in list(self.processor.health.items()):
            if self._warming(sid, h):
                continue  # history still being warmed; not on the live feed yet
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
            "stream": {"status": "BACKLOG" if self._backlogged() else "OK", **self.stream.stats(),
                       "sim_cycles_skipped": self.sim_cycles_skipped},
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
            "warmup": self.warmup | ({"pending_station_ids": [s for s in self.simulation.station_ids()
                                                               if s not in self.simulation.live_ids]}
                                     if self.warmup.get("state") == "RUNNING" and self.simulation.live_ids is not None else {}),
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
            "stations": [ObservationProcessor.station_event_payload(h) for sid, h in list(self.processor.health.items())
                         if not self._warming(sid, h)],

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
