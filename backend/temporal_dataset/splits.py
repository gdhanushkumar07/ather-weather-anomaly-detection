"""
Deterministic, station-level train/validation/test split.

Splitting happens on the STATION list, before any sequence/window is
generated, so no station's data can ever appear in more than one split
(the leakage guard required by the Stage 1 design). Row-level or
window-level splitting is intentionally NOT done here.
"""
from typing import Any, Dict, List, Tuple

import numpy as np

from .config import TemporalGeneratorConfig


def assign_station_splits(
    selected_stations: List[Dict[str, Any]],
    cfg: TemporalGeneratorConfig,
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """
    Returns (station_id -> split_name, report).
    split_name is one of "train", "val", "test".
    """
    ids = sorted(str(s.get("id")) for s in selected_stations)
    n = len(ids)

    # Independent seed derived from the same global seed so this shuffle
    # doesn't correlate with the station-selection permutation in
    # station_selection.py — both remain individually deterministic.
    rng = np.random.default_rng(cfg.seed + 1)
    perm = rng.permutation(n)
    shuffled_ids = [ids[i] for i in perm]

    n_train = int(round(n * cfg.train_ratio))
    n_val = int(round(n * cfg.val_ratio))
    # Remainder goes to test so counts always sum to n exactly.
    n_test = n - n_train - n_val

    train_ids = shuffled_ids[:n_train]
    val_ids = shuffled_ids[n_train:n_train + n_val]
    test_ids = shuffled_ids[n_train + n_val:]

    assignment: Dict[str, str] = {}
    for sid in train_ids:
        assignment[sid] = "train"
    for sid in val_ids:
        assignment[sid] = "val"
    for sid in test_ids:
        assignment[sid] = "test"

    report = {
        "total_stations": n,
        "train_stations": len(train_ids),
        "val_stations": len(val_ids),
        "test_stations": len(test_ids),
    }
    return assignment, report
