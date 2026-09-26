"""
Standalone Stage 2 inference utility.

Given the previous 144 (temperature_c, pressure_hpa, relative_humidity_pct)
observations (with timestamps) for ONE station, predicts the next 10-minute
reading in physical units.

Deliberately kept separate from the production temporal anomaly engine
(engine/layer2_temporal.py) — nothing here is imported by, or imports from,
the existing 5-layer engine. This is a Stage 2 standalone artifact only.
"""
import pickle
from pathlib import Path
from typing import Dict, Optional, Union

import numpy as np
import pandas as pd
import torch

from .config import TemporalLSTMConfig
from .dataset import add_time_features
from .model import TemporalLSTM
from .utils import get_device


class TemporalLSTMPredictor:
    """Loads a trained Stage 2 model + scaler once, then serves repeated
    next-step predictions without reloading from disk each call."""

    def __init__(self, model_dir: Optional[Union[str, Path]] = None):
        cfg = TemporalLSTMConfig()
        self.model_dir = Path(model_dir) if model_dir else cfg.output_dir

        import json
        with open(self.model_dir / cfg.config_filename) as f:
            saved = json.load(f)
        cfg.sequence_length = saved["sequence_length"]
        cfg.hidden_size = saved["hidden_size"]
        cfg.num_layers = saved["num_layers"]
        cfg.feature_columns = saved["feature_columns"]
        cfg.target_columns = saved["target_columns"]
        cfg.scale_columns = saved["scale_columns"]
        self.cfg = cfg

        with open(self.model_dir / cfg.scaler_filename, "rb") as f:
            self.scaler = pickle.load(f)

        self.device = get_device()
        self.model = TemporalLSTM.from_config(cfg).to(self.device)
        self.model.load_state_dict(torch.load(self.model_dir / cfg.model_filename, map_location=self.device))
        self.model.eval()

    def predict_next(self, history_df: pd.DataFrame) -> Dict[str, float]:
        """
        history_df: DataFrame with exactly `cfg.sequence_length` rows, sorted
        ascending by time, containing columns: timestamp (parseable to
        datetime), temperature_c, pressure_hpa, relative_humidity_pct.
        Returns: {"temperature_c": ..., "pressure_hpa": ..., "relative_humidity_pct": ...}
        in PHYSICAL units.
        """
        if len(history_df) != self.cfg.sequence_length:
            raise ValueError(
                f"Expected exactly {self.cfg.sequence_length} historical observations, "
                f"got {len(history_df)}."
            )

        df = history_df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)

        df = add_time_features(df)
        scaled_physical = self.scaler.transform(df[self.cfg.scale_columns].to_numpy(dtype=np.float64))
        df[self.cfg.scale_columns] = scaled_physical

        x = df[self.cfg.feature_columns].to_numpy(dtype=np.float32)
        x_tensor = torch.from_numpy(x).unsqueeze(0).to(self.device)  # (1, seq_len, n_features)

        with torch.no_grad():
            self.model.eval()
            pred_scaled = self.model(x_tensor).cpu().numpy()  # (1, 3)

        pred_phys = self.scaler.inverse_transform(pred_scaled)[0]
        return {col: float(val) for col, val in zip(self.cfg.target_columns, pred_phys)}


def predict_next(history_df: pd.DataFrame, model_dir: Optional[Union[str, Path]] = None) -> Dict[str, float]:
    """Convenience one-shot function (loads artifacts on every call — for
    repeated use, prefer TemporalLSTMPredictor)."""
    predictor = TemporalLSTMPredictor(model_dir=model_dir)
    return predictor.predict_next(history_df)
