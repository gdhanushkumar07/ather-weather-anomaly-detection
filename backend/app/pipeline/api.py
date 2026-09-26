"""
Real-time API surface.

  GET  /api/stream                      SSE: STATION_UPDATED, ANOMALY_DETECTED, INCIDENT_*, ...
  GET  /api/network/state               initial dashboard snapshot (+ event_seq to resume from)
  GET  /api/system/health               components, sources, latency, throughput
  GET  /api/sources                     source adapter status
  POST /api/observations                push ingestion (validated, queued, 202)
  GET  /api/stations/{id}/live          latest DetectionResult + health + reference
  GET  /api/stations/{id}/timeseries    persisted observations (downsampled window)
  GET  /api/stations/{id}/detections    detection history (status / layer timeline)
  GET  /api/stations/{id}/spatial       spatial event analysis around a station
  GET  /api/detections/{id}             one full DetectionResult (provenance)
  GET  /api/lab/fault-types             fault catalogue
  GET  /api/lab/faults                  injected faults
  POST /api/lab/faults                  inject a fault into the live simulated feed
  DELETE /api/lab/faults/{id}           cancel a fault
  POST /api/replay                      start a replay; steps stream as REPLAY_STEP
  GET  /api/replay/{id}                 full replay result

The browser never polls stations: it loads /api/network/state once, then
applies SSE events. History is fetched per station, on demand, by window.
"""
import asyncio
import hmac
import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from engine.layer4_spatial import haversine_distance_km

from . import events as ev
from .models import ObservationIn
from .normalize import dew_point_c
from .runtime import get_runtime

router = APIRouter(prefix="/api")


def _rt():
    rt = get_runtime()
    if rt is None:
        raise HTTPException(status_code=503, detail="Real-time pipeline is not running (ATHER_PIPELINE_ENABLED=0).")
    return rt


def _station(rt, station_id: str) -> Dict[str, Any]:
    stn = rt.stations._stations.get(station_id)
    if not stn:
        raise HTTPException(status_code=404, detail=f"Station '{station_id}' not found")
    return stn


def _json(data: Any) -> str:
    return json.dumps(data, default=str, separators=(",", ":"))


def legacy_payload_to_observation(stn_id: str, norm: Dict[str, Any], raw: Dict[str, Any]) -> ObservationIn:
    """Maps the multi-protocol /api/ingest payload (WeeWX / WOW-BE / native)
    onto the pipeline contract. Pushed telemetry is treated as in-situ."""
    observed = raw.get("observed_at") or raw.get("dateTime") or raw.get("timestamp_utc")
    try:
        if isinstance(observed, (int, float)):
            observed_at = datetime.fromtimestamp(float(observed), tz=timezone.utc)
        elif observed:
            observed_at = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
        else:
            observed_at = datetime.now(timezone.utc)
    except (ValueError, OSError):
        observed_at = datetime.now(timezone.utc)
    station = None
    if "latitude" in norm and "longitude" in norm:
        station = {"name": norm.get("name"), "latitude": norm["latitude"], "longitude": norm["longitude"]}
    return ObservationIn(
        station_id=stn_id, observed_at=observed_at, source="AWS_IN_SITU", adapter="push",
        temperature=norm.get("temperature"), humidity=norm.get("humidity"), pressure=norm.get("pressure"),
        wind_speed=norm.get("windSpeed"), station=station,
    )


# ── live stream ─────────────────────────────────────────────────────────
@router.get("/stream")
async def stream(
    request: Request,
    since: Optional[int] = Query(None, description="Resume after this event id (from /api/network/state)"),
    types: Optional[str] = Query(None, description="Comma-separated event types to receive"),
    last_event_id: Optional[str] = Header(None),
):
    rt = _rt()
    resume = since
    if last_event_id and last_event_id.isdigit():
        resume = int(last_event_id)
    wanted = {t.strip() for t in types.split(",")} if types else None
    sub = rt.broker.subscribe(since_id=resume, types=wanted)

    async def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    e = await asyncio.wait_for(sub.queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"id: {e.id}\nevent: {e.type}\ndata: {_json(e.data | {'_ts': e.ts})}\n\n"
        finally:
            rt.broker.unsubscribe(sub)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
    })


@router.get("/network/state")
def network_state():
    return _rt().network_snapshot()


@router.get("/system/health")
def system_health():
    return _rt().system_health()


@router.get("/sources")
def sources():
    return {"sources": [a.status.to_dict() for a in _rt().adapters]}


@router.get("/events/recent")
def recent_events(limit: int = Query(50, ge=1, le=500), types: Optional[str] = None):
    wanted = {t.strip() for t in types.split(",")} if types else None
    return {"events": _rt().broker.recent(limit, wanted)}


# ── push ingestion ──────────────────────────────────────────────────────
@router.post("/observations", status_code=202)
async def push_observations(body: Dict[str, Any], x_ather_token: Optional[str] = Header(None)):
    rt = _rt()
    token = os.environ.get("ATHER_INGEST_TOKEN")
    if token and not (x_ather_token and hmac.compare_digest(token, x_ather_token)):
        raise HTTPException(status_code=401, detail="missing or invalid X-ATHER-Token")
    raw_items = body.get("observations") if isinstance(body.get("observations"), list) else [body]
    if len(raw_items) > 5000:
        raise HTTPException(status_code=413, detail="at most 5000 observations per request")
    items, invalid = [], []
    for i, raw in enumerate(raw_items):
        try:
            raw = dict(raw)
            raw.pop("meta", None)  # internal provenance cannot be forged by callers
            raw.setdefault("adapter", "push")
            items.append(ObservationIn(**raw))
        except (ValidationError, TypeError) as e:
            rt.metrics.rejected.add()
            errors = e.errors(include_url=False) if isinstance(e, ValidationError) else [{"msg": str(e)}]
            invalid.append({"index": i, "code": "SCHEMA_INVALID", "errors": json.loads(_json(errors))})
    result = await rt.ingest(items, block=False)
    result["rejected"] = invalid + result["rejected"]
    if items and not result["accepted"] and any(r.get("code") == "STREAM_FULL" for r in result["rejected"]):
        raise HTTPException(status_code=503, detail=result)
    return result


# ── station views ───────────────────────────────────────────────────────
@router.get("/stations/{station_id}/live")
def station_live(station_id: str):
    rt = _rt()
    stn = _station(rt, station_id)
    health = rt.processor.health.get(station_id)
    latest = rt.store.latest_detection(station_id)
    from .reference import compare
    obs = {"temperature": stn.get("temperature"), "humidity": stn.get("humidity"),
           "pressure": stn.get("pressure"), "wind_speed": stn.get("windSpeed")}
    return {
        "station_id": station_id,
        "live_feed": bool(health),
        "health": health,
        "latest_detection": latest,
        "reference_comparison": compare(obs, stn["latitude"], stn["longitude"],
                                        (health or {}).get("source") or str(stn.get("dataSource")),
                                        rt.reference.available),
        "active_faults": [f.to_dict() for f in rt.faults.list(active_only=True)
                          if f.station_id == station_id or station_id in f.affected_station_ids],
    }


@router.get("/stations/{station_id}/timeseries")
def station_timeseries(station_id: str, hours: float = Query(6, gt=0, le=72),
                       max_points: int = Query(360, ge=10, le=2000)):
    rt = _rt()
    _station(rt, station_id)
    since = time.time() - hours * 3600
    rows = rt.store.history(station_id, since, max_points=max_points)
    points = []
    for r in rows:
        dp = r.get("dew_point")
        points.append({
            "t": datetime.fromtimestamp(r["observed_at"], tz=timezone.utc).isoformat(),
            "epoch": r["observed_at"],
            "temperature": r.get("temperature"), "humidity": r.get("humidity"), "pressure": r.get("pressure"),
            "wind_speed": r.get("wind_speed"), "wind_direction": r.get("wind_direction"),
            "rainfall": r.get("rainfall"),
            "dew_point": dp if dp is not None else dew_point_c(r.get("temperature"), r.get("humidity")),
            "dew_point_derived": dp is None,
            "samples": r.get("samples", 1),
            "late": bool(r.get("late")),
        })
    available = [p for p in ("temperature", "humidity", "pressure", "wind_speed", "rainfall", "dew_point")
                 if any(pt.get(p) is not None for pt in points)]
    return {"station_id": station_id, "hours": hours, "points": points, "parameters_available": available,
            "source": (rt.processor.health.get(station_id) or {}).get("source"),
            "downsampled": any(pt["samples"] > 1 for pt in points)}


@router.get("/stations/{station_id}/detections")
def station_detections(station_id: str, hours: float = Query(6, gt=0, le=72), limit: int = Query(1000, ge=1, le=5000)):
    rt = _rt()
    _station(rt, station_id)
    rows = rt.store.detections(station_id, time.time() - hours * 3600, limit)
    for r in rows:
        r["t"] = datetime.fromtimestamp(r["observed_at"], tz=timezone.utc).isoformat()
    return {"station_id": station_id, "hours": hours, "detections": rows}


@router.get("/detections/{detection_id}")
def get_detection(detection_id: str):
    det = _rt().store.detection(detection_id)
    if not det:
        raise HTTPException(status_code=404, detail=f"Detection '{detection_id}' not found")
    return det


def _pearson(a: List[float], b: List[float]) -> Optional[float]:
    n = len(a)
    if n < 6:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 1e-12 or vb <= 1e-12:
        return None
    return round(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb), 3)


@router.get("/stations/{station_id}/spatial")
def station_spatial(station_id: str, radius_km: float = Query(60.0, gt=1, le=250),
                    minutes: float = Query(60.0, gt=5, le=720), parameter: str = "temperature"):
    """Spatial event analysis (spec §12), built on L4's own consensus:
    is this change isolated to the station (sensor) or shared by its
    neighbourhood (weather)? Also returns each neighbour's correlation with
    the station over the window and the regional footprint of abnormal
    stations."""
    rt = _rt()
    stn = _station(rt, station_id)
    if parameter not in ("temperature", "humidity", "pressure"):
        raise HTTPException(status_code=400, detail="parameter must be temperature, humidity or pressure")
    health = rt.processor.health
    lat, lon = stn["latitude"], stn["longitude"]
    near = []
    for sid, h in list(health.items()):
        if sid == station_id or h.get("latitude") is None:
            continue
        d = haversine_distance_km(lat, lon, h["latitude"], h["longitude"])
        if d <= radius_km:
            near.append((d, sid, h))
    near.sort(key=lambda x: x[0])
    ids = [station_id] + [sid for _, sid, _ in near[:15]]
    since = time.time() - minutes * 60
    rows = rt.store.observations_between(ids, since, time.time())
    series: Dict[str, Dict[float, float]] = {}
    for r in rows:
        if r.get(parameter) is not None:
            series.setdefault(r["station_id"], {})[round(r["observed_at"])] = r[parameter]
    target_series = series.get(station_id, {})

    def delta(sid: str) -> Optional[float]:
        s = series.get(sid, {})
        if len(s) < 2:
            return None
        ks = sorted(s)
        return round(s[ks[-1]] - s[ks[0]], 2)

    neighbours = []
    for d, sid, h in near[:15]:
        common = sorted(set(target_series) & set(series.get(sid, {})))
        corr = _pearson([target_series[k] for k in common], [series[sid][k] for k in common])
        neighbours.append({
            "station_id": sid, "name": h.get("name"), "distance_km": round(d, 1),
            "latitude": h.get("latitude"), "longitude": h.get("longitude"),
            "overall_status": h.get("overall_status"), "interpretation": h.get("interpretation"),
            "value": (h.get("values") or {}).get(parameter), "change_over_window": delta(sid),
            "correlation": corr, "simulated": h.get("simulated"),
        })
    me = health.get(station_id) or {}
    my_change = delta(station_id)
    n_changes = [n["change_over_window"] for n in neighbours if n["change_over_window"] is not None]
    abnormal = [n for n in neighbours if n["overall_status"] in ("suspect", "anomaly")]
    weather = [n for n in neighbours if n["interpretation"] == "likely_weather_event"]
    verdict, text = "insufficient_neighbours", "Fewer than two live neighbours in range — spatial evidence is limited."
    if len(n_changes) >= 2 and my_change is not None:
        n_sorted = sorted(n_changes)
        median = n_sorted[len(n_sorted) // 2]
        spread = max(1.0 if parameter == "temperature" else 3.0 if parameter == "humidity" else 0.8,
                     (n_sorted[-1] - n_sorted[0]) / 2)
        if abs(my_change - median) <= spread:
            if abs(median) >= (2.0 if parameter == "temperature" else 8.0 if parameter == "humidity" else 1.5):
                verdict, text = "regional_event", (f"Neighbours changed by a median {median:+.1f} over the window, like this "
                                                   f"station ({my_change:+.1f}) — a shared, regional signal (likely weather).")
            else:
                verdict, text = "consistent", "Station and neighbours move together; no regional event in progress."
        else:
            verdict, text = "isolated", (f"This station changed {my_change:+.1f} while neighbours changed a median "
                                         f"{median:+.1f} — the change is local to the station (sensor fault more likely).")
    latest = rt.store.latest_detection(station_id) or {}
    return {
        "station_id": station_id, "parameter": parameter, "radius_km": radius_km, "window_minutes": minutes,
        "station": {"latitude": lat, "longitude": lon, "name": stn.get("name"),
                    "overall_status": me.get("overall_status"), "interpretation": me.get("interpretation"),
                    "value": (me.get("values") or {}).get(parameter), "change_over_window": my_change},
        "neighbours": neighbours,
        "footprint": {"neighbours_in_radius": len(neighbours), "abnormal": len(abnormal),
                      "weather_classified": len(weather),
                      "abnormal_fraction": round(len(abnormal) / len(neighbours), 2) if neighbours else None},
        "l4": (latest.get("layer_results") or {}).get("L4"),
        "expected": latest.get("expected"),
        "verdict": verdict, "explanation": text,
        "series": {sid: [{"epoch": k, "value": v} for k, v in sorted(s.items())] for sid, s in series.items()},
    }


# ── test lab ────────────────────────────────────────────────────────────
@router.get("/lab/fault-types")
def fault_types():
    from app.sources.simulation import FAULT_TYPES, SEVERITIES, expected_time_to_detection
    from config import CONFIG
    rt = _rt()
    return {
        "severities": SEVERITIES,
        "simulation_enabled": rt.simulation.status.state not in ("NOT_CONFIGURED", "DISABLED"),
        "cadence_s": rt.simulation.cadence_s,
        "fault_types": [
            {"id": k, "label": v["label"], "parameters": v["parameters"], "description": v["description"],
             "expected_layers": v["expected_layers"], "expected_interpretation": v["expected_interpretation"],
             "expected_time_to_detection": expected_time_to_detection(
                 k, rt.simulation.cadence_s, CONFIG.temporal.frozen_min_span_minutes)}
            for k, v in FAULT_TYPES.items()
        ],
    }


@router.get("/lab/faults")
def list_faults(active: bool = False):
    return {"faults": [f.to_dict() for f in _rt().faults.list(active_only=active)]}


@router.post("/lab/faults", status_code=201)
def inject_fault(body: Dict[str, Any]):
    rt = _rt()
    if rt.simulation.status.state in ("NOT_CONFIGURED", "DISABLED"):
        raise HTTPException(status_code=409, detail="Fault injection needs the simulated feed (ATHER_SIM_ENABLED=1).")
    sid = body.get("station_id")
    if sid not in set(rt.simulation.station_ids()):
        raise HTTPException(status_code=400, detail="Faults can only be injected into stations on the simulated feed.")
    stn = rt.stations._stations[sid]
    try:
        f = rt.faults.inject(
            sid, body.get("fault_type", ""), body.get("parameter"), body.get("severity", "medium"),
            duration_s=float(body.get("duration_minutes", 15)) * 60.0,
            station_latlon=(stn["latitude"], stn["longitude"]),
            radius_km=body.get("radius_km"),
        )
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    rt.broker.publish(ev.FAULT_INJECTED, f.to_dict() | {"station_name": stn.get("name")})
    return f.to_dict()


@router.delete("/lab/faults/{fault_id}")
def cancel_fault(fault_id: str):
    rt = _rt()
    f = rt.faults.cancel(fault_id)
    if not f:
        raise HTTPException(status_code=404, detail="fault not found")
    rt.broker.publish(ev.FAULT_CLEARED, f.to_dict())
    return f.to_dict()


# ── replay ──────────────────────────────────────────────────────────────
_replay_service = None


def _replays():
    global _replay_service
    rt = _rt()
    from .replay import ReplayService
    if _replay_service is None or _replay_service.rt is not rt:
        _replay_service = ReplayService(rt)
    return _replay_service


@router.post("/replay", status_code=202)
async def start_replay(body: Dict[str, Any]):
    svc = _replays()
    try:
        return await svc.run(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/replay/{replay_id}")
def get_replay(replay_id: str):
    r = _replays().results.get(replay_id)
    if not r:
        raise HTTPException(status_code=404, detail="replay not found")
    return r
