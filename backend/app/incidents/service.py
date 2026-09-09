"""
ATHER Incident Workflow (Phase 13-15)
======================================
Extends "ANOMALY DETECTED" into a real operator workflow:

  ANOMALY DETECTED -> VALIDATED -> FUSED -> ROOT CAUSE -> SEVERITY ->
  RECOMMENDED ACTION -> INCIDENT -> ACKNOWLEDGE -> INVESTIGATE -> RESOLVE

This is an in-memory incident ledger (matches the project's existing
in-memory station/detector state pattern — no new infra dependency).
Incident state is NEVER auto-resolved by the engine; only explicit operator
actions (acknowledge/investigate/resolve/dismiss) change it.

Escalation is a PREVIEW ONLY (Phase 15): ATHER never sends a real email/SMS
here. "Mark as Escalated" records the operator's decision in the incident's
own audit trail — it does not contact any external system.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.stations.service import station_service

VALID_STATES = ["NEW", "ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "DISMISSED"]


class IncidentStore:
    def __init__(self):
        self._incidents: Dict[str, Dict[str, Any]] = {}

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _snapshot_from_station(self, station_id: str) -> Optional[Dict[str, Any]]:
        stn = station_service.get_station(station_id)
        if not stn:
            return None
        result = station_service.get_station_anomaly(station_id)
        if not result:
            return None
        legacy_anomaly = stn.get("anomaly") or {}
        return {
            "station_id": station_id,
            "station_name": stn.get("name"),
            "town": stn.get("town"),
            "region": stn.get("region"),
            "country": stn.get("country"),
            "parameter": legacy_anomaly.get("parameter", "Sensor Array"),
            "observed": legacy_anomaly.get("observed"),
            "expected_min": legacy_anomaly.get("expectedMin"),
            "expected_max": legacy_anomaly.get("expectedMax"),
            "unit": legacy_anomaly.get("unit", ""),
            "severity": result["overall"]["severity"] if "overall" in result else "NONE",
            "confidence": result.get("confidence", 0.0),
            "root_cause": result.get("root_cause", "UNKNOWN"),
            "evidence": result.get("reasons", []),
            "recommended_action": result.get("operator_action", ""),
            "status": result.get("status", "NORMAL"),
        }

    def get_or_create(self, station_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns the current incident for a station. If the station currently
        shows an ANOMALY/WARNING and no OPEN incident exists yet, a NEW
        incident is created from the current diagnostic snapshot. Existing
        open incidents are never silently overwritten or auto-resolved — only
        their read-only "latest observation" snapshot is refreshed so the UI
        can show current values without losing operator-tracked state.
        """
        snapshot = self._snapshot_from_station(station_id)
        if not snapshot:
            return self._incidents.get(station_id)

        existing = self._incidents.get(station_id)
        is_actionable = snapshot["status"] in ("ANOMALY", "WARNING")

        if existing and existing["state"] not in ("RESOLVED", "DISMISSED"):
            # Refresh the read-only snapshot fields, preserve workflow state/history.
            existing["latest_snapshot"] = snapshot
            existing["updated_at"] = self._now()
            return existing

        if not is_actionable:
            return existing  # nothing new to report; keep prior record (may be resolved/dismissed) as-is

        # A previously resolved/dismissed incident whose condition has
        # recurred, or a brand-new one, gets a fresh incident record.
        incident = {
            "incident_id": f"INC-{station_id}-{uuid.uuid4().hex[:8]}",
            "station_id": station_id,
            "state": "NEW",
            "created_at": self._now(),
            "updated_at": self._now(),
            "initial_snapshot": snapshot,
            "latest_snapshot": snapshot,
            "escalated": False,
            "escalated_at": None,
            "history": [{"state": "NEW", "at": self._now(), "note": "Incident created from diagnostic evidence."}],
        }
        self._incidents[station_id] = incident
        return incident

    def _transition(self, station_id: str, new_state: str, note: str) -> Optional[Dict[str, Any]]:
        incident = self.get_or_create(station_id)
        if not incident:
            return None
        incident["state"] = new_state
        incident["updated_at"] = self._now()
        incident["history"].append({"state": new_state, "at": self._now(), "note": note})
        return incident

    def acknowledge(self, station_id: str) -> Optional[Dict[str, Any]]:
        return self._transition(station_id, "ACKNOWLEDGED", "Operator acknowledged the incident.")

    def investigate(self, station_id: str) -> Optional[Dict[str, Any]]:
        return self._transition(station_id, "INVESTIGATING", "Operator marked the incident under investigation.")

    def resolve(self, station_id: str) -> Optional[Dict[str, Any]]:
        return self._transition(station_id, "RESOLVED", "Operator marked the incident resolved.")

    def dismiss(self, station_id: str) -> Optional[Dict[str, Any]]:
        return self._transition(station_id, "DISMISSED", "Operator dismissed the incident (not a genuine fault).")

    def build_escalation_preview(self, station_id: str) -> Optional[Dict[str, Any]]:
        incident = self.get_or_create(station_id)
        if not incident:
            return None
        snap = incident["latest_snapshot"]
        observed = snap.get("observed")
        expected_min = snap.get("expected_min")
        expected_max = snap.get("expected_max")
        expected_str = (
            f"{expected_min}-{expected_max} {snap.get('unit', '')}".strip()
            if expected_min is not None and expected_max is not None else "N/A"
        )
        # `town` already includes locality/city/region/country — don't repeat region.
        location = snap.get("town") or "Unknown location"
        return {
            "recipient": "Meteorological Operations Team",
            "subject": f"{'CRITICAL' if snap['severity'] == 'HIGH' else snap['severity']} AWS anomaly — {station_id}",
            "station_id": station_id,
            "station_name": snap.get("station_name"),
            "location": location,
            "affected_parameter": snap.get("parameter"),
            "observed": f"{observed} {snap.get('unit', '')}".strip() if observed is not None else "N/A",
            "expected": expected_str,
            "severity": snap.get("severity"),
            "confidence_pct": round(snap.get("confidence", 0.0) * 100),
            "root_cause": snap.get("root_cause"),
            "evidence": snap.get("evidence", []),
            "recommended_action": snap.get("recommended_action"),
            "is_preview_only": True,
            "note": "This is a preview only. ATHER has not contacted any external recipient.",
        }

    def list_all(self, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists tracked incident records (Anomalies workspace Active/Resolved/All
        tabs). Only stations with an OPEN or previously-tracked incident appear
        here — this never scans/fabricates incidents for stations that were
        never actionable."""
        records = list(self._incidents.values())
        if state:
            records = [r for r in records if r["state"] == state]
        records.sort(key=lambda r: r["updated_at"], reverse=True)
        return records

    def mark_escalated(self, station_id: str) -> Optional[Dict[str, Any]]:
        incident = self.get_or_create(station_id)
        if not incident:
            return None
        incident["escalated"] = True
        incident["escalated_at"] = self._now()
        incident["history"].append({
            "state": incident["state"], "at": self._now(),
            "note": "Escalation preview marked as escalated by operator (no external message was sent).",
        })
        return incident


incident_store = IncidentStore()
