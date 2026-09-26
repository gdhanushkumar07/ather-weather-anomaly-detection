"""
Replay (spec §15): re-run a window of observations through a FRESH engine
and play the verdicts back step by step.

  mode="synthetic"  the target station and its neighbours are generated on a
                    virtual clock (e.g. 2 h at 5-min cadence) with a fault
                    injected at a chosen minute — shows WHEN each layer
                    triggers, when fusion escalates and when an incident
                    would open.
  mode="history"    the station's own persisted observations (and its
                    neighbours') from the time-series store are replayed.

Isolation: a new AnomalyDetector, a shadow copy of the station registry, a
null store and a virtual incident book. Replay uses the SAME
ObservationProcessor code as production, but nothing it does is persisted
or counted as operational state.
"""
import asyncio
import copy
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.anomaly.detector import AnomalyDetector
from engine.layer4_spatial import haversine_distance_km

from . import events as ev
from .models import LAYER_KEYS, ObservationIn
from .normalize import normalize
from .processor import ObservationProcessor


class _NullStore:
    def write_batch(self, *a, **k): return 0
    def observation_exists(self, *a, **k): return False
    def latest_observations(self, *a, **k): return []
    def recent_station_observations(self, *a, **k): return []


class _ShadowStations:
    def __init__(self, real, ids: List[str]):
        self._real = real
        self._stations = {i: copy.deepcopy(real._stations[i]) for i in ids if i in real._stations}

    def _build_incident_snapshot(self, *a, **k):
        return self._real._build_incident_snapshot(*a, **k)


class _VirtualIncidents:
    def __init__(self):
        self.items: Dict[str, Dict[str, Any]] = {}

    def upsert_from_evaluation(self, snap: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if snap.get("status") not in ("WARNING", "ANOMALY"):
            return None
        key = f"{snap['station_id']}::{snap.get('parameter')}::{snap.get('root_cause')}"
        inc = self.items.get(key)
        if inc is None:
            inc = {
                "incident_id": f"REPLAY-INC-{uuid.uuid4().hex[:6].upper()}", "station_id": snap["station_id"],
                "station_name": snap.get("station_name"), "status": "NEW (virtual)",
                "severity": {"HIGH": "CRITICAL", "WARNING": "WARNING"}.get((snap.get("severity") or "").upper(), "WARNING"),
                "confidence": snap.get("confidence"), "parameter": snap.get("parameter"),
                "root_cause": snap.get("root_cause"), "source": "REPLAY", "observation_count": 1,
                "created_at": snap.get("observation_timestamp"), "context": snap.get("context"),
                "recommended_action": snap.get("recommended_action"),
            }
            self.items[key] = inc
        else:
            inc["observation_count"] += 1
        return dict(inc)


class ReplayService:
    MAX_WINDOW_MIN = 12 * 60

    def __init__(self, runtime):
        self.rt = runtime
        self.results: Dict[str, Dict[str, Any]] = {}

    def _neighbors(self, station_id: str, radius_km: float = 60.0, k: int = 10) -> List[str]:
        stn = self.rt.stations._stations[station_id]
        cands = []
        for s in self.rt.simulation.catalogue():
            if s["id"] == station_id:
                continue
            d = haversine_distance_km(stn["latitude"], stn["longitude"], s["latitude"], s["longitude"])
            if d <= radius_km:
                cands.append((d, s["id"]))
        cands.sort()
        return [sid for _, sid in cands[:k]]

    def _engine(self, ids: List[str]) -> ObservationProcessor:
        return ObservationProcessor(
            detector=AnomalyDetector(), station_service=_ShadowStations(self.rt.stations, ids),
            store=_NullStore(), incident_service=_VirtualIncidents(),
            reference_available=lambda: self.rt.reference.available,
        )

    # ── batch builders ──────────────────────────────────────────────────
    def _synthetic_batches(self, target: str, ids: List[str], p: Dict[str, Any]):
        from app.sources.simulation import FaultBook, SyntheticNetwork
        net = SyntheticNetwork.from_station_dicts(
            [self.rt.stations._stations[i] for i in ids], self.rt._reference_for)
        faults = FaultBook()
        step_s = p["interval_minutes"] * 60.0
        n_steps = int(p["window_minutes"] // p["interval_minutes"]) + 1
        start = time.time() - p["window_minutes"] * 60.0
        onset = start + p["fault_start_minute"] * 60.0
        if p.get("fault_type"):
            s = net.stations[target]
            faults.inject(target, p["fault_type"], p.get("parameter"), p.get("severity", "medium"),
                          duration_s=p["fault_duration_minutes"] * 60.0, started_at=onset,
                          station_latlon=(s.lat, s.lon))
        for k in range(n_steps):
            t = start + k * step_s
            obs_at = datetime.fromtimestamp(t, tz=timezone.utc)
            batch = []
            for sid, (values, metas) in net.generate(t, faults).items():
                if values is None:
                    continue
                o = ObservationIn(station_id=sid, observed_at=obs_at, source="SIMULATED_AWS", adapter="replay",
                                  meta={"injected_fault": metas[0]} if metas else {}, **values)
                batch.append(normalize(o, received_at=obs_at + timedelta(seconds=2), cadence_s=step_s))
            end = onset + p["fault_duration_minutes"] * 60.0
            yield t, batch, (onset <= t < end if p.get("fault_type") else False)

    def _history_batches(self, target: str, ids: List[str], p: Dict[str, Any]):
        until = time.time()
        since = until - p["window_minutes"] * 60.0
        rows = self.rt.store.observations_between(ids, since, until)
        by_t: Dict[float, list] = {}
        for r in rows:
            by_t.setdefault(r["observed_at"], []).append(r)
        for t in sorted(by_t):
            batch = []
            for r in by_t[t]:
                values = {k: r.get(k) for k in ("temperature", "humidity", "pressure", "wind_speed",
                                                  "wind_direction", "rainfall", "dew_point")}
                o = ObservationIn(station_id=r["station_id"], observed_at=datetime.fromtimestamp(t, tz=timezone.utc),
                                  source=r["source"], adapter="replay", **values)
                batch.append(normalize(o, received_at=datetime.fromtimestamp(t + 2, tz=timezone.utc),
                                       cadence_s=self.rt.simulation.cadence_s))
            yield t, batch, False

    # ── run ─────────────────────────────────────────────────────────────
    def compute(self, replay_id: str, p: Dict[str, Any]) -> Dict[str, Any]:
        target = p["station_id"]
        ids = [target] + self._neighbors(target)
        proc = self._engine(ids)
        gen = self._synthetic_batches(target, ids, p) if p["mode"] == "synthetic" else self._history_batches(target, ids, p)
        steps, markers = [], []
        seen = set()

        def mark(key: str, t: float, text: str):
            if key not in seen:
                seen.add(key)
                markers.append({"key": key, "at": datetime.fromtimestamp(t, tz=timezone.utc).isoformat(), "text": text})

        for t, batch, fault_active in gen:
            if fault_active:
                mark("fault_onset", t, f"Injected fault begins: {p.get('fault_type')} ({p.get('parameter') or 'station'}, {p.get('severity')})")
            outcome = next((o for o in proc.process_batch(batch)
                            if o.get("detection") and o["detection"]["station_id"] == target), None)
            if not outcome:
                steps.append({"t": datetime.fromtimestamp(t, tz=timezone.utc).isoformat(), "missing": True,
                              "fault_active": fault_active})
                if fault_active:
                    mark("silent", t, "Station transmitted nothing (dropout)")
                continue
            d = outcome["detection"]
            for code, _ in LAYER_KEYS:
                if d["layer_results"][code]["triggered"]:
                    mark(f"layer_{code}", t, f"{code} triggers — {d['layer_results'][code]['reason']}")
            if d["overall_status"] == "suspect":
                mark("suspect", t, f"Fusion: SUSPECT ({round(d['confidence'] * 100)}% confidence)")
            if d["overall_status"] == "anomaly":
                mark("anomaly", t, f"Fusion: ANOMALY ({round(d['confidence'] * 100)}% confidence) — {d['diagnosis']['rca_label']}")
            if d["interpretation"] == "likely_weather_event":
                mark("weather", t, "Neighbours corroborate the change — classified as a weather event, no incident")
            if outcome.get("incident"):
                mark("incident", t, f"Incident would open: {outcome['incident']['root_cause']} ({outcome['incident']['severity']})")
            steps.append({
                "t": d["observation_timestamp"],
                "fault_active": fault_active,
                "values": d["observed_values"],
                "overall_status": d["overall_status"],
                "engine_status": d["engine_status"],
                "interpretation": d["interpretation"],
                "confidence": d["confidence"],
                "triggered_layers": d["triggered_layers"],
                "layer_scores": {c: d["layer_results"][c]["score"] for c, _ in LAYER_KEYS},
                "root_cause": d["diagnosis"]["root_cause"],
                "summary": d["summary"],
                "incident": outcome.get("incident", {}) and outcome["incident"].get("incident_id"),
            })
        onset = next((m for m in markers if m["key"] == "fault_onset"), None)
        first_alarm = next((m for m in markers if m["key"] in ("suspect", "anomaly", "weather")), None)
        ttd = None
        if onset and first_alarm:
            ttd = (datetime.fromisoformat(first_alarm["at"]) - datetime.fromisoformat(onset["at"])).total_seconds() / 60.0
        return {
            "replay_id": replay_id, "params": p, "station_id": target, "neighbor_ids": ids[1:],
            "steps": steps, "markers": markers, "time_to_detection_min": ttd,
            "isolation": "Fresh engine instance; nothing persisted; incidents are virtual.",
            "simulated": p["mode"] == "synthetic",
        }

    def validate(self, body: Dict[str, Any]) -> Dict[str, Any]:
        from app.sources.simulation import FAULT_TYPES
        sid = body.get("station_id")
        if not sid or sid not in self.rt.stations._stations:
            raise ValueError("station_id must be a catalogue station")
        mode = body.get("mode", "synthetic")
        if mode not in ("synthetic", "history"):
            raise ValueError("mode must be 'synthetic' or 'history'")
        window = float(body.get("window_minutes", 120))
        interval = float(body.get("interval_minutes", 5))
        if not (10 <= window <= self.MAX_WINDOW_MIN) or not (1 <= interval <= 60):
            raise ValueError("window_minutes must be 10–720 and interval_minutes 1–60")
        ft = body.get("fault_type")
        if ft and ft not in FAULT_TYPES:
            raise ValueError(f"unknown fault_type {ft}")
        start = float(body.get("fault_start_minute", min(30.0, window / 4)))
        return {
            "mode": mode, "station_id": sid, "window_minutes": window, "interval_minutes": interval,
            "fault_type": ft if mode == "synthetic" else None, "parameter": body.get("parameter"),
            "severity": body.get("severity", "medium"), "fault_start_minute": start,
            "fault_duration_minutes": float(body.get("fault_duration_minutes", window - start)),
            "playback_ms": max(50, min(2000, int(body.get("playback_ms", 350)))),
        }

    async def run(self, body: Dict[str, Any]) -> Dict[str, Any]:
        p = self.validate(body)
        replay_id = "rpl_" + uuid.uuid4().hex[:10]
        result = await asyncio.to_thread(self.compute, replay_id, p)
        self.results[replay_id] = result
        if len(self.results) > 20:
            self.results.pop(next(iter(self.results)))
        asyncio.create_task(self._playback(result))
        return {"replay_id": replay_id, "steps": len(result["steps"]), "playback_ms": p["playback_ms"]}

    async def _playback(self, result: Dict[str, Any]) -> None:
        delay = result["params"]["playback_ms"] / 1000.0
        markers_by_t: Dict[str, list] = {}
        for m in result["markers"]:
            markers_by_t.setdefault(m["at"], []).append(m)
        for i, step in enumerate(result["steps"]):
            self.rt.broker.publish(ev.REPLAY_STEP, {
                "replay_id": result["replay_id"], "index": i, "total": len(result["steps"]),
                "step": step, "markers": markers_by_t.get(step["t"], []),
            })
            await asyncio.sleep(delay)
        self.rt.broker.publish(ev.REPLAY_COMPLETED, {
            "replay_id": result["replay_id"], "markers": result["markers"],
            "time_to_detection_min": result["time_to_detection_min"],
        })
