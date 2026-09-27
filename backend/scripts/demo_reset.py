"""
Simulation reset for a clean demo — ARCHIVES, never deletes.

Moves the local incidents and time-series databases (and their WAL/SHM
files) to data/archive/<timestamp>/ so the next backend start begins from an
empty store and the simulated network is re-warmed by the start-up warm-up
(ATHER_SIM_WARMUP_CYCLES). Earlier incidents stay available in the archive.

Run with the backend STOPPED:   python scripts/demo_reset.py
"""
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.incidents.db import _resolve_db_path as get_db_path  # noqa: E402
from app.pipeline.store import _resolve_path as ts_path  # noqa: E402

paths = [Path(get_db_path()), Path(ts_path())]
dest = paths[0].parent / "archive" / time.strftime("%Y%m%d-%H%M%S")
moved = []
for p in paths:
    for f in (p, Path(f"{p}-wal"), Path(f"{p}-shm")):
        if f.exists():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), dest / f.name)
            moved.append(f.name)
print(f"Simulation reset: archived {moved or 'nothing (no databases found)'}" + (f" to {dest}" if moved else ""))
print("Start the backend; the simulated network warms up before stations join the live feed.")
