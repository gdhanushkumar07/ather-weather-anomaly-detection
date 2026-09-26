"""
Stage 6 Phase 4: long-running stream simulation (multiple days, multiple
stations, multiple injected events) against the REAL, production
TemporalPatternLayer (with Stage 6's timestamp/gap fixes applied).
"""
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import numpy as np

from config import CONFIG
from schema import AWSReading
from engine.layer2_temporal import TemporalPatternLayer

START = datetime(2025, 3, 1, tzinfo=timezone.utc)


def _reading(ts, temp, press, rh, station):
    return AWSReading(station_id=station, timestamp=ts, temperature_c=temp, pressure_hpa=press,
                       humidity_pct=rh, lat=17.0, lon=78.0)


def _base_series(n, seed):
    rng = np.random.default_rng(seed)
    days = n / 144.0
    temp = 25 + 3 * np.sin(np.linspace(0, 2 * np.pi * days, n)) + rng.normal(0, 0.05, n)
    press = 1012 + rng.normal(0, 0.05, n)
    rh = 55 + 5 * np.cos(np.linspace(0, 2 * np.pi * days, n)) + rng.normal(0, 0.1, n)
    return temp, press, rh


def run_long_stream(days: int = 5, seed: int = 42) -> Dict[str, Any]:
    n = days * 144
    layer = TemporalPatternLayer(CONFIG.temporal)

    events = {
        "LR-SPIKE":  {"type": "temperature_spike",  "at": 300, "duration": 1,  "magnitude": 12.0},
        "LR-DRIFT":  {"type": "temperature_drift",  "at": 300, "duration": 25, "rate": 0.4},
        "LR-FROZEN": {"type": "frozen_temperature", "at": 300, "duration": 14, "magnitude": None},
        "LR-NOISE":  {"type": "noise_burst",        "at": 300, "duration": 3,  "magnitude": 2.0},
        "LR-QUIET":  {"type": "none", "at": None, "duration": 0, "magnitude": None},  # pure normal control
    }

    all_scores: Dict[str, List[Dict[str, Any]]] = {}

    for station, ev in events.items():
        # Stable hash (not Python's per-process-salted hash()) for a
        # deterministic per-station seed offset, matching the established
        # project convention (temporal_dataset/sequence_generator.py).
        station_seed = seed + (zlib.crc32(station.encode("utf-8")) % 1000)
        temp, press, rh = _base_series(n, seed=station_seed)
        rng = np.random.default_rng(seed)
        scores = []
        for i in range(n):
            ts = START + timedelta(minutes=10 * i)
            t, p, r = float(temp[i]), float(press[i]), float(rh[i])

            if ev["at"] is not None and ev["at"] <= i < ev["at"] + ev["duration"]:
                if ev["type"] == "temperature_spike" and i == ev["at"]:
                    t += ev["magnitude"]
                elif ev["type"] == "temperature_drift":
                    t += ev["rate"] * (i - ev["at"] + 1)
                elif ev["type"] == "frozen_temperature":
                    t = float(temp[ev["at"] - 1])
                elif ev["type"] == "noise_burst":
                    t += rng.normal(0, ev["magnitude"])

            score, ch_scores, reason, detail = layer.evaluate(_reading(ts, t, p, r, station))
            lstm_detail = detail.get("lstm", {})  # absent for the first ~2 readings (pre-early-return)
            scores.append({
                "step": i, "score": score, "reason_present": reason is not None,
                "lstm_available": lstm_detail.get("lstm_available", False),
                "recent_lstm_peak": lstm_detail.get("recent_lstm_peak", 0.0),
                "in_event_window": ev["at"] is not None and ev["at"] <= i < ev["at"] + ev["duration"] + 20,
            })
        all_scores[station] = scores

    # ── Analysis ─────────────────────────────────────────────────────────
    result: Dict[str, Any] = {"days": days, "n_steps_per_station": n, "events": {k: v for k, v in events.items()}}

    for station, scores in all_scores.items():
        warm = [s for s in scores if s["step"] >= 144]  # exclude warm-up window from FP-rate stats
        outside_event = [s for s in warm if not s["in_event_window"]]
        inside_event = [s for s in warm if s["in_event_window"]]

        fp_rate_outside = float(np.mean([s["score"] > 0.70 for s in outside_event])) if outside_event else None
        max_score_inside = float(np.max([s["score"] for s in inside_event])) if inside_event else None

        # Recovery: steps after event window before score permanently < 0.5
        recovery_step = None
        if events[station]["at"] is not None:
            event_end = events[station]["at"] + events[station]["duration"]
            for s in scores:
                if s["step"] >= event_end and s["score"] < 0.5:
                    tail = scores[s["step"]:s["step"] + 6]
                    if all(t["score"] < 0.5 for t in tail):
                        recovery_step = s["step"] - event_end
                        break

        result[station] = {
            "event_type": events[station]["type"],
            "false_positive_rate_outside_event_gt_0_70": fp_rate_outside,
            "max_score_inside_event_window": max_score_inside,
            "steps_to_recovery_after_event_end": recovery_step,
            "minutes_to_recovery_after_event_end": recovery_step * 10 if recovery_step is not None else None,
        }

    return result
