"""
Stage 4: LSTM temporal-prediction evidence source.

Wraps the already-trained, FROZEN Stage 2 LSTM (backend/models/temporal_lstm/)
so it can be consulted by TemporalPatternLayer (engine/layer2_temporal.py)
as an ADDITIONAL evidence source alongside the existing rule-based checks.

DESIGN PRINCIPLES (Stage 4 spec):
  - Loads the model/scaler ONCE (this class is instantiated once per
    TemporalPatternLayer instance, not per reading).
  - Never retrains, never fits a new scaler, never modifies model weights.
  - Uses exactly the same preprocessing as Stage 2 — reuses
    temporal_lstm.inference.TemporalLSTMPredictor unmodified rather than
    duplicating its logic.
  - Reads Stage 3's calibration_stats.json at load time (not hardcoded).
  - Degrades gracefully: any load or inference failure disables LSTM
    evidence and reports why, without raising into the caller.
"""
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import LSTMTemporalConfig

BACKEND_DIR = Path(__file__).resolve().parents[1]

PHYSICAL_CHANNELS = ["temperature_c", "pressure_hpa", "relative_humidity_pct"]


def load_calibration_percentiles(path: Path) -> Dict[str, Dict[str, float]]:
    """Reads Stage 3's calibration_stats.json. Raises on any problem — the
    caller (LSTMTemporalEvidence.__init__) is responsible for catching this
    and disabling LSTM evidence gracefully."""
    with open(path) as f:
        data = json.load(f)
    return data["normal_validation_residual_percentiles"]


@dataclass
class LSTMStepResult:
    available: bool
    skip_reason: Optional[str] = None

    predicted_temperature_c: Optional[float] = None
    predicted_pressure_hpa: Optional[float] = None
    predicted_humidity_pct: Optional[float] = None

    temperature_residual: Optional[float] = None
    pressure_residual: Optional[float] = None
    humidity_residual: Optional[float] = None

    temperature_abs_residual: Optional[float] = None
    pressure_abs_residual: Optional[float] = None
    humidity_abs_residual: Optional[float] = None

    # Normalized-by-P99 scores, UNCLIPPED (for explainability — can exceed 1.0)
    temperature_raw_score: Optional[float] = None
    pressure_raw_score: Optional[float] = None
    humidity_raw_score: Optional[float] = None

    # Same scores CLIPPED to [0,1] — these are what get combined with the
    # existing rule-based channel scores (same scale/semantics).
    temperature_score: float = 0.0
    pressure_score: float = 0.0
    humidity_score: float = 0.0

    lstm_residual_score: float = 0.0  # max(clipped channel scores) — see config.py note: NOT the final ATHER temporal score


class LSTMTemporalEvidence:
    """
    Instantiate ONCE per TemporalPatternLayer. If Stage 2/3 artifacts are
    missing or fail to load, `self.available` is False and every call to
    `evaluate()` returns a skip result — the rest of ATHER continues
    functioning on rule-based temporal evidence alone (spec section 21).
    """

    def __init__(self, cfg: LSTMTemporalConfig):
        self.cfg = cfg
        self.available = False
        self.load_error: Optional[str] = None
        self.predictor = None
        self.calibration: Optional[Dict[str, Dict[str, float]]] = None

        if not cfg.enabled:
            self.load_error = "disabled_by_config"
            return

        try:
            # Imported lazily so a missing/broken torch install can never
            # break the rest of ATHER at process startup — only this
            # optional evidence source is affected.
            from temporal_lstm.inference import TemporalLSTMPredictor

            model_dir = BACKEND_DIR / cfg.model_dir
            self.predictor = TemporalLSTMPredictor(model_dir=model_dir)

            calibration_path = BACKEND_DIR / cfg.calibration_path
            self.calibration = load_calibration_percentiles(calibration_path)
            for ch in PHYSICAL_CHANNELS:
                if ch not in self.calibration or "p99" not in self.calibration[ch]:
                    raise ValueError(f"calibration_stats.json missing p99 for channel '{ch}'")

            self.available = True
        except Exception as e:
            print(f"Warning: LSTM temporal evidence unavailable at startup ({type(e).__name__}: {e}). "
                  f"Falling back to rule-based-only temporal intelligence.")
            self.load_error = "model_load_error"
            self.predictor = None
            self.calibration = None
            self.available = False

    def evaluate(
        self,
        history: List[Tuple[datetime, float, float, float]],
        actual_temperature_c: Optional[float],
        actual_pressure_hpa: Optional[float],
        actual_humidity_pct: Optional[float],
    ) -> LSTMStepResult:
        """
        history: the PREVIOUS `cfg.sequence_length` jointly-valid
        (timestamp, temperature_c, pressure_hpa, relative_humidity_pct)
        tuples — must NOT include the current observation being predicted
        (spec section 7: no off-by-one leakage of the target into its own
        input window).
        actual_*: the just-arrived current reading's own values, used only
        to compute the residual — never fed into the model.
        """
        if not self.available:
            return LSTMStepResult(available=False, skip_reason=self.load_error or "lstm_unavailable")

        if actual_temperature_c is None or actual_pressure_hpa is None or actual_humidity_pct is None:
            # Spec section 18: never fabricate a residual against a missing
            # current observation.
            return LSTMStepResult(available=False, skip_reason="current_observation_incomplete")

        if len(history) < self.cfg.sequence_length:
            return LSTMStepResult(available=False, skip_reason="insufficient_valid_history")

        recent_history = history[-self.cfg.sequence_length:]
        if any(
            t is None or T is None or P is None or RH is None
            for (t, T, P, RH) in recent_history
        ):
            # Defensive guard — history_complete is only ever populated
            # with jointly-valid tuples, so this should not trigger, but
            # we never feed a NaN/None into the model regardless.
            return LSTMStepResult(available=False, skip_reason="insufficient_valid_history")

        try:
            history_df = pd.DataFrame(recent_history, columns=["timestamp", "temperature_c", "pressure_hpa", "relative_humidity_pct"])
            prediction = self.predictor.predict_next(history_df)
        except Exception as e:
            print(f"Warning: LSTM inference failed ({type(e).__name__}: {e}). Skipping LSTM evidence for this reading.")
            return LSTMStepResult(available=False, skip_reason="inference_error")

        pred_t = prediction["temperature_c"]
        pred_p = prediction["pressure_hpa"]
        pred_rh = prediction["relative_humidity_pct"]

        resid_t = actual_temperature_c - pred_t
        resid_p = actual_pressure_hpa - pred_p
        resid_rh = actual_humidity_pct - pred_rh

        abs_t, abs_p, abs_rh = abs(resid_t), abs(resid_p), abs(resid_rh)

        # Stage 5 calibration factor (default 1.0 = exact Stage 4 behavior):
        # see config.LSTMTemporalConfig.combined_score_calibration_factor
        # for the full measurement-based justification.
        k = self.cfg.combined_score_calibration_factor
        raw_score_t = abs_t / self.calibration["temperature_c"]["p99"] / k
        raw_score_p = abs_p / self.calibration["pressure_hpa"]["p99"] / k
        raw_score_rh = abs_rh / self.calibration["relative_humidity_pct"]["p99"] / k

        score_t = min(1.0, raw_score_t)
        score_p = min(1.0, raw_score_p)
        score_rh = min(1.0, raw_score_rh)

        return LSTMStepResult(
            available=True,
            predicted_temperature_c=pred_t, predicted_pressure_hpa=pred_p, predicted_humidity_pct=pred_rh,
            temperature_residual=resid_t, pressure_residual=resid_p, humidity_residual=resid_rh,
            temperature_abs_residual=abs_t, pressure_abs_residual=abs_p, humidity_abs_residual=abs_rh,
            temperature_raw_score=raw_score_t, pressure_raw_score=raw_score_p, humidity_raw_score=raw_score_rh,
            temperature_score=score_t, pressure_score=score_p, humidity_score=score_rh,
            lstm_residual_score=max(score_t, score_p, score_rh),
        )
