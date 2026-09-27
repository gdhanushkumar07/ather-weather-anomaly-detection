"""Shared small utilities for Stage 2 (seeding, device selection)."""
import random

import numpy as np
import torch


def set_seed(seed: int) -> None:
    """Seeds Python's random, NumPy, and PyTorch for reproducibility.

    Deliberately does NOT use Python's built-in hash() anywhere in this
    package for ordering/seeding — str hash() is per-process salted
    (PYTHONHASHSEED) and would silently break determinism across runs.
    """
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def get_device() -> torch.device:
    # CPU-only per the Stage 2 environment (no CUDA available) — kept as a
    # function rather than a hardcoded literal so a future GPU environment
    # doesn't require touching call sites.
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")
