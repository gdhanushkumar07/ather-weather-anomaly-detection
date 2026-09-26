"""
ObservationProcessor — runs every stream observation through the existing
ATHER engine and turns the verdict into persisted, published state.

Per micro-batch:
  1. de-duplicate (observation_id) and divert out-of-order observations
     (archived as LATE, never fed to the stateful temporal/drift layers)
  2. place every accepted reading in the spatial pool FIRST, so Layer 4
     compares stations observed at the same instant (a regional front hitting
     ten stations in one batch is corroborated, not ten isolated spikes)
  3. per observation: 5 layers + conformal fusion (AnomalyDetector),
     DetectionResult, station health, incident create/update
  4. persist raw observations + detections in one transaction
  5. return events for the broker

Failure isolation: an exception while evaluating one observation is logged,
counted and published as PROCESSING_ERROR; its raw observation is still
archived and the rest of the batch proceeds.

Synchronous by design: the runtime calls process_batch on a worker thread.
Tests call it directly.
"""
import logging
import math
import time
import traceback
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from engine.layer4_spatial import haversine_distance_km
from schema import AWSReading, classify_freshness

from . import events as ev
from .detection import build_detection_result, compact_for_event
from .metrics import PipelineMetrics
from .models import NormalizedObservation
from .reference import compare as reference_compare
from .store import TimeSeriesStore

log = logging.getLogger("ather.pipeline")

SIMULATED_SOURCE = "SIMULATED_AWS"
ABNORMAL = ("suspect", "anomaly")


def source_class(source: str) -> str:
    """Stations are only compared with neighbours of the same class: a real
    sensor is never 'corroborated' by simulated data, or vice versa."""
    return "SIMULATED" if source == SIMULATED_SOURCE else "MEASURED"


def incident_source_for(source: str) -> str:
    return "SIMULATED_FEED" if source == SIMULATED_SOURCE else "LIVE_AWS"


def _iso(epoch: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat() if epoch else None


class SpatialPool:
    """Latest reading per live-fed station, bucketed on a coarse lat/lon grid
    so neighbour search is O(stations in 9 cells), not O(network)."""

    CELL_DEG = 2.5

    def __init__(self, radius_km: float = 250.0):
        self.radius_km = radius_km
        self._cells: Dict[Tuple[int, int], Dict[str, Tuple[AWSReading, str, float]]] = {}
        self._where: Dict[str, Tuple[int, int]] = {}

    def _cell(self, lat: float, lon: float) -> Tuple[int, int]:
        return (int(math.floor(lat / self.CELL_DEG)), int(math.floor(lon / self.CELL_DEG)))

    def put(self, reading: AWSReading, cls: str, observed_epoch: float) -> None:
        cell = self._cell(reading.lat, reading.lon)
        old = self._where.get(reading.station_id)
        if old is not None and old != cell:
            self._cells.get(old, {}).pop(reading.station_id, None)
        self._cells.setdefault(cell, {})[reading.station_id] = (reading, cls, observed_epoch)
        self._where[reading.station_id] = cell

    def neighbors(
        self, reading: AWSReading, cls: str, at_epoch: float, max_age_s: float, k: int = 8
    ) -> List[Tuple[AWSReading, float, float]]:
        ci, cj = self._cell(reading.lat, reading.lon)
        found = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for sid, (r, c, t) in list(self._cells.get((ci + di, cj + dj), {}).items()):
                    if sid == reading.station_id or c != cls:
                        continue
                    if abs(at_epoch - t) > max_age_s:
                        continue
                    d = haversine_distance_km(reading.lat, reading.lon, r.lat, r.lon)
                    if d <= self.radius_km:
                        found.append((r, d, t))
        found.sort(key=lambda x: x[1])
        return found[:k]


class ObservationProcessor:
    # After a sensor-fault verdict, weather claims are withheld for this long.
    POST_FAULT_QUARANTINE_S = 3600.0

    def __init__(
        self,
        *,
        detector,
        station_service,
        store: TimeSeriesStore,
        incident_service,
        metrics: Optional[PipelineMetrics] = None,
        reference_available: Callable[[], bool] = lambda: True,
        incident_debounce: int = 2,
    ):
        self.detector = detector
        self.stations = station_service
        self.store = store
        self.incidents = incident_service
        self.metrics = metrics or PipelineMetrics()
        self.reference_available = reference_available
        self.incident_debounce = incident_debounce
        self.run_id = "run_" + uuid.uuid4().hex[:10]

        self.pool = SpatialPool()
        self.health: Dict[str, Dict[str, Any]] = {}
        self._last_observed: Dict[str, float] = {}
        self._station_source: Dict[str, str] = {}
        self._recent_ids: "OrderedDict[str, None]" = OrderedDict()
        self._incident_severity: Dict[str, str] = {}

    # ── public ──────────────────────────────────────────────────────────
    def process(self, obs: NormalizedObservation) -> Dict[str, Any]:
        return self.process_batch([obs])[0]

    def process_batch(self, batch: List[NormalizedObservation]) -> List[Dict[str, Any]]:
        outcomes: List[Dict[str, Any]] = []
        obs_rows: List[Dict[str, Any]] = []
        det_rows: List[Dict[str, Any]] = []
        accepted: List[Tuple[NormalizedObservation, Dict[str, Any], AWSReading]] = []
        dequeued = time.monotonic()

        for obs in batch:
            if obs.enqueued_at is not None:
                self.metrics.queue_wait.add((dequeued - obs.enqueued_at) * 1000.0)
            status = self._admit(obs)
            if status == "duplicate":
                self.metrics.duplicates.add()
                outcomes.append({"observation_id": obs.observation_id, "status": "duplicate", "events": []})
                continue
            stn = self.stations._stations.get(obs.station_id)
            if status == "late" or stn is None:
                obs_rows.append(self._obs_row(obs, late=True))
                self.metrics.late.add()
                outcomes.append({
                    "observation_id": obs.observation_id,
                    "status": "late" if stn is not None else "unknown_station",
                    "events": [],
                })
                continue
            reading = self._to_reading(obs, stn)
            accepted.append((obs, stn, reading))
            obs_rows.append(self._obs_row(obs))

        # Synchronous spatial snapshot (see module docstring, step 2).
        for obs, stn, reading in accepted:
            self.pool.put(reading, source_class(obs.source), obs.observed_at.timestamp())

        for obs, stn, reading in accepted:
            try:
                outcome, det_row = self._evaluate(obs, stn, reading)
                det_rows.append(det_row)
                outcomes.append(outcome)
            except Exception as e:  # detector failure isolation
                self.metrics.errors.add()
                self.metrics.last_error = f"{obs.station_id}: {e!r}"
                log.error("processing failed for %s: %s", obs.observation_id, traceback.format_exc())
                outcomes.append({
                    "observation_id": obs.observation_id,
                    "status": "error",
                    "error": str(e),
                    "events": [(ev.PROCESSING_ERROR, {"station_id": obs.station_id, "observation_id": obs.observation_id, "error": str(e)})],
                })

        if obs_rows or det_rows:
            self.store.write_batch(obs_rows, det_rows)
        return outcomes

    def seed_health_from_store(self, lookback_s: float = 6 * 3600) -> int:
        """After a restart, restore 'last observed' per station so staleness
        and out-of-order checks keep working. Engine L2/L5 state is warmed
        separately by warm_up()."""
        n = 0
        for row in self.store.latest_observations(since=time.time() - lookback_s):
            self._last_observed[row["station_id"]] = row["observed_at"]
            n += 1
        return n

    def warm_up(self, station_ids: List[str], per_station: int = 20) -> int:
        """Replays each station's most recent persisted observations through
        the detector (no persistence, no events, no incidents) so temporal
        and drift layers resume with context instead of 'insufficient data'."""
        n = 0
        for sid in station_ids:
            stn = self.stations._stations.get(sid)
            if not stn:
                continue
            for row in self.store.recent_station_observations(sid, per_station):
                values = {k: row.get(k) for k in ("temperature", "humidity", "pressure", "wind_speed", "wind_direction", "rainfall", "dew_point")}
                observed = datetime.fromtimestamp(row["observed_at"], tz=timezone.utc)
                obs = NormalizedObservation(
                    observation_id=row["observation_id"], station_id=sid, observed_at=observed,
                    received_at=observed, source=row["source"], adapter="warm-up", values=values,
                )
                reading = self._to_reading(obs, stn)
                self.pool.put(reading, source_class(row["source"]), row["observed_at"])
                self.detector.evaluate_reading(reading, neighbors=[], station_data=stn)
                self._last_observed[sid] = row["observed_at"]
                self._station_source[sid] = row["source"]
                n += 1
        return n

    # ── internals ───────────────────────────────────────────────────────
    def _admit(self, obs: NormalizedObservation) -> str:
        oid = obs.observation_id
        if oid in self._recent_ids:
            return "duplicate"
        t = obs.observed_at.timestamp()
        last = self._last_observed.get(obs.station_id)
        if last is not None and t <= last:
            # Same instant with a different id (e.g. another source) or older:
            # a duplicate if we already hold it, else a late arrival.
            return "duplicate" if self.store.observation_exists(oid) else "late"
        if last is None and self.store.observation_exists(oid):
            return "duplicate"
        self._recent_ids[oid] = None
        if len(self._recent_ids) > 100_000:
            self._recent_ids.popitem(last=False)
        self._last_observed[obs.station_id] = t
        return "accepted"

    def _to_reading(self, obs: NormalizedObservation, stn: Dict[str, Any]) -> AWSReading:
        v = obs.values
        # Readings from a new source must not be compared with the previous
        # source's history by the stateful layers.
        prev_src = self._station_source.get(obs.station_id) or stn.get("dataSource")
        prev_src = getattr(prev_src, "value", prev_src)
        if prev_src and prev_src != obs.source:
            self.detector.reset_station_state(obs.station_id)
        self._station_source[obs.station_id] = obs.source
        # Freshness of THIS observation = how late it was when it reached us.
        # A station that stops reporting is detected by the runtime's
        # staleness monitor, not here.
        freshness = classify_freshness(
            obs.observed_at, obs.received_at, cadence_minutes=3 * obs.cadence_s / 60.0
        )
        return AWSReading(
            station_id=obs.station_id,
            timestamp=obs.observed_at,          # L2 clock = observation time (replay-safe)
            temperature_c=v.get("temperature"),
            pressure_hpa=v.get("pressure"),
            humidity_pct=v.get("humidity"),
            dew_point_c=v.get("dew_point"),
            wind_speed_kmh=v.get("wind_speed"),
            lat=float(stn.get("latitude") or 0.0),
            lon=float(stn.get("longitude") or 0.0),
            elevation_m=float(stn.get("elevation") or 0.0),
            source=obs.source,
            observation_timestamp=obs.observed_at,
            received_timestamp=obs.received_at,
            freshness=freshness,
        )

    def _obs_row(self, obs: NormalizedObservation, late: bool = False) -> Dict[str, Any]:
        return {
            "observation_id": obs.observation_id,
            "station_id": obs.station_id,
            "observed_at": obs.observed_at.timestamp(),
            "received_at": obs.received_at.timestamp(),
            "source": obs.source,
            "adapter": obs.adapter,
            "values": obs.values,
            "flags": obs.flags,
            "late": late,
        }

    def _baseline(self, station_id: str, consensus: Dict[str, Any]) -> Dict[str, Any]:
        """Expected values: the station's own recent history (L2 buffer
        median) and the neighbour consensus (L4), side by side."""
        out: Dict[str, Any] = {}
        buf = self.detector.layer2.buffers.get(station_id)
        pairs = (("temperature", "history_temp", "temperature_c"),
                 ("pressure", "history_press", "pressure_hpa"),
                 ("humidity", "history_rh", "humidity_pct"))
        for name, attr, ch in pairs:
            hist = list(getattr(buf, attr, []))[:-1] if buf else []
            spatial = (consensus.get("channel_results") or {}).get(ch, {})
            out[name] = {
                "rolling_median": round(float(np.median(hist[-36:])), 2) if len(hist) >= 3 else None,
                "history_points": len(hist),
                "spatial_consensus": spatial.get("consensus_value"),
                "spatial_deviation": spatial.get("deviation"),
                "spatial_z": spatial.get("z_score"),
            }
        return out

    def _evaluate(self, obs: NormalizedObservation, stn: Dict[str, Any], reading: AWSReading):
        t0 = time.perf_counter()
        sid = obs.station_id
        observed_epoch = obs.observed_at.timestamp()
        cls = source_class(obs.source)
        max_age = max(3 * obs.cadence_s, 900.0)
        found = self.pool.neighbors(reading, cls, observed_epoch, max_age)
        alert = self.detector.evaluate_reading(reading, neighbors=[r for r, _, _ in found], station_data=stn)

        freshness = str(getattr(reading.freshness, "value", reading.freshness))
        self._update_station_registry(stn, obs, alert, freshness)
        self.detector.update_spatial_pool([reading])

        neighbor_rows = []
        for r, dist, t in found:
            h = self.health.get(r.station_id, {})
            neighbor_rows.append({
                "station_id": r.station_id,
                "name": (self.stations._stations.get(r.station_id) or {}).get("name"),
                "distance_km": round(dist, 1),
                "temperature": r.temperature_c,
                "humidity": r.humidity_pct,
                "pressure": r.pressure_hpa,
                "observed_at": _iso(t),
                "overall_status": h.get("overall_status"),
            })

        spatial_detail = (alert.layer_details or {}).get("spatial", {})
        prev = self.health.get(sid) or {}
        warn_streak = prev.get("warning_streak", 0) + 1 if alert.status == "WARNING" else 0
        det = build_detection_result(
            alert=alert,
            reading=reading,
            obs=obs,
            freshness=freshness,
            reference_comparison=reference_compare(
                obs.values, reading.lat, reading.lon, obs.source, self.reference_available()
            ),
            neighbors=neighbor_rows,
            baseline=self._baseline(sid, spatial_detail),
            processing_started=t0,
            run_id=self.run_id,
            hold_single_warning=warn_streak < 2,
        )

        prev_status = prev.get("overall_status")
        prev_interp = prev.get("interpretation")
        last_fault = prev.get("last_sensor_fault_epoch")
        in_quarantine = last_fault is not None and 0 <= observed_epoch - last_fault <= self.POST_FAULT_QUARANTINE_S
        if (det["interpretation"] == "likely_weather_event" and in_quarantine
                and prev_interp != "likely_sensor_fault"):
            # Post-fault settling: the station's temporal baseline (L2 window)
            # still contains the faulty readings, so a "change" relative to it
            # is not evidence of weather.
            det["interpretation"] = "uncertain"
            det["summary"] = ("Post-fault settling period — the temporal baseline still contains faulty readings, "
                              "so a weather classification is withheld. " + det["summary"])
        if det["interpretation"] == "likely_weather_event" and prev_interp == "likely_sensor_fault":
            # The classifier sees one observation; the pipeline sees the
            # station's history. An abrupt move back INTO agreement with the
            # neighbours right after a sensor-fault verdict is a sensor
            # recovery/reset, not weather — keep it suspect and say so.
            det["interpretation"] = "uncertain"
            det["overall_status"] = "suspect"
            det["summary"] = ("SUSPECT — abrupt return towards neighbour consensus immediately after a sensor-fault "
                              "verdict: likely sensor recovery or reset, not a weather event. " + det["summary"])
        consecutive = prev.get("consecutive_abnormal", 0) + 1 if det["overall_status"] in ABNORMAL else 0

        events: List[Tuple[str, Dict[str, Any]]] = []
        incident_events: List[Tuple[str, Dict[str, Any]]] = []
        incident = self._maybe_incident(stn, obs, det, consecutive, alert)
        if incident:
            det["incident_id"] = incident["incident_id"]
            incident_events = self._incident_events(incident)
        active_incident = incident["incident_id"] if incident else (
            prev.get("active_incident_id") if det["overall_status"] in ABNORMAL else None
        )

        now = time.time()
        health = {
            "station_id": sid,
            "name": stn.get("name"),
            "latitude": stn.get("latitude"),
            "longitude": stn.get("longitude"),
            "region": stn.get("region"),
            "source": obs.source,
            "adapter": obs.adapter,
            "simulated": obs.source == SIMULATED_SOURCE,
            "overall_status": det["overall_status"],
            "engine_status": det["engine_status"],
            "interpretation": det["interpretation"],
            "confidence": det["confidence"],
            "severity": det["severity"],
            "root_cause": det["diagnosis"]["root_cause"],
            "rca_label": det["diagnosis"]["rca_label"],
            "triggered_layers": det["triggered_layers"],
            "summary": det["summary"],
            "values": obs.values,
            "last_observed_at": obs.observed_at.isoformat(),
            "last_observed_epoch": observed_epoch,
            "last_processed_at": _iso(now),
            "freshness": freshness,
            "cadence_s": obs.cadence_s,
            "consecutive_abnormal": consecutive,
            "last_sensor_fault_epoch": observed_epoch if det["interpretation"] == "likely_sensor_fault" else last_fault,
            "warning_streak": warn_streak,
            "watch": det.get("watch", False),
            "active_incident_id": active_incident,
            "detection_id": det["detection_id"],
            "injected_fault": obs.meta.get("injected_fault"),
            "sensor_health_index": det["sensor_health_index"],
        }
        self.health[sid] = health

        compact = compact_for_event(det)
        # Order matters for the live feed: state, then detection, then incident.
        events.append((ev.STATION_UPDATED, self.station_event_payload(health)))
        new_status = det["overall_status"]
        if det["interpretation"] == "likely_weather_event" and prev_interp != "likely_weather_event":
            events.append((ev.WEATHER_EVENT_DETECTED, compact))
        elif new_status in ABNORMAL and (prev_status not in ABNORMAL or (prev_status == "suspect" and new_status == "anomaly")):
            # The live feed reports diagnosed faults and anomalies; a persistent
            # but undiagnosed statistical warning only recolours the station.
            if new_status == "anomaly" or det.get("diagnosed_fault"):
                events.append((ev.ANOMALY_DETECTED, compact | {"escalation": prev_status == "suspect"}))
                self.metrics.anomalies.add()
        elif new_status not in ABNORMAL and prev_status in ABNORMAL:
            events.append((ev.STATION_RECOVERED, compact))
        events.extend(incident_events)

        processing_ms = (time.perf_counter() - t0) * 1000.0
        self.metrics.processing.add(processing_ms)
        self.metrics.ingestion_latency.add((obs.received_at - obs.observed_at).total_seconds() * 1000.0)
        self.metrics.processed.add()
        self.metrics.last_processed_at = now

        det_row = {
            "detection_id": det["detection_id"],
            "observation_id": obs.observation_id,
            "station_id": sid,
            "observed_at": observed_epoch,
            "processed_at": now,
            "overall_status": det["overall_status"],
            "engine_status": det["engine_status"],
            "confidence": det["confidence"],
            "anomaly_score": det["anomaly_score"],
            "severity": det["severity"],
            "root_cause": det["diagnosis"]["root_cause"],
            "triggered_layers": det["triggered_layers"],
            "layer_scores": {c: det["layer_results"][c]["score"] for c in ("L1", "L2", "L3", "L4", "L5")},
            "incident_id": det.get("incident_id"),
            "processing_ms": round(processing_ms, 3),
            "detail": det,
        }
        outcome = {
            "observation_id": obs.observation_id,
            "status": "processed",
            "detection": det,
            "incident": incident,
            "events": events,
            "observed_epoch": observed_epoch,
        }
        return outcome, det_row

    def _update_station_registry(self, stn: Dict[str, Any], obs: NormalizedObservation, alert, freshness: str) -> None:
        v = obs.values
        stn.update({
            "temperature": v.get("temperature"),
            "humidity": v.get("humidity"),
            "pressure": v.get("pressure"),
            "windSpeed": v.get("wind_speed"),
            "windDirectionDeg": v.get("wind_direction"),
            "rainfall": v.get("rainfall"),
            "timestamp": obs.observed_at.isoformat(),
            "observationTimestamp": obs.observed_at.isoformat(),
            "dataSource": obs.source,
            "freshness": freshness,
            "sourceCadenceMinutes": obs.cadence_s / 60.0,
            "awsTelemetryStatus": "SIMULATED_FEED" if obs.source == SIMULATED_SOURCE else "TELEMETRY_AVAILABLE",
            "status": alert.status,
            "anomaly": alert.to_legacy_dict(),
            "liveFeed": True,
        })
        if v.get("wind_direction") is not None:
            from app.weather.open_meteo import degrees_to_cardinal
            stn["windDirection"] = degrees_to_cardinal(v["wind_direction"])

    def _maybe_incident(self, stn, obs: NormalizedObservation, det: Dict[str, Any], consecutive: int, alert=None) -> Optional[Dict[str, Any]]:
        """ANOMALY opens/updates an incident immediately; SUSPECT only once it
        persists for `incident_debounce` consecutive observations (one noisy
        reading is not an operational event). Weather-classified detections
        never open a maintenance incident."""
        if det["interpretation"] == "likely_weather_event":
            return None
        status = det["overall_status"]
        persistent_fault = (status == "suspect" and consecutive >= self.incident_debounce
                            and det.get("diagnosed_fault"))
        if not (status == "anomaly" or persistent_fault):
            return None
        try:
            snapshot = self.stations._build_incident_snapshot(stn, source=incident_source_for(obs.source), alert=alert)
            if not snapshot:
                return None
            snapshot["context"] = {
                "detection_id": det["detection_id"],
                "observation_id": obs.observation_id,
                "first_observation_at": obs.observed_at.isoformat(),
                "triggered_layers": det["triggered_layers"],
                "interpretation": det["interpretation"],
                "rca_category": det["diagnosis"]["rca_category"],
                "rca_label": det["diagnosis"]["rca_label"],
                "action_category": det["recommended_action"]["category"],
                "action_label": det["recommended_action"]["label"],
                "summary": det["summary"],
                "observed_values": obs.values,
                "expected": det["expected"],
                "neighbors": det["neighbors"][:8],
                "reference_comparison": det["reference_comparison"],
                "layer_results": det["layer_results"],
                "provenance": {
                    "data_source": obs.source,
                    "simulated": obs.source == SIMULATED_SOURCE,
                    "detector_version": det["provenance"]["detector_version"],
                    "pipeline_version": det["provenance"]["pipeline_version"],
                    "injected_fault": obs.meta.get("injected_fault"),
                },
            }
            inc = self.incidents.upsert_from_evaluation(snapshot)
        except Exception as e:
            # Incident persistence must never break detection.
            log.error("incident sync failed for %s: %s", obs.station_id, e)
            return None
        return inc

    def _incident_events(self, inc: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
        payload = incident_event_payload(inc)
        iid = inc["incident_id"]
        prev_sev = self._incident_severity.get(iid)
        self._incident_severity[iid] = inc.get("severity")
        if inc.get("observation_count", 1) == 1 and prev_sev is None:
            self.metrics.incidents_created.add()
            return [(ev.INCIDENT_CREATED, payload)]
        if prev_sev != inc.get("severity") or inc.get("observation_count", 0) % 5 == 0:
            return [(ev.INCIDENT_UPDATED, payload)]
        return []

    @staticmethod
    def station_event_payload(h: Dict[str, Any]) -> Dict[str, Any]:
        keys = ("station_id", "name", "latitude", "longitude", "source", "simulated", "overall_status",
                "engine_status", "interpretation", "confidence", "severity", "root_cause", "rca_label",
                "triggered_layers", "values", "last_observed_at", "last_processed_at", "freshness",
                "active_incident_id", "detection_id", "summary", "injected_fault", "watch")
        return {k: h.get(k) for k in keys}


def incident_event_payload(inc: Dict[str, Any]) -> Dict[str, Any]:
    ctx = inc.get("context") or {}
    return {
        "incident_id": inc["incident_id"],
        "station_id": inc["station_id"],
        "station_name": inc.get("station_name"),
        "status": inc.get("status"),
        "severity": inc.get("severity"),
        "confidence": inc.get("confidence"),
        "parameter": inc.get("parameter"),
        "root_cause": inc.get("root_cause"),
        "rca_label": ctx.get("rca_label"),
        "source": inc.get("source"),
        "observation_count": inc.get("observation_count"),
        "created_at": inc.get("created_at"),
        "updated_at": inc.get("updated_at"),
    }
