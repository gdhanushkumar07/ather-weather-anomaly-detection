"""
DetectionResult construction (spec §7) and interpretation rules.

Everything here is derived from the AnomalyAlert the existing 5-layer
engine produced — this module never re-scores anything. It re-expresses
the verdict on two separate axes so the operator is never told to repair a
sensor during a thunderstorm:

  overall_status  — how far to trust the SENSOR data:
                    nominal | suspect | degraded | anomaly
  interpretation  — what ATHER thinks is happening:
                    nominal | likely_sensor_fault | likely_weather_event |
                    communication_issue | uncertain
"""
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.anomaly.detector import ENGINE_VERSION
from schema import AnomalyAlert, AWSReading, DataQuality, FaultType

from .models import LAYER_KEYS, NormalizedObservation

PIPELINE_VERSION = "ather-pipeline/1.0.0"

WEATHER_CAUSES = {FaultType.GENUINE_EXTREME_WEATHER, FaultType.POSSIBLE_WEATHER_CHANGE}
SENSOR_CAUSES = {
    FaultType.SENSOR_SPIKE, FaultType.FROZEN_SENSOR, FaultType.CALIBRATION_DRIFT,
    FaultType.SINGLE_CHANNEL_FAULT,
}
# The classifier found no fault signature behind a warning-level score.
UNDIAGNOSED_CAUSES = {FaultType.NORMAL, FaultType.INSUFFICIENT_EVIDENCE}


def is_diagnosed_fault(alert: AnomalyAlert) -> bool:
    return alert.veto_fired or _cause(alert) not in UNDIAGNOSED_CAUSES | WEATHER_CAUSES


def is_undiagnosed_warning(alert: AnomalyAlert) -> bool:
    return alert.status == "WARNING" and not alert.veto_fired and _cause(alert) in UNDIAGNOSED_CAUSES

# RCA categories (spec §11).
RCA_LABELS = {
    "physically_impossible_reading": "Physically impossible reading",
    "stuck_sensor": "Stuck sensor",
    "sensor_drift": "Sensor drift",
    "calibration_problem": "Calibration / siting problem",
    "sensor_malfunction": "Sensor malfunction (abrupt step or spike)",
    "communication_issue": "Communication issue",
    "localized_meteorological_event": "Meteorological event (spatially corroborated)",
    "uncertain": "Uncertain — insufficient evidence",
    "none": "No fault",
}

# Recommended action categories (spec §11).
ACTION_LABELS = {
    "inspect_sensor": "Inspect sensor",
    "recalibrate": "Recalibrate",
    "replace_sensor": "Replace sensor",
    "investigate_communications": "Investigate communications",
    "monitor": "Monitor",
    "no_action_weather_event": "No action — likely weather event",
    "none": "No action",
}


def _cause(alert: AnomalyAlert) -> FaultType:
    return alert.root_cause if isinstance(alert.root_cause, FaultType) else FaultType(alert.root_cause)


def interpretation(alert: AnomalyAlert) -> str:
    cause = _cause(alert)
    if alert.status == "NORMAL" and cause == FaultType.NORMAL:
        return "nominal"
    if cause in WEATHER_CAUSES:
        return "likely_weather_event"
    if cause == FaultType.COMMUNICATION_OUTAGE:
        return "communication_issue"
    if alert.veto_fired or cause in SENSOR_CAUSES:
        return "likely_sensor_fault"
    return "uncertain"


def rca_category(alert: AnomalyAlert) -> str:
    cause = _cause(alert)
    if alert.status == "NORMAL" and cause == FaultType.NORMAL:
        return "none"
    if alert.veto_fired:
        return "physically_impossible_reading"
    return {
        FaultType.FROZEN_SENSOR: "stuck_sensor",
        FaultType.CALIBRATION_DRIFT: "sensor_drift",
        FaultType.SINGLE_CHANNEL_FAULT: "calibration_problem",
        FaultType.SENSOR_SPIKE: "sensor_malfunction",
        FaultType.COMMUNICATION_OUTAGE: "communication_issue",
        FaultType.GENUINE_EXTREME_WEATHER: "localized_meteorological_event",
        FaultType.POSSIBLE_WEATHER_CHANGE: "localized_meteorological_event",
    }.get(cause, "uncertain")


def action_category(alert: AnomalyAlert) -> str:
    cause = _cause(alert)
    conf = getattr(alert.diagnosis_confidence, "value", alert.diagnosis_confidence)
    if alert.status == "NORMAL" and cause == FaultType.NORMAL:
        return "none"
    if alert.veto_fired or cause == FaultType.FROZEN_SENSOR:
        return "inspect_sensor"
    if cause == FaultType.SENSOR_SPIKE:
        return "inspect_sensor" if conf in ("HIGH", "MEDIUM") else "monitor"
    if cause in (FaultType.CALIBRATION_DRIFT, FaultType.SINGLE_CHANNEL_FAULT):
        return "recalibrate"
    if cause == FaultType.COMMUNICATION_OUTAGE:
        return "investigate_communications"
    if cause in WEATHER_CAUSES:
        return "no_action_weather_event"
    return "monitor"


def overall_status(alert: AnomalyAlert, reading: AWSReading, freshness: str) -> str:
    cause = _cause(alert)
    if cause == FaultType.GENUINE_EXTREME_WEATHER:
        # Neighbours corroborate the change: the SENSOR is behaving correctly.
        return "nominal"
    if cause == FaultType.POSSIBLE_WEATHER_CHANGE:
        return "suspect"
    if alert.status == "ANOMALY":
        return "anomaly"
    if alert.status == "WARNING":
        return "suspect"
    layers = (alert.canonical_result or {}).get("layers", {})
    l5 = layers.get("sensor_health", {}).get("status")
    missing_core = [c for c in ("temperature_c", "pressure_hpa", "humidity_pct")
                    if reading.data_quality.get(c) != DataQuality.VALID]
    if l5 in ("WARNING", "ANOMALY") or freshness == "STALE" or missing_core:
        return "degraded"
    return "nominal"


def _layer_results(alert: AnomalyAlert, include_details: bool) -> Dict[str, Any]:
    layers = (alert.canonical_result or {}).get("layers", {})
    out: Dict[str, Any] = {}
    for code, key in LAYER_KEYS:
        card = layers.get(key, {})
        status = card.get("status", "UNKNOWN")
        item = {
            "layer": code,
            "key": key,
            "name": card.get("name", key),
            "status": status,
            "score": card.get("score"),
            "evidence_quality": card.get("evidence_quality"),
            "reason": card.get("reason"),
            "triggered": status in ("WARNING", "ANOMALY", "VETO"),
        }
        if include_details:
            item["details"] = card.get("details")
        out[code] = item
    fusion = (alert.layer_details or {}).get("fusion", {}) or {}
    out["fusion"] = {
        "method": "conformal p-value fusion",
        "status": alert.status,
        "p_value": fusion.get("p_value"),
        "nonconformity_score": fusion.get("nonconformity_score"),
        "meaningful_layer_count": fusion.get("meaningful_layer_count"),
        "agreement_factor": fusion.get("agreement_factor"),
        "confidence": round(alert.confidence_score, 3),
        "anomaly_score": round(alert.severity_score, 3),
        "veto": alert.veto_fired,
        "triggered_by": fusion.get("triggered_by"),
    }
    return out


def _summary(status: str, confidence: float, interp: str, layer_results: Dict[str, Any]) -> str:
    triggered = [f"{c}: {layer_results[c]['reason']}" for c, _ in LAYER_KEYS if layer_results[c]["triggered"]]
    head = f"{status.upper()} — {round(confidence * 100)}% confidence"
    if status == "nominal" and interp == "nominal":
        return f"{head}. All five layers within nominal envelopes."
    tail = {
        "likely_sensor_fault": "Therefore likely a sensor fault.",
        "likely_weather_event": "Neighbouring stations show the same change — therefore likely a genuine weather event, not a sensor fault.",
        "communication_issue": "Therefore likely a communication issue.",
        "uncertain": "Evidence is not yet conclusive; monitoring.",
        "nominal": "",
    }[interp]
    body = "; ".join(triggered) if triggered else "No individual layer crossed its threshold"
    return f"{head}. {body}. {tail}".strip()


def build_detection_result(
    *,
    alert: AnomalyAlert,
    reading: AWSReading,
    obs: NormalizedObservation,
    freshness: str,
    reference_comparison: Dict[str, Any],
    neighbors: List[Dict[str, Any]],
    baseline: Dict[str, Any],
    processing_started: float,
    run_id: str,
    hold_single_warning: bool = False,
) -> Dict[str, Any]:
    """hold_single_warning: alarm hysteresis. An undiagnosed warning (a
    single statistical excursion the classifier attributes to no fault) that
    has NOT persisted is reported as nominal + watch; engine_status keeps the
    raw WARNING so nothing is hidden from the audit trail."""
    interp = interpretation(alert)
    status = overall_status(alert, reading, freshness)
    watch = False
    if hold_single_warning and status == "suspect" and is_undiagnosed_warning(alert):
        status, watch = "nominal", True
    abnormal = status != "nominal" or interp != "nominal"
    layer_results = _layer_results(alert, include_details=abnormal)
    triggered = [c for c, _ in LAYER_KEYS if layer_results[c]["triggered"]]
    canonical = alert.canonical_result or {}
    severity = canonical.get("overall", {}).get("severity", "NONE")
    rca = rca_category(alert)
    action = action_category(alert)
    now = time.time()

    result: Dict[str, Any] = {
        "detection_id": "det_" + uuid.uuid4().hex[:16],
        "observation_id": obs.observation_id,
        "station_id": obs.station_id,
        "observation_timestamp": obs.observed_at.isoformat(),
        "received_timestamp": obs.received_at.isoformat(),
        "processing_timestamp": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "overall_status": status,
        "engine_status": alert.status,
        "interpretation": interp,
        "confidence": round(alert.confidence_score, 3),
        "anomaly_score": round(alert.severity_score, 3),
        "severity": severity,
        "triggered_layers": triggered,
        "layer_results": layer_results,
        "summary": (
            "WATCH — single undiagnosed statistical excursion; held for one observation before "
            "raising (alarm hysteresis). " + _summary("suspect", alert.confidence_score, interp, layer_results)
            if watch else _summary(status, alert.confidence_score, interp, layer_results)
        ),
        "watch": watch,
        "diagnosed_fault": is_diagnosed_fault(alert),
        "evidence": list(alert.reasons or []),
        "diagnosis": {
            "root_cause": _cause(alert).value,
            "rca_category": rca,
            "rca_label": RCA_LABELS[rca],
            "confidence": getattr(alert.diagnosis_confidence, "value", alert.diagnosis_confidence),
            "primary_signal": alert.primary_signal,
            "alternatives": alert.alternative_causes,
            "affected_channels": alert.affected_channels,
        },
        "observed_values": obs.values,
        "expected": baseline,
        "neighbors": neighbors,
        "reference_comparison": reference_comparison,
        "recommended_action": {
            "category": action,
            "label": ACTION_LABELS[action],
            "detail": alert.operator_action,
        },
        "sensor_health_index": round(alert.sensor_health_index, 1),
        "data_quality": canonical.get("data_quality"),
        "provenance": {
            "data_source": obs.source,
            "adapter": obs.adapter,
            "simulated": obs.source == "SIMULATED_AWS",
            "observation_timestamp": obs.observed_at.isoformat(),
            "received_timestamp": obs.received_at.isoformat(),
            "processing_timestamp": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "freshness": freshness,
            "detector_version": ENGINE_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "reference_model": "Open-Meteo NWP (best-match model)" if reference_comparison.get("available") else None,
            "input_parameters": {k: v for k, v in obs.values.items() if v is not None},
            "quality_flags": obs.flags,
            "triggered_rules": list(alert.reasons or []),
            "neighbor_count": len(neighbors),
            "processing_ms": round((time.perf_counter() - processing_started) * 1000.0, 2),
            "run_id": run_id,
            "injected_fault": obs.meta.get("injected_fault"),
        },
    }
    if not abnormal:
        # Keep nominal rows compact in storage; the full evidence set is kept
        # for everything an operator might need to audit.
        result["neighbors"] = neighbors[:3]
    return result


def compact_for_event(det: Dict[str, Any]) -> Dict[str, Any]:
    """The slice of a DetectionResult pushed to every dashboard."""
    return {
        "detection_id": det["detection_id"],
        "station_id": det["station_id"],
        "observation_timestamp": det["observation_timestamp"],
        "processing_timestamp": det["processing_timestamp"],
        "overall_status": det["overall_status"],
        "engine_status": det["engine_status"],
        "interpretation": det["interpretation"],
        "confidence": det["confidence"],
        "severity": det["severity"],
        "triggered_layers": det["triggered_layers"],
        "root_cause": det["diagnosis"]["root_cause"],
        "rca_label": det["diagnosis"]["rca_label"],
        "summary": det["summary"],
        "watch": det.get("watch", False),
        "diagnosed_fault": det.get("diagnosed_fault", False),
        "values": det["observed_values"],
        "source": det["provenance"]["data_source"],
        "simulated": det["provenance"]["simulated"],
        "injected_fault": det["provenance"].get("injected_fault"),
    }
