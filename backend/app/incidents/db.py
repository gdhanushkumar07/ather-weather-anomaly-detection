"""
ATHER Incident Persistence — SQLite
=====================================
The project has NO existing database technology (audited: no sqlite3/
SQLAlchemy/pymongo/psycopg usage anywhere, only in-memory dicts and ad-hoc
JSON-file caches such as app/weather/.weather_cache.json). Phase 30 of the
incident-workflow spec explicitly permits SQLite as a safe default when no
existing database can be reused, and forbids introducing a new external
database technology otherwise — so this uses Python's stdlib `sqlite3`
module: zero new dependencies, a real relational database, and adequate
for a single-process FastAPI deployment.

The database file lives next to the other on-disk project data
(backend/../data/incidents.db), mirroring the existing convention used by
app/stations/service.py's DATA_PATH for data/stations.json.

This module is intentionally a LEAF module: it does not import
app.stations.service or app.anomaly.detector, so app/stations/service.py
can safely import *this* module without creating a circular import.
"""
import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parents[2]  # backend directory
_DEFAULT_DB_PATH = BASE_DIR.parent / "data" / "incidents.db"

_local = threading.local()
_write_lock = threading.Lock()  # sqlite3 connections are not thread-safe for concurrent writes


def _resolve_db_path() -> Path:
    """Tests set ATHER_INCIDENTS_DB_PATH to an isolated temp file so they
    never read or clobber real accumulated incident data."""
    override = os.environ.get("ATHER_INCIDENTS_DB_PATH")
    return Path(override) if override else _DEFAULT_DB_PATH


def get_connection() -> sqlite3.Connection:
    """One connection per thread (FastAPI's default sync route handlers run
    on a small thread pool) — sqlite3 connections must not be shared across
    threads without check_same_thread=False, which we avoid here."""
    conn = getattr(_local, "conn", None)
    db_path = _resolve_db_path()
    cached_path = getattr(_local, "conn_path", None)
    if conn is not None and cached_path != str(db_path):
        conn.close()
        conn = None
    if conn is None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        _local.conn = conn
        _local.conn_path = str(db_path)
        _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id            TEXT PRIMARY KEY,
            fingerprint            TEXT NOT NULL,
            station_id             TEXT NOT NULL,
            station_name           TEXT,
            town                   TEXT,
            region                 TEXT,
            country                TEXT,

            parameter              TEXT,
            anomaly_type           TEXT,

            source                 TEXT NOT NULL DEFAULT 'LIVE_AWS',
            status                 TEXT NOT NULL DEFAULT 'NEW',
            severity               TEXT,

            detected_at            TEXT NOT NULL,
            first_seen_at          TEXT NOT NULL,
            last_seen_at           TEXT NOT NULL,
            observation_timestamp  TEXT,

            observed_value         REAL,
            expected_min           REAL,
            expected_max           REAL,
            unit                   TEXT,

            anomaly_score          REAL,
            confidence             REAL,

            root_cause             TEXT,
            root_cause_confidence  TEXT,
            recommended_action     TEXT,

            evidence_json          TEXT,
            diagnostic_layers_json TEXT,
            fusion_result_json     TEXT,

            observation_count      INTEGER NOT NULL DEFAULT 1,
            obs_source             TEXT,
            freshness              TEXT,

            acknowledged_at        TEXT,
            acknowledged_by        TEXT,
            investigated_at        TEXT,
            investigated_by        TEXT,
            escalated_at           TEXT,
            escalated_by           TEXT,
            resolved_at            TEXT,
            resolved_by            TEXT,
            resolution_notes       TEXT,
            resolution_type        TEXT,
            dismissed_at           TEXT,
            dismissed_by           TEXT,
            dismissal_reason       TEXT,

            created_at             TEXT NOT NULL,
            updated_at             TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_incidents_fingerprint ON incidents(fingerprint, status);
        CREATE INDEX IF NOT EXISTS idx_incidents_station ON incidents(station_id);
        CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
        CREATE INDEX IF NOT EXISTS idx_incidents_source ON incidents(source);

        CREATE TABLE IF NOT EXISTS incident_timeline (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id   TEXT NOT NULL,
            event         TEXT NOT NULL,
            at            TEXT NOT NULL,
            actor         TEXT,
            note          TEXT,
            FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
        );

        CREATE INDEX IF NOT EXISTS idx_timeline_incident ON incident_timeline(incident_id);
        """
    )
    conn.commit()


def dict_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    for json_field in ("evidence_json", "diagnostic_layers_json", "fusion_result_json"):
        raw = d.pop(json_field, None)
        key = json_field[: -len("_json")]
        if raw:
            try:
                d[key] = json.loads(raw)
            except (TypeError, ValueError):
                d[key] = None
        else:
            d[key] = None
    return d


def reset_for_tests() -> None:
    """Test-only helper: drops and recreates the schema on the CURRENT
    thread's connection. Never called from production code paths."""
    conn = get_connection()
    conn.executescript("DROP TABLE IF EXISTS incident_timeline; DROP TABLE IF EXISTS incidents;")
    conn.commit()
    _init_schema(conn)
