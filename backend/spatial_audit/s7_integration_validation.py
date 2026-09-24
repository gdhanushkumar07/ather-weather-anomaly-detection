"""
S7 -- production-shape integration validation (read-only).

Runs the REAL integrated pipeline (Physics/Temporal/Multivariate/Spatial S1-S6/
Drift -> Fusion -> Root Cause -> estimated value -> canonical object) over the
full production-shaped inventory data/stations.json, and reports:
completion, finiteness, determinism, evidence coverage, output-contract
validity, and runtime (including the share spent in neighbor selection).

data/stations.json is production-SHAPED demo/seed metadata -- NOT confirmed
AWS telemetry and NOT ground truth. This script measures computability,
determinism, and cost only; it makes NO accuracy claim.

Run:  cd backend && python3 -m spatial_audit.s7_integration_validation
"""
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.anomaly.detector import AnomalyDetector
from schema import AWSReading

RESULTS_PATH = Path(__file__).resolve().parent / "results" / "spatial_s7_integration_validation.json"
REQUIRED_TOP = ("station", "observation", "overall", "layers", "diagnosis", "weather_analysis", "insights", "data_quality")


def _finite(x):
    return x is None or (isinstance(x, (int, float)) and math.isfinite(x))


def run():
    with open(BACKEND_DIR.parent / "data" / "stations.json") as f:
        raw = json.load(f)
    readings = [
        AWSReading(station_id=s["id"], lat=s["latitude"], lon=s["longitude"],
                   temperature_c=s.get("temperature"), pressure_hpa=s.get("pressure"),
                   humidity_pct=s.get("humidity"))
        for s in raw
    ]

    def sweep():
        det = AnomalyDetector()
        det.update_spatial_pool(readings)
        alerts, t0 = [], time.perf_counter()
        for r in readings:
            alerts.append(det.evaluate_reading(r))
        return det, alerts, time.perf_counter() - t0

    det, alerts, elapsed = sweep()
    det2, alerts2, _ = sweep()

    contract_ok = non_finite = with_ra = with_cv = unavailable = 0
    statuses, cv_states, root_causes = {}, {}, {}
    for a in alerts:
        c = a.canonical_result
        if all(k in c for k in REQUIRED_TOP):
            contract_ok += 1
        if not all(_finite(v) for v in a.layer_scores.values()) or not _finite(a.confidence_score) or not _finite(a.severity_score):
            non_finite += 1
        card = c["layers"]["spatial"]
        with_ra += card["regional_attribution"] is not None
        with_cv += card["counterfactual_verification"] is not None
        unavailable += sum(1 for l in c["layers"].values() if l["status"] == "UNAVAILABLE")
        statuses[a.status] = statuses.get(a.status, 0) + 1
        root_causes[a.root_cause.value] = root_causes.get(a.root_cause.value, 0) + 1
        if card["counterfactual_verification"]:
            k = card["counterfactual_verification"]["overall_status"]
            cv_states[k] = cv_states.get(k, 0) + 1

    determinism = all(
        (x.status, x.severity_score, x.confidence_score, x.root_cause, x.layer_scores,
         x.canonical_result["layers"]["spatial"]["counterfactual_verification"])
        == (y.status, y.severity_score, y.confidence_score, y.root_cause, y.layer_scores,
            y.canonical_result["layers"]["spatial"]["counterfactual_verification"])
        for x, y in zip(alerts, alerts2)
    )

    # Cost breakdown: neighbor selection vs the whole per-station evaluation.
    sample = readings[:200]
    t0 = time.perf_counter()
    for r in sample:
        det.get_neighbors_for_reading(r)
    neighbor_ms = (time.perf_counter() - t0) / len(sample) * 1000

    t0 = time.perf_counter()
    events = det.compute_spatial_events()
    events_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    tr1 = det.update_spatial_event_tracking(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc))
    tr2 = det.update_spatial_event_tracking(timestamp=datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc))
    tracking_ms = (time.perf_counter() - t0) * 1000

    return {
        "disclaimer": ("data/stations.json is production-SHAPED seed/demo metadata, not confirmed AWS telemetry "
                       "or ground truth. This validates completion/finiteness/determinism/cost only; no accuracy claim."),
        "stations_processed": len(alerts), "stations_in_inventory": len(readings),
        "output_contract_valid": contract_ok, "non_finite_outputs": non_finite,
        "layer_unavailable_events": unavailable,
        "spatial_regional_attribution_present": with_ra, "spatial_counterfactual_present": with_cv,
        "final_status_distribution": statuses, "root_cause_distribution": root_causes,
        "counterfactual_overall_status_distribution": cv_states,
        "deterministic_across_two_full_sweeps": determinism,
        "runtime": {
            "full_sweep_seconds": round(elapsed, 3),
            "ms_per_station": round(elapsed / len(alerts) * 1000, 3),
            "neighbor_selection_ms_per_station": round(neighbor_ms, 3),
            "compute_spatial_events_ms": round(events_ms, 2),
            "two_event_tracking_updates_ms": round(tracking_ms, 2),
        },
        "spatial_events": {"candidates": events["candidates_considered"], "clusters": events["cluster_count"]},
        "event_tracking": {"t1_new": tr1["summary"]["new_count"], "t2_updated": tr2["summary"]["updated_count"]},
    }


if __name__ == "__main__":
    out = run()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
