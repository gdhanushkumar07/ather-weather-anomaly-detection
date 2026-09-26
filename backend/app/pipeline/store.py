"""
TimeSeriesStore — raw observations + detection results (SQLite, WAL).

Why SQLite and not PostgreSQL/TimescaleDB right now: the project already
uses stdlib sqlite3 for incidents, there is no database server in the
target environment, and the measured write load is small (a 5,000-station
network at a 5-minute cadence is ~17 observations/s; one WAL-mode SQLite
writer sustains thousands of inserts/s in batched transactions). The class
boundary is the migration seam: a TimescaleStore implementing the same
methods maps `observations`/`detections` to hypertables, `history()`'s
bucketing to time_bucket() / continuous aggregates, and `prune()` to a
retention policy.

Write discipline: only the pipeline worker thread writes (batched, one
transaction per micro-batch). API threads read through their own
thread-local connections, which WAL allows concurrently with the writer.
"""
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/
_DEFAULT_PATH = BASE_DIR.parent / "data" / "ather_timeseries.db"

_OBS_COLUMNS = ("temperature", "humidity", "pressure", "wind_speed", "wind_direction", "rainfall", "dew_point")


def _resolve_path() -> Path:
    override = os.environ.get("ATHER_TIMESERIES_DB_PATH")
    return Path(override) if override else _DEFAULT_PATH


class TimeSeriesStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else _resolve_path()
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema(self._conn())

    # ── connections ──────────────────────────────────────────────────────
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._local.conn = conn
        return conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS observations (
                observation_id TEXT PRIMARY KEY,
                station_id     TEXT NOT NULL,
                observed_at    REAL NOT NULL,
                received_at    REAL NOT NULL,
                source         TEXT NOT NULL,
                adapter        TEXT,
                temperature    REAL,
                humidity       REAL,
                pressure       REAL,
                wind_speed     REAL,
                wind_direction REAL,
                rainfall       REAL,
                dew_point      REAL,
                flags          TEXT,
                late           INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_obs_station_time ON observations(station_id, observed_at);
            CREATE INDEX IF NOT EXISTS idx_obs_time ON observations(observed_at);

            CREATE TABLE IF NOT EXISTS detections (
                detection_id     TEXT PRIMARY KEY,
                observation_id   TEXT NOT NULL,
                station_id       TEXT NOT NULL,
                observed_at      REAL NOT NULL,
                processed_at     REAL NOT NULL,
                overall_status   TEXT NOT NULL,
                engine_status    TEXT NOT NULL,
                confidence       REAL,
                anomaly_score    REAL,
                severity         TEXT,
                root_cause       TEXT,
                triggered_layers TEXT,
                layer_scores     TEXT,
                incident_id      TEXT,
                processing_ms    REAL,
                detail           TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_det_station_time ON detections(station_id, observed_at);
            CREATE INDEX IF NOT EXISTS idx_det_time ON detections(observed_at);
            """
        )
        conn.commit()

    # ── writes (pipeline worker thread) ─────────────────────────────────
    def observation_exists(self, observation_id: str) -> bool:
        row = self._conn().execute(
            "SELECT 1 FROM observations WHERE observation_id = ?", (observation_id,)
        ).fetchone()
        return row is not None

    def write_batch(
        self,
        observations: Iterable[Dict[str, Any]],
        detections: Iterable[Dict[str, Any]],
    ) -> int:
        """Inserts observations (INSERT OR IGNORE — idempotent on
        observation_id) and detections in ONE transaction. Returns the
        number of observation rows actually inserted."""
        conn = self._conn()
        obs_rows = [
            (
                o["observation_id"], o["station_id"], o["observed_at"], o["received_at"],
                o["source"], o.get("adapter"),
                *[o["values"].get(c) for c in _OBS_COLUMNS],
                json.dumps(o.get("flags") or []), 1 if o.get("late") else 0,
            )
            for o in observations
        ]
        det_rows = [
            (
                d["detection_id"], d["observation_id"], d["station_id"], d["observed_at"], d["processed_at"],
                d["overall_status"], d["engine_status"], d.get("confidence"), d.get("anomaly_score"),
                d.get("severity"), d.get("root_cause"), json.dumps(d.get("triggered_layers") or []),
                json.dumps(d.get("layer_scores") or {}), d.get("incident_id"), d.get("processing_ms"),
                json.dumps(d.get("detail")) if d.get("detail") is not None else None,
            )
            for d in detections
        ]
        with self._write_lock:
            before = conn.total_changes
            conn.executemany(
                f"""INSERT OR IGNORE INTO observations (
                      observation_id, station_id, observed_at, received_at, source, adapter,
                      {", ".join(_OBS_COLUMNS)}, flags, late
                    ) VALUES (?,?,?,?,?,?,{",".join("?" * len(_OBS_COLUMNS))},?,?)""",
                obs_rows,
            )
            inserted = conn.total_changes - before
            conn.executemany(
                """INSERT OR REPLACE INTO detections (
                      detection_id, observation_id, station_id, observed_at, processed_at,
                      overall_status, engine_status, confidence, anomaly_score, severity, root_cause,
                      triggered_layers, layer_scores, incident_id, processing_ms, detail
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                det_rows,
            )
            conn.commit()
        return inserted

    def prune(self, older_than_epoch: float) -> Tuple[int, int]:
        conn = self._conn()
        with self._write_lock:
            o = conn.execute("DELETE FROM observations WHERE observed_at < ?", (older_than_epoch,)).rowcount
            d = conn.execute("DELETE FROM detections WHERE observed_at < ?", (older_than_epoch,)).rowcount
            conn.commit()
        return o, d

    # ── reads (any thread) ──────────────────────────────────────────────
    def history(
        self,
        station_id: str,
        since: float,
        until: Optional[float] = None,
        max_points: int = 360,
    ) -> List[Dict[str, Any]]:
        """Observations in [since, until], downsampled by time-bucket
        averaging when there are more than max_points rows. Wind direction
        is averaged as a vector-free approximation (last value per bucket)
        to avoid the 359°/1° averaging artefact."""
        until = until or time.time()
        conn = self._conn()
        n = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE station_id = ? AND observed_at BETWEEN ? AND ?",
            (station_id, since, until),
        ).fetchone()[0]
        if n <= max_points:
            rows = conn.execute(
                f"""SELECT observed_at, source, {", ".join(_OBS_COLUMNS)}, late FROM observations
                    WHERE station_id = ? AND observed_at BETWEEN ? AND ? ORDER BY observed_at""",
                (station_id, since, until),
            ).fetchall()
            return [dict(r) | {"samples": 1} for r in rows]
        bucket = max(1.0, (until - since) / max_points)
        rows = conn.execute(
            """SELECT CAST((observed_at - ?) / ? AS INTEGER) AS b,
                      MAX(observed_at) AS observed_at, MAX(source) AS source,
                      AVG(temperature) AS temperature, AVG(humidity) AS humidity,
                      AVG(pressure) AS pressure, AVG(wind_speed) AS wind_speed,
                      MAX(wind_direction) AS wind_direction, SUM(rainfall) AS rainfall,
                      AVG(dew_point) AS dew_point, MAX(late) AS late, COUNT(*) AS samples
               FROM observations WHERE station_id = ? AND observed_at BETWEEN ? AND ?
               GROUP BY b ORDER BY b""",
            (since, bucket, station_id, since, until),
        ).fetchall()
        return [{k: r[k] for k in r.keys() if k != "b"} for r in rows]

    def observations_between(self, station_ids: List[str], since: float, until: float) -> List[Dict[str, Any]]:
        if not station_ids:
            return []
        marks = ",".join("?" * len(station_ids))
        rows = self._conn().execute(
            f"""SELECT observation_id, station_id, observed_at, source, {", ".join(_OBS_COLUMNS)}
                FROM observations WHERE station_id IN ({marks}) AND observed_at BETWEEN ? AND ? AND late = 0
                ORDER BY observed_at""",
            (*station_ids, since, until),
        ).fetchall()
        return [dict(r) for r in rows]

    def detections(self, station_id: str, since: float, limit: int = 1000) -> List[Dict[str, Any]]:
        rows = self._conn().execute(
            """SELECT detection_id, observation_id, observed_at, processed_at, overall_status, engine_status,
                      confidence, anomaly_score, severity, root_cause, triggered_layers, layer_scores,
                      incident_id, processing_ms
               FROM detections WHERE station_id = ? AND observed_at >= ?
               ORDER BY observed_at DESC LIMIT ?""",
            (station_id, since, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["triggered_layers"] = json.loads(d["triggered_layers"] or "[]")
            d["layer_scores"] = json.loads(d["layer_scores"] or "{}")
            out.append(d)
        return out[::-1]

    def detection(self, detection_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn().execute("SELECT detail FROM detections WHERE detection_id = ?", (detection_id,)).fetchone()
        if not row or not row["detail"]:
            return None
        return json.loads(row["detail"])

    def latest_detection(self, station_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn().execute(
            "SELECT detail FROM detections WHERE station_id = ? ORDER BY observed_at DESC LIMIT 1", (station_id,)
        ).fetchone()
        return json.loads(row["detail"]) if row and row["detail"] else None

    def latest_observations(self, since: Optional[float] = None) -> List[Dict[str, Any]]:
        """Most recent observation per station (used to seed state on restart)."""
        since = since or 0.0
        rows = self._conn().execute(
            f"""SELECT o.* FROM observations o
                JOIN (SELECT station_id, MAX(observed_at) AS m FROM observations
                      WHERE late = 0 AND observed_at >= ? GROUP BY station_id) x
                  ON o.station_id = x.station_id AND o.observed_at = x.m""",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]

    def recent_station_observations(self, station_id: str, limit: int) -> List[Dict[str, Any]]:
        rows = self._conn().execute(
            f"""SELECT observation_id, observed_at, source, {", ".join(_OBS_COLUMNS)} FROM observations
                WHERE station_id = ? AND late = 0 ORDER BY observed_at DESC LIMIT ?""",
            (station_id, limit),
        ).fetchall()
        return [dict(r) for r in rows][::-1]

    def stats(self) -> Dict[str, Any]:
        conn = self._conn()
        obs = conn.execute("SELECT COUNT(*), MIN(observed_at), MAX(observed_at) FROM observations").fetchone()
        det = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
        size = 0
        for suffix in ("", "-wal"):
            p = Path(str(self.path) + suffix)
            if p.exists():
                size += p.stat().st_size
        return {
            "backend": "SQLite (WAL)",
            "path": self.path.name,
            "observations": obs[0],
            "detections": det,
            "oldest_observation": obs[1],
            "newest_observation": obs[2],
            "size_mb": round(size / 1e6, 1),
        }

    def ping(self) -> bool:
        try:
            self._conn().execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False
