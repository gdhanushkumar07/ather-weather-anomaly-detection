"""Shared small utilities for Stage 3 (deterministic per-scenario RNG)."""
import zlib

import numpy as np


def scenario_rng(global_seed: int, station_id: str, anomaly_type: str, injection_index: int) -> np.random.Generator:
    """
    Deterministic per-scenario RNG. Uses zlib.crc32 (a stable hash) rather
    than Python's built-in hash() — string hash() is per-process salted
    (PYTHONHASHSEED) and would silently break cross-run determinism, the
    same pitfall already avoided in temporal_dataset/sequence_generator.py.
    """
    key = f"{station_id}:{anomaly_type}:{injection_index}".encode("utf-8")
    stable_hash = zlib.crc32(key)
    seed_seq = np.random.SeedSequence([global_seed, stable_hash])
    return np.random.default_rng(seed_seq)
