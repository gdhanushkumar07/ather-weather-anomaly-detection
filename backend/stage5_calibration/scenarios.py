"""
Phase 9: full-pipeline scenarios A-F, run through the REAL AnomalyDetector
(all 5 layers + fusion), using the CALIBRATED Stage 5 TemporalPatternLayer
(loaded automatically via CONFIG.lstm_temporal's new default). Scenario F
reuses the EXISTING simulation infrastructure (app/simulation) unmodified.
"""
from typing import Any, Dict

from datetime import datetime, timedelta, timezone
import numpy as np

from app.anomaly.detector import AnomalyDetector
from app.simulation.service import run_simulation

START = datetime(2025, 6, 1, tzinfo=timezone.utc)


def _normal_series(n: int, seed: int):
    rng = np.random.default_rng(seed)
    temp = 25.0 + 3.0 * np.sin(np.linspace(0, 4 * np.pi, n)) + rng.normal(0, 0.05, n)
    press = 1012.0 + rng.normal(0, 0.05, n)
    rh = 55.0 + 5.0 * np.cos(np.linspace(0, 4 * np.pi, n)) + rng.normal(0, 0.1, n)
    return temp, press, rh


def _feed(detector: AnomalyDetector, station_id: str, temp, press, rh, start_step=0):
    status = None
    for i, (t, p, r) in enumerate(zip(temp, press, rh)):
        step = start_step + i
        stn = {
            "id": station_id, "name": station_id, "latitude": 17.0, "longitude": 78.0,
            "temperature": None if t is None else float(t),
            "pressure": None if p is None else float(p),
            "humidity": None if r is None else float(r),
        }
        status, _ = detector.evaluate_station(stn)
    # Use the full AnomalyAlert (not the legacy dict, which is None for
    # NORMAL/non-anomalous readings) so layer_scores is always available.
    alert = detector.get_station_alert(station_id)
    return status, alert


def run_pipeline_scenarios() -> Dict[str, Any]:
    results: Dict[str, Any] = {}

    # A. Normal weather
    det_a = AnomalyDetector()
    temp, press, rh = _normal_series(150, seed=100)
    status, alert = _feed(det_a, "S5-A-NORMAL", temp, press, rh)
    results["A_normal_weather"] = {
        "status": status, "layer_scores": alert.layer_scores if alert else None,
        "temporal_score": alert.layer_scores["temporal"] if alert else None,
    }

    # B. Temperature spike
    det_b = AnomalyDetector()
    temp, press, rh = _normal_series(144, seed=101)
    _feed(det_b, "S5-B-SPIKE", temp, press, rh)
    status, alert = _feed(det_b, "S5-B-SPIKE", [42.0], [float(press[-1])], [float(rh[-1])], start_step=144)
    results["B_temperature_spike"] = {
        "status": status, "temporal_score": alert.layer_scores["temporal"],
        "is_anomaly": alert.is_anomaly, "reasons": alert.reasons,
    }

    # C. Frozen temperature
    det_c = AnomalyDetector()
    temp, press, rh = _normal_series(144, seed=102)
    _feed(det_c, "S5-C-FROZEN", temp, press, rh)
    frozen_val = float(temp[-1])
    status = alert = None
    for i in range(14):
        status, alert = _feed(det_c, "S5-C-FROZEN", [frozen_val], [float(press[-1])], [float(rh[-1])], start_step=144 + i)
    results["C_frozen_temperature"] = {
        "status": status, "temporal_score": alert.layer_scores["temporal"],
        "reasons": alert.reasons,
    }

    # D. Stale packet
    det_d = AnomalyDetector()
    temp, press, rh = _normal_series(144, seed=103)
    _feed(det_d, "S5-D-STALE", temp, press, rh)
    st, sp, sr = float(temp[-1]), float(press[-1]), float(rh[-1])
    status = alert = None
    for i in range(14):
        status, alert = _feed(det_d, "S5-D-STALE", [st], [sp], [sr], start_step=144 + i)
    results["D_stale_packet"] = {
        "status": status, "temporal_score": alert.layer_scores["temporal"],
        "reasons": alert.reasons,
    }

    # E. Missing observation
    det_e = AnomalyDetector()
    temp, press, rh = _normal_series(144, seed=104)
    _feed(det_e, "S5-E-MISSING", temp, press, rh)
    status, alert = _feed(det_e, "S5-E-MISSING", [None], [None], [None], start_step=144)
    results["E_missing_observation"] = {
        "status": status, "temporal_score": alert.layer_scores["temporal"],
    }

    # F. Regional weather event (existing simulation infrastructure, unmodified)
    sim_result = run_simulation("REGIONAL_WEATHER_EVENT")
    results["F_regional_weather_event"] = {
        "fusion_status": sim_result["fusion"]["status"],
        "root_cause": sim_result["root_cause"]["category"],
        "temporal_layer_score": sim_result["diagnostics"]["temporal"]["score"],
        "spatial_layer_score": sim_result["diagnostics"]["spatial"]["score"],
        "note": "Reuses existing app/simulation scenario infrastructure unmodified — not a Stage 5 addition.",
    }

    return results
