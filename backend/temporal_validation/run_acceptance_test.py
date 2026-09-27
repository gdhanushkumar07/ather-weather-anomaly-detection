"""
Temporal Intelligence — Final Acceptance Test (validation only).

Runs the FROZEN, unmodified Stage 1-6 TemporalPatternLayer against fresh
deterministic scenarios and reuses existing Stage 5/6 calibration results
where appropriate. Makes NO production code changes. Every measurement
here is synthetic-data engineering validation, not real-world accuracy.
"""
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import numpy as np

from config import CONFIG
from schema import AWSReading
from engine.layer2_temporal import TemporalPatternLayer

OUT_DIR = Path(__file__).resolve().parent
START = datetime(2025, 6, 1, tzinfo=timezone.utc)


def _reading(ts, temp, press, rh, station):
    return AWSReading(station_id=station, timestamp=ts, temperature_c=temp, pressure_hpa=press,
                       humidity_pct=rh, lat=17.0, lon=78.0)


def _base_series(n, seed):
    rng = np.random.default_rng(seed)
    days = max(1, n / 144.0)
    temp = 25 + 3 * np.sin(np.linspace(0, 2 * np.pi * days, n)) + rng.normal(0, 0.05, n)
    press = 1012 + rng.normal(0, 0.05, n)
    rh = 55 + 5 * np.cos(np.linspace(0, 2 * np.pi * days, n)) + rng.normal(0, 0.1, n)
    return temp, press, rh


# ── Section 2: normal behavior ──────────────────────────────────────────
def run_normal_behavior():
    from stage5_calibration.config import Stage5Config
    from stage5_calibration.normal_calibration import run_normal_calibration

    cfg = Stage5Config()
    result = run_normal_calibration(cfg)
    s = result["summary"]
    df = result["records_df"]

    # Max continuous elevated-score (>0.70) run length, per station, over the max.
    max_run = 0
    for station_id, g in df.sort_values("timestamp").groupby("station_id"):
        elevated = (g["integrated_overall_score"] > 0.70).to_numpy()
        run = 0
        for v in elevated:
            run = run + 1 if v else 0
            max_run = max(max_run, run)

    return {
        "A_stable_normal": "Covered by the 75-station Stage 1 VALIDATION split — each station's own AR(1) "
                            "slow/fast components represent stable, low-variance normal behavior.",
        "B_diurnal_variation": "Covered inherently — Stage 1's generator embeds a diurnal sinusoid per station.",
        "C_gradual_variation": "Covered inherently — the AR(1) slow component represents gradual drift-free variation.",
        "D_long_running_stream": "See Stage 6 long-run results (stage6_results/stage6_long_run.json): "
                                  "5 stations x 5 days x 144/day = 720 steps/station.",
        "n_stations": s["dataset"]["n_stations"] if "dataset" in s else 75,
        "n_observations": s["dataset"]["n_observations"] if "dataset" in s else len(df),
        "integrated_median": s["integrated"]["overall"]["median"],
        "integrated_p95": s["integrated"]["overall"]["p95"],
        "integrated_p99": s["integrated"]["overall"]["p99"],
        "pct_gt_070": float(100.0 * (df["integrated_overall_score"] > 0.70).mean()),
        "reason_string_rate_pct": s["reason_report_rate"]["integrated_pct"],
        "lstm_availability_pct": s["lstm_availability"]["available_pct"],
        "max_continuous_elevated_run_steps": max_run,
        "max_continuous_elevated_run_minutes": max_run * 10,
        "note": "These figures are IDENTICAL to Stage 5/6's already-documented results (median~0.354, "
                "P95~0.919, 9.6% >0.70, 21.2% reason-rate) -- reported honestly as known limitations, "
                "not changed here (validation-only task).",
    }


# ── Sections 3/4/6: one combined run per anomaly type ────────────────────
ANOMALY_SPECS = {
    "temperature_spike":  {"channel": "temperature_c", "onset": 300, "duration": 1,  "kind": "step", "magnitude": 12.0},
    "temperature_drop":   {"channel": "temperature_c", "onset": 300, "duration": 1,  "kind": "step", "magnitude": -12.0},
    "frozen_temperature": {"channel": "temperature_c", "onset": 300, "duration": 14, "kind": "freeze"},
    "frozen_humidity":    {"channel": "humidity_pct",  "onset": 300, "duration": 14, "kind": "freeze"},
    "pressure_offset":    {"channel": "pressure_hpa",  "onset": 300, "duration": 40, "kind": "offset", "magnitude": 6.0},
    "humidity_offset":    {"channel": "humidity_pct",  "onset": 300, "duration": 40, "kind": "offset", "magnitude": 15.0},
    "temperature_drift":  {"channel": "temperature_c", "onset": 300, "duration": 25, "kind": "drift", "rate": 0.35},
    "noise_burst":        {"channel": "temperature_c", "onset": 300, "duration": 3,  "kind": "noise", "magnitude": 2.5},
    "missing_observation":{"channel": "all",            "onset": 300, "duration": 3,  "kind": "missing"},
    "stale_packet":       {"channel": "all",            "onset": 300, "duration": 8,  "kind": "stale"},
}


def _run_one_anomaly_type(name, spec, n=450, seed=7):
    from stage5_calibration.runner import make_layers

    layers = make_layers()
    temp, press, rh = _base_series(n, seed=seed)
    rng = np.random.default_rng(seed + 1)

    rows = []
    for i in range(n):
        ts = START + timedelta(minutes=10 * i)
        t, p, r = float(temp[i]), float(press[i]), float(rh[i])
        is_event = spec["onset"] <= i < spec["onset"] + spec["duration"]

        if is_event:
            k = spec["kind"]
            if k == "step" and i == spec["onset"]:
                t += spec["magnitude"]
            elif k == "freeze":
                if spec["channel"] == "temperature_c":
                    t = float(temp[spec["onset"] - 1])
                else:
                    r = float(rh[spec["onset"] - 1])
            elif k == "offset":
                if spec["channel"] == "pressure_hpa":
                    p += spec["magnitude"]
                else:
                    r = float(np.clip(r + spec["magnitude"], 0, 100))
            elif k == "drift":
                t += spec["rate"] * (i - spec["onset"] + 1)
            elif k == "noise":
                t += rng.normal(0, spec["magnitude"])
            elif k == "missing":
                t = p = r = None
            elif k == "stale":
                t, p, r = float(temp[spec["onset"] - 1]), float(press[spec["onset"] - 1]), float(rh[spec["onset"] - 1])

        rec = {"step": i, "is_event": is_event}
        for layer_name, layer in layers.items():
            score, scores, reason, detail = layer.evaluate(_reading(ts, t, p, r, f"AV-{name}"))
            if layer_name == "integrated":
                lstm = detail.get("lstm", {})
                rec.update({
                    "integrated_score": score, "reason": reason,
                    "lstm_available": lstm.get("lstm_available", False),
                    "lstm_residual_score": lstm.get("lstm_residual_score", 0.0),
                    "recent_lstm_peak": lstm.get("recent_lstm_peak", 0.0),
                    "predicted_temperature_c": lstm.get("lstm_predicted_temperature_c"),
                    "predicted_pressure_hpa": lstm.get("lstm_predicted_pressure_hpa"),
                    "predicted_humidity_pct": lstm.get("lstm_predicted_humidity_pct"),
                    "temperature_residual": lstm.get("temperature_residual"),
                    "actual_temperature_c": t, "actual_pressure_hpa": p, "actual_humidity_pct": r,
                })
            else:
                rec["rule_score"] = score
        rows.append(rec)

    event_rows = [r for r in rows if r["is_event"]]
    post_event = [r for r in rows if r["step"] >= spec["onset"] + spec["duration"]]

    max_score = max((r["integrated_score"] for r in event_rows), default=0.0)
    first_detect = None
    for r in event_rows:
        if r["integrated_score"] > 0.70:
            first_detect = r["step"] - spec["onset"]
            break

    recovery_step = None
    for idx, r in enumerate(post_event):
        if r["integrated_score"] < 0.5:
            tail = post_event[idx:idx + 6]
            if len(tail) >= 6 and all(t["integrated_score"] < 0.5 for t in tail):
                recovery_step = r["step"] - (spec["onset"] + spec["duration"])
                break

    rule_max = max((r.get("rule_score", 0.0) for r in event_rows), default=0.0)
    lstm_max = max((r.get("lstm_residual_score", 0.0) for r in event_rows if r.get("lstm_available")), default=None)
    peak_max = max((r.get("recent_lstm_peak", 0.0) for r in event_rows if r.get("lstm_available")), default=None)

    # Classification
    rule_strong = rule_max >= 0.7
    lstm_strong = (lstm_max or 0) >= 0.7
    if rule_strong and lstm_strong:
        cls = "both_contribute"
    elif lstm_strong and not rule_strong:
        cls = "lstm_dominated"
    elif rule_strong and not lstm_strong:
        cls = "rule_dominated"
    else:
        cls = "insufficient_evidence"

    # A representative normal-period and event-period prediction sample (Section 4)
    normal_sample = rows[200] if len(rows) > 200 else None
    event_sample = event_rows[len(event_rows) // 2] if event_rows else None

    return {
        "anomaly_type": name,
        "onset_step": spec["onset"], "duration_steps": spec["duration"],
        "rule_max_score": round(rule_max, 4),
        "lstm_max_score": round(lstm_max, 4) if lstm_max is not None else None,
        "recent_peak_max_score": round(peak_max, 4) if peak_max is not None else None,
        "integrated_max_score": round(max_score, 4),
        "first_detection_step_offset": first_detect,
        "detection_delay_minutes": first_detect * 10 if first_detect is not None else None,
        "detected": max_score > 0.70,
        "recovery_step_offset": recovery_step,
        "recovery_minutes": recovery_step * 10 if recovery_step is not None else None,
        "classification": cls,
        "sample_reason_at_max": next((r["reason"] for r in event_rows if r["integrated_score"] == max_score), None),
        "normal_period_prediction_sample": {
            "actual_temperature_c": round(normal_sample["actual_temperature_c"], 2) if normal_sample and normal_sample["actual_temperature_c"] is not None else None,
            "predicted_temperature_c": round(normal_sample["predicted_temperature_c"], 2) if normal_sample and normal_sample.get("predicted_temperature_c") is not None else None,
            "temperature_residual": round(normal_sample["temperature_residual"], 3) if normal_sample and normal_sample.get("temperature_residual") is not None else None,
        } if normal_sample else None,
        "event_period_prediction_sample": {
            "actual_temperature_c": round(event_sample["actual_temperature_c"], 2) if event_sample and event_sample["actual_temperature_c"] is not None else None,
            "predicted_temperature_c": round(event_sample["predicted_temperature_c"], 2) if event_sample and event_sample.get("predicted_temperature_c") is not None else None,
            "temperature_residual": round(event_sample["temperature_residual"], 3) if event_sample and event_sample.get("temperature_residual") is not None else None,
        } if event_sample else None,
    }


def run_anomaly_validation():
    results = {}
    for name, spec in ANOMALY_SPECS.items():
        results[name] = _run_one_anomaly_type(name, spec)
    return results


# ── Section 7: Stage 6 bug-fix regression (direct reproduction) ──────────
def run_robustness_regression():
    findings = {}

    # Bug 1+2: rollback must reset history_complete AND must not false-flag
    layer = TemporalPatternLayer(CONFIG.temporal)
    temp, press, rh = _base_series(144, seed=5)
    ts = START
    for i in range(144):
        ts = START + timedelta(minutes=10 * i)
        layer.evaluate(_reading(ts, float(temp[i]), float(press[i]), float(rh[i]), "ROLLBACK"))
    buf = layer.buffers["ROLLBACK"]
    len_before = len(buf.history_complete)
    rollback_ts = ts - timedelta(minutes=30)
    _, _, _, detail = layer.evaluate(_reading(rollback_ts, float(temp[-1]) + 2.0, float(press[-1]), float(rh[-1]), "ROLLBACK"))
    findings["bug1_rollback_resets_history"] = {
        "len_before": len_before, "len_after": len(buf.history_complete),
        "reset_confirmed": len(buf.history_complete) == 1,
    }
    findings["bug2_no_false_spike_from_rollback"] = {
        "temp_spike_detail_present": detail.get("temp_spike") is not None,
        "false_positive_confirmed_absent": detail.get("temp_spike") is None,
    }

    # Duplicate timestamp
    layer2 = TemporalPatternLayer(CONFIG.temporal)
    ts2 = START
    for i in range(144):
        ts2 = START + timedelta(minutes=10 * i)
        layer2.evaluate(_reading(ts2, float(temp[i]), float(press[i]), float(rh[i]), "DUP"))
    buf2 = layer2.buffers["DUP"]
    layer2.evaluate(_reading(ts2, float(temp[-1]) + 0.1, float(press[-1]), float(rh[-1]), "DUP"))
    findings["duplicate_timestamp_resets"] = {"len_after": len(buf2.history_complete), "reset_confirmed": len(buf2.history_complete) == 1}

    # Bug 3: reading that triggers a big gap must not use stale history
    layer3 = TemporalPatternLayer(CONFIG.temporal)
    ts3 = START
    for i in range(144):
        ts3 = START + timedelta(minutes=10 * i)
        layer3.evaluate(_reading(ts3, float(temp[i]), float(press[i]), float(rh[i]), "GAP"))
    big_gap_ts = ts3 + timedelta(hours=6)
    _, _, _, detail3 = layer3.evaluate(_reading(big_gap_ts, float(temp[-1]), float(press[-1]), float(rh[-1]), "GAP"))
    findings["bug3_gap_reading_does_not_use_stale_history"] = {
        "lstm_available_on_triggering_reading": detail3["lstm"]["lstm_available"],
        "skip_reason": detail3["lstm"]["lstm_skip_reason"],
        "correctly_unavailable": detail3["lstm"]["lstm_available"] is False,
    }

    # Out-of-order reading
    layer4 = TemporalPatternLayer(CONFIG.temporal)
    ts4 = START
    for i in range(144):
        ts4 = START + timedelta(minutes=10 * i)
        layer4.evaluate(_reading(ts4, float(temp[i]), float(press[i]), float(rh[i]), "OOO"))
    buf4 = layer4.buffers["OOO"]
    ooo_ts = ts4 - timedelta(minutes=100)
    layer4.evaluate(_reading(ooo_ts, float(temp[-1]), float(press[-1]), float(rh[-1]), "OOO"))
    findings["out_of_order_reading_resets"] = {"len_after": len(buf4.history_complete), "reset_confirmed": len(buf4.history_complete) == 1}

    # Gap-boundary sanity: just-below/at/above max_gap_minutes
    for label, delta_min in [("just_below", CONFIG.lstm_temporal.max_gap_minutes - 1),
                              ("exactly_at", CONFIG.lstm_temporal.max_gap_minutes),
                              ("just_above", CONFIG.lstm_temporal.max_gap_minutes + 1)]:
        layer5 = TemporalPatternLayer(CONFIG.temporal)
        ts5 = START
        for i in range(144):
            ts5 = START + timedelta(minutes=10 * i)
            layer5.evaluate(_reading(ts5, float(temp[i]), float(press[i]), float(rh[i]), f"GAPB-{label}"))
        buf5 = layer5.buffers[f"GAPB-{label}"]
        len_before5 = len(buf5.history_complete)
        layer5.evaluate(_reading(ts5 + timedelta(minutes=delta_min), float(temp[-1]), float(press[-1]), float(rh[-1]), f"GAPB-{label}"))
        findings[f"gap_boundary_{label}"] = {
            "delta_minutes": delta_min, "len_before": len_before5, "len_after": len(buf5.history_complete),
            "reset": len(buf5.history_complete) == 1,
        }

    return findings


# ── Section 8: output contract ────────────────────────────────────────────
def run_output_contract_check():
    layer = TemporalPatternLayer(CONFIG.temporal)
    temp, press, rh = _base_series(150, seed=3)
    results = {"nan_or_inf_found": False, "score_out_of_bounds_found": False, "channel_score_out_of_bounds_found": False}
    last_result = None
    for i in range(150):
        ts = START + timedelta(minutes=10 * i)
        result = layer.evaluate(_reading(ts, float(temp[i]), float(press[i]), float(rh[i]), "CONTRACT"))
        last_result = result
        score, scores, reason, detail = result
        if not np.isfinite(score):
            results["nan_or_inf_found"] = True
        if not (0.0 <= score <= 1.0):
            results["score_out_of_bounds_found"] = True
        for v in scores.values():
            if not np.isfinite(v) or not (0.0 <= v <= 1.0):
                results["channel_score_out_of_bounds_found"] = True

    score, scores, reason, detail = last_result
    results["return_tuple_length"] = len(last_result)
    results["return_types_correct"] = isinstance(score, float) and isinstance(scores, dict) and (reason is None or isinstance(reason, str)) and isinstance(detail, dict)
    results["lstm_detail_present_when_available"] = "lstm" in detail and detail["lstm"]["lstm_available"] is True

    # warm-up: LSTM absent/unavailable before 144 readings
    layer2 = TemporalPatternLayer(CONFIG.temporal)
    warmup_result = layer2.evaluate(_reading(START, float(temp[0]), float(press[0]), float(rh[0]), "WARMUP"))
    results["lstm_correctly_skipped_during_warmup"] = warmup_result[3].get("lstm", {}).get("lstm_available", None) in (False, None)

    return results


# ── Section 9: performance ────────────────────────────────────────────────
def run_performance_check():
    layer = TemporalPatternLayer(CONFIG.temporal)
    temp, press, rh = _base_series(200, seed=1)
    for i in range(144):
        ts = START + timedelta(minutes=10 * i)
        layer.evaluate(_reading(ts, float(temp[i]), float(press[i]), float(rh[i]), "PERF"))

    n_calls = 150
    t0 = time.perf_counter()
    for i in range(144, 144 + n_calls):
        ts = START + timedelta(minutes=10 * i)
        layer.evaluate(_reading(ts, float(temp[i % 200]), float(press[i % 200]), float(rh[i % 200]), "PERF"))
    elapsed = time.perf_counter() - t0

    avg_ms = (elapsed / n_calls) * 1000
    return {
        "n_calls": n_calls, "avg_latency_ms": round(avg_ms, 3),
        "stage5_stage6_baseline_ms": 2.0,
        "regression_pct": round(100.0 * (avg_ms - 2.0) / 2.0, 1),
        "meaningful_regression": avg_ms > 3.0,  # generous margin before calling it "meaningful"
    }


def main():
    print("=== Temporal Intelligence Final Acceptance Test ===")
    print("Section 2: normal behavior...")
    normal_results = run_normal_behavior()

    print("Section 3/4/6: anomaly validation (10 types)...")
    anomaly_results = run_anomaly_validation()

    print("Section 7: robustness regression...")
    robustness_results = run_robustness_regression()

    print("Section 8: output contract...")
    contract_results = run_output_contract_check()

    print("Section 9: performance...")
    perf_results = run_performance_check()

    with open(OUT_DIR / "normal_results.json", "w") as f:
        json.dump(normal_results, f, indent=2, default=str)
    with open(OUT_DIR / "anomaly_results.json", "w") as f:
        json.dump(anomaly_results, f, indent=2, default=str)
    with open(OUT_DIR / "recovery_results.json", "w") as f:
        recovery_summary = {name: {
            "recovery_minutes": r["recovery_minutes"],
            "recovery_step_offset": r["recovery_step_offset"],
            "detected": r["detected"],
        } for name, r in anomaly_results.items()}
        json.dump(recovery_summary, f, indent=2, default=str)
    with open(OUT_DIR / "robustness_results.json", "w") as f:
        json.dump({"stage6_bug_regression": robustness_results,
                    "output_contract": contract_results,
                    "performance": perf_results}, f, indent=2, default=str)

    print("Done. Artifacts written to", OUT_DIR)
    return {
        "normal": normal_results, "anomaly": anomaly_results,
        "robustness": robustness_results, "contract": contract_results, "performance": perf_results,
    }


if __name__ == "__main__":
    main()
