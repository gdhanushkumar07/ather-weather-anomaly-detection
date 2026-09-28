"""
Maintenance work orders raised from an incident.

A work order is the ACTION step of the incident lifecycle: an operator raises
it from a real incident, then moves it Created -> Assigned -> In progress ->
Completed. Every step is recorded on the incident's own timeline. Completing
a work order never resolves the incident by itself — the operator still
resolves it through the incident lifecycle.
"""
from typing import Any, Dict, List, Optional

from .db import _write_lock, dict_from_row, get_connection
from .service import IncidentNotFoundError, InvalidTransitionError, _add_timeline, _now, get as get_incident

WO_STATES = ["CREATED", "ASSIGNED", "IN_PROGRESS", "COMPLETED"]
PRIORITIES = ["LOW", "MEDIUM", "HIGH", "URGENT"]
_CLOSED_INCIDENT = ("RESOLVED", "DISMISSED")
_EVENT = {"CREATED": "WORK_ORDER_CREATED", "ASSIGNED": "WORK_ORDER_ASSIGNED",
          "IN_PROGRESS": "WORK_ORDER_IN_PROGRESS", "COMPLETED": "WORK_ORDER_COMPLETED"}


class WorkOrderNotFoundError(Exception):
    pass


def _get(conn, wo_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM work_orders WHERE work_order_id = ?", (wo_id,)).fetchone()
    return dict_from_row(row) if row else None


def list_for_incident(incident_id: str) -> List[Dict[str, Any]]:
    rows = get_connection().execute(
        "SELECT * FROM work_orders WHERE incident_id = ? ORDER BY created_at ASC", (incident_id,)).fetchall()
    return [dict_from_row(r) for r in rows]


def create(incident_id: str, issue: str, priority: str, team: str,
           actor: Optional[str] = "operator", notes: Optional[str] = None) -> Dict[str, Any]:
    inc = get_incident(incident_id)
    if not inc:
        raise IncidentNotFoundError(incident_id)
    if inc["status"] in _CLOSED_INCIDENT:
        raise InvalidTransitionError(f"Incident {incident_id} is {inc['status']}; work orders can only be raised on open incidents.")
    priority = (priority or "").upper()
    if priority not in PRIORITIES:
        raise InvalidTransitionError(f"priority must be one of {PRIORITIES}")
    if not (issue or "").strip() or not (team or "").strip():
        raise InvalidTransitionError("issue and team are required")
    conn = get_connection()
    with _write_lock:
        if any(w["status"] != "COMPLETED" for w in list_for_incident(incident_id)):
            raise InvalidTransitionError("This incident already has an open work order.")
        n = conn.execute("SELECT COUNT(*) FROM work_orders WHERE incident_id = ?", (incident_id,)).fetchone()[0]
        wo_id = "WO-" + incident_id.replace("INC-", "") + (f"-{n + 1}" if n else "")
        now = _now()
        conn.execute(
            "INSERT INTO work_orders (work_order_id, incident_id, station_id, issue, priority, team, status, notes, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'CREATED', ?, ?, ?)",
            (wo_id, incident_id, inc["station_id"], issue.strip(), priority, team.strip(), notes, now, now))
        _add_timeline(conn, incident_id, "WORK_ORDER_CREATED", now, actor,
                      f"{wo_id} created — {issue.strip()} (priority {priority.lower()}, team {team.strip()}).")
        conn.execute("UPDATE incidents SET updated_at = ? WHERE incident_id = ?", (now, incident_id))
        conn.commit()
        return _get(conn, wo_id)


def advance(wo_id: str, to_status: str, actor: Optional[str] = "operator",
            assignee: Optional[str] = None, note: Optional[str] = None) -> Dict[str, Any]:
    conn = get_connection()
    to_status = (to_status or "").upper()
    with _write_lock:
        wo = _get(conn, wo_id)
        if not wo:
            raise WorkOrderNotFoundError(wo_id)
        if to_status not in WO_STATES or WO_STATES.index(to_status) != WO_STATES.index(wo["status"]) + 1:
            raise InvalidTransitionError(f"Work order {wo_id} is {wo['status']}; next allowed state is "
                                         f"{WO_STATES[WO_STATES.index(wo['status']) + 1] if wo['status'] != 'COMPLETED' else 'none'}.")
        if to_status == "ASSIGNED" and not (assignee or wo.get("assignee")):
            raise InvalidTransitionError("An assignee is required to assign a work order.")
        now = _now()
        conn.execute(
            "UPDATE work_orders SET status = ?, assignee = COALESCE(?, assignee), updated_at = ?, "
            "completed_at = CASE WHEN ? = 'COMPLETED' THEN ? ELSE completed_at END, "
            "notes = CASE WHEN ? IS NOT NULL THEN COALESCE(notes || char(10), '') || ? ELSE notes END "
            "WHERE work_order_id = ?",
            (to_status, assignee, now, to_status, now, note, note, wo_id))
        detail = {"ASSIGNED": f"{wo_id} assigned to {assignee or wo.get('assignee')}.",
                  "IN_PROGRESS": f"{wo_id} work started.",
                  "COMPLETED": f"{wo_id} completed."}[to_status]
        _add_timeline(conn, wo["incident_id"], _EVENT[to_status], now, actor, detail + (f" {note}" if note else ""))
        conn.execute("UPDATE incidents SET updated_at = ? WHERE incident_id = ?", (now, wo["incident_id"]))
        conn.commit()
        return _get(conn, wo_id)
