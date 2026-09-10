"""
ATHER Incident Workflow — Production-Grade Persistent Service
================================================================

DETECT -> VALIDATE -> CORRELATE -> PERSIST -> EXPLAIN -> DIAGNOSE ->
RECOMMEND -> ACKNOWLEDGE -> INVESTIGATE -> ESCALATE -> RESOLVE

This module is a LEAF module: it does not import app.stations.service or
app.anomaly.detector. Callers (app/stations/service.py, app/main.py) build
a plain "evaluation snapshot" dict from the REAL anomaly-engine output and
hand it to `upsert_from_evaluation()`. This keeps the dependency graph
one-directional (stations/detector -> incidents, never the reverse) and
means this module never needs to know how a diagnosis was produced —
only what it says.

ANOMALY vs INCIDENT (Phase 2): a raw anomaly is a single evaluation. An
incident is a persistent operational record. `upsert_from_evaluation` is
the ONLY entry point that creates or updates incidents, and it always
correlates against the same (station, parameter, root cause) fingerprint
before ever inserting a new row — repeated detections of the same ongoing
condition update one incident; a fingerprint that has been explicitly
RESOLVED or DISMISSED starts a fresh incident on its next occurrence.

SIMULATION ISOLATION (Phase 29/36): every snapshot carries a `source`
field. TEST_SIMULATION incidents live in the exact same table (so the same
schema/tests/API apply) but are excluded from `list_all()` and from
`get_active_counts()` by default — a caller must explicitly ask for them.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .db import get_connection, dict_from_row, _write_lock

VALID_STATES = ["NEW", "ACKNOWLEDGED", "INVESTIGATING", "ESCALATED", "RESOLVED", "DISMISSED"]

# Phase 34: only these transitions are permitted. A state transitioning to
# itself (e.g. re-clicking Acknowledge) is always a harmless no-op, handled
# separately from this table.
VALID_TRANSITIONS: Dict[str, set] = {
    "NEW": {"ACKNOWLEDGED", "DISMISSED"},
    "ACKNOWLEDGED": {"INVESTIGATING", "DISMISSED"},
    "INVESTIGATING": {"ESCALATED", "RESOLVED", "DISMISSED"},
    "ESCALATED": {"RESOLVED", "DISMISSED"},
    "RESOLVED": set(),
    "DISMISSED": set(),
}

_SEVERITY_MAP = {"HIGH": "CRITICAL", "WARNING": "WARNING", "LOW": "INFO", "NONE": "INFO"}


class IncidentNotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(station_id: str, parameter: str, anomaly_type: str) -> str:
    return f"{station_id}::{parameter}::{anomaly_type}"


def _map_severity(raw: Optional[str]) -> str:
    return _SEVERITY_MAP.get((raw or "").upper(), "WARNING")


def _add_timeline(conn, incident_id: str, event: str, at: str, actor: Optional[str], note: Optional[str]) -> None:
    conn.execute(
        "INSERT INTO incident_timeline (incident_id, event, at, actor, note) VALUES (?, ?, ?, ?, ?)",
        (incident_id, event, at, actor, note),
    )


def _row_with_timeline(conn, incident_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
    if not row:
        return None
    d = dict_from_row(row)
    timeline_rows = conn.execute(
        "SELECT event, at, actor, note FROM incident_timeline WHERE incident_id = ? ORDER BY id ASC",
        (incident_id,),
    ).fetchall()
    d["timeline"] = [dict(r) for r in timeline_rows]
    return d


def get(incident_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    return _row_with_timeline(conn, incident_id)


def list_all(status: Optional[str] = None, source: str = "LIVE_AWS", station_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists incidents. `source` defaults to LIVE_AWS ONLY — a caller must
    explicitly pass source="TEST_SIMULATION" (or None for both) to ever see
    simulation records; production UI never does (Phase 36)."""
    conn = get_connection()
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if station_id:
        clauses.append("station_id = ?")
        params.append(station_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"SELECT * FROM incidents {where} ORDER BY updated_at DESC", params).fetchall()
    return [dict_from_row(r) for r in rows]


def get_active_counts(source: str = "LIVE_AWS") -> Dict[str, int]:
    """Real counts for the operational incident counter (Phase 24/43) —
    computed from persisted incident rows, not re-derived independently
    elsewhere."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT status, severity, COUNT(*) as n FROM incidents WHERE source = ? GROUP BY status, severity",
        (source,),
    ).fetchall()
    counts = {"active": 0, "critical": 0, "warning": 0, "investigating": 0, "escalated": 0, "acknowledged": 0, "new": 0}
    for r in rows:
        status, severity, n = r["status"], r["severity"], r["n"]
        if status not in ("RESOLVED", "DISMISSED"):
            counts["active"] += n
            if severity == "CRITICAL":
                counts["critical"] += n
            elif severity == "WARNING":
                counts["warning"] += n
        if status == "INVESTIGATING":
            counts["investigating"] += n
        elif status == "ESCALATED":
            counts["escalated"] += n
        elif status == "ACKNOWLEDGED":
            counts["acknowledged"] += n
        elif status == "NEW":
            counts["new"] += n
    return counts


def upsert_from_evaluation(snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    THE single entry point for turning a real diagnostic evaluation into a
    persistent incident. Callers pass a plain dict built from the ACTUAL
    anomaly-engine output (see app/stations/service.py's snapshot builders)
    — this function never invents evidence, it only decides whether the
    evidence it was given is actionable enough to persist, and whether it
    belongs to an already-open incident or a new one (Phase 3, 6).

    Returns None (no-op) when:
      - status is not WARNING/ANOMALY (Phase 3: never for NORMAL/OFFLINE/
        insufficient-evidence-only NORMAL results)
      - the observation source is NWP_MODEL_REFERENCE (Phase 3: never turn
        model reference data into an AWS sensor incident)
    """
    status = snapshot.get("status")
    if status not in ("WARNING", "ANOMALY"):
        return None
    if snapshot.get("obs_source") == "NWP_MODEL_REFERENCE":
        return None

    station_id = snapshot["station_id"]
    parameter = snapshot.get("parameter") or "Sensor Array"
    anomaly_type = snapshot.get("root_cause") or "UNKNOWN"
    incident_source = snapshot.get("source") or "LIVE_AWS"
    fp = _fingerprint(station_id, parameter, anomaly_type)
    severity = _map_severity(snapshot.get("severity"))
    now = _now()

    evidence_json = json.dumps(snapshot.get("evidence") or [])
    layers_json = json.dumps(snapshot["diagnostic_layers"]) if snapshot.get("diagnostic_layers") else None
    fusion_json = json.dumps(snapshot["fusion_result"]) if snapshot.get("fusion_result") else None

    conn = get_connection()
    with _write_lock:
        existing = conn.execute(
            """SELECT incident_id FROM incidents
               WHERE fingerprint = ? AND source = ? AND status NOT IN ('RESOLVED', 'DISMISSED')
               ORDER BY created_at DESC LIMIT 1""",
            (fp, incident_source),
        ).fetchone()

        if existing:
            incident_id = existing["incident_id"]
            conn.execute(
                """UPDATE incidents SET
                     last_seen_at = ?, observation_timestamp = ?, observed_value = ?,
                     anomaly_score = ?, confidence = ?, severity = ?,
                     root_cause_confidence = ?, recommended_action = ?,
                     evidence_json = ?, diagnostic_layers_json = ?, fusion_result_json = ?,
                     observation_count = observation_count + 1,
                     obs_source = ?, freshness = ?, updated_at = ?
                   WHERE incident_id = ?""",
                (
                    now, snapshot.get("observation_timestamp"), snapshot.get("observed_value"),
                    snapshot.get("anomaly_score"), snapshot.get("confidence"), severity,
                    snapshot.get("root_cause_confidence"), snapshot.get("recommended_action"),
                    evidence_json, layers_json, fusion_json,
                    snapshot.get("obs_source"), snapshot.get("freshness"), now,
                    incident_id,
                ),
            )
            conn.commit()
            return _row_with_timeline(conn, incident_id)

        incident_id = f"INC-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        conn.execute(
            """INSERT INTO incidents (
                 incident_id, fingerprint, station_id, station_name, town, region, country,
                 parameter, anomaly_type, source, status, severity,
                 detected_at, first_seen_at, last_seen_at, observation_timestamp,
                 observed_value, expected_min, expected_max, unit,
                 anomaly_score, confidence, root_cause, root_cause_confidence, recommended_action,
                 evidence_json, diagnostic_layers_json, fusion_result_json,
                 observation_count, obs_source, freshness, created_at, updated_at
               ) VALUES (?,?,?,?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?,?,?)""",
            (
                incident_id, fp, station_id, snapshot.get("station_name"), snapshot.get("town"),
                snapshot.get("region"), snapshot.get("country"),
                parameter, anomaly_type, incident_source, "NEW", severity,
                now, now, now, snapshot.get("observation_timestamp"),
                snapshot.get("observed_value"), snapshot.get("expected_min"), snapshot.get("expected_max"),
                snapshot.get("unit"),
                snapshot.get("anomaly_score"), snapshot.get("confidence"), anomaly_type,
                snapshot.get("root_cause_confidence"), snapshot.get("recommended_action"),
                evidence_json, layers_json, fusion_json,
                1, snapshot.get("obs_source"), snapshot.get("freshness"), now, now,
            ),
        )
        _add_timeline(conn, incident_id, "ANOMALY_DETECTED", now, None,
                       f"{parameter} anomaly detected at {station_id}.")
        _add_timeline(conn, incident_id, "INCIDENT_CREATED", now, None,
                       "Incident created from validated diagnostic evidence.")
        conn.commit()
        return _row_with_timeline(conn, incident_id)


def _transition(incident_id: str, new_status: str, actor: Optional[str], note: str,
                 extra_fields: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    conn = get_connection()
    with _write_lock:
        row = conn.execute("SELECT status FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        if not row:
            raise IncidentNotFoundError(incident_id)
        current = row["status"]
        if new_status != current and new_status not in VALID_TRANSITIONS.get(current, set()):
            raise InvalidTransitionError(f"Cannot transition incident from {current} to {new_status}")

        now = _now()
        fields = {"status": new_status, "updated_at": now}
        if extra_fields:
            fields.update(extra_fields)
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE incidents SET {set_clause} WHERE incident_id = ?", (*fields.values(), incident_id))
        _add_timeline(conn, incident_id, new_status, now, actor, note)
        conn.commit()
        return _row_with_timeline(conn, incident_id)


def acknowledge(incident_id: str, actor: Optional[str] = "operator") -> Dict[str, Any]:
    return _transition(
        incident_id, "ACKNOWLEDGED", actor, "Operator acknowledged the incident.",
        {"acknowledged_at": _now(), "acknowledged_by": actor},
    )


def investigate(incident_id: str, actor: Optional[str] = "operator") -> Dict[str, Any]:
    return _transition(
        incident_id, "INVESTIGATING", actor, "Operator marked the incident under investigation.",
        {"investigated_at": _now(), "investigated_by": actor},
    )


def escalate(incident_id: str, actor: Optional[str] = "operator") -> Dict[str, Any]:
    return _transition(
        incident_id, "ESCALATED", actor,
        "Escalation preview marked as escalated by operator (no external message was sent).",
        {"escalated_at": _now(), "escalated_by": actor},
    )


def resolve(incident_id: str, actor: Optional[str], resolution_notes: str, resolution_type: str) -> Dict[str, Any]:
    if not resolution_notes or not resolution_notes.strip():
        raise ValueError("resolution_notes is required to resolve an incident.")
    if not resolution_type:
        raise ValueError("resolution_type is required to resolve an incident.")
    return _transition(
        incident_id, "RESOLVED", actor, f"Resolved: {resolution_type} — {resolution_notes}",
        {
            "resolved_at": _now(), "resolved_by": actor,
            "resolution_notes": resolution_notes, "resolution_type": resolution_type,
        },
    )


def dismiss(incident_id: str, actor: Optional[str], dismissal_reason: str) -> Dict[str, Any]:
    if not dismissal_reason or not dismissal_reason.strip():
        raise ValueError("dismissal_reason is required to dismiss an incident.")
    return _transition(
        incident_id, "DISMISSED", actor, f"Dismissed: {dismissal_reason}",
        {"dismissed_at": _now(), "dismissed_by": actor, "dismissal_reason": dismissal_reason},
    )


def build_escalation_preview(incident_id: str) -> Optional[Dict[str, Any]]:
    """Read-only — never mutates the incident. See escalate() for the
    actual state transition triggered by "Mark Escalated" (Phase 17)."""
    inc = get(incident_id)
    if not inc:
        return None
    expected_str = (
        f"{inc['expected_min']}-{inc['expected_max']} {inc.get('unit', '')}".strip()
        if inc.get("expected_min") is not None and inc.get("expected_max") is not None else "N/A"
    )
    location = ", ".join(p for p in [inc.get("town"), inc.get("country")] if p) or "Unknown location"
    return {
        "recipient": "Meteorological Operations Team",
        "subject": f"{inc['severity']} AWS anomaly — {inc['incident_id']} ({inc['station_id']})",
        "incident_id": inc["incident_id"],
        "station_id": inc["station_id"],
        "station_name": inc.get("station_name"),
        "location": location,
        "affected_parameter": inc.get("parameter"),
        "observed": f"{inc.get('observed_value')} {inc.get('unit', '')}".strip() if inc.get("observed_value") is not None else "N/A",
        "expected": expected_str,
        "severity": inc.get("severity"),
        "confidence_pct": round((inc.get("confidence") or 0.0) * 100),
        "root_cause": inc.get("root_cause"),
        "evidence": inc.get("evidence") or [],
        "recommended_action": inc.get("recommended_action"),
        "is_preview_only": True,
        "note": "This is a preview only. ATHER has not contacted any external recipient.",
    }
