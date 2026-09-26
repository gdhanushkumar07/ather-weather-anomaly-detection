"""
Per-station online Layer 3 engine.

    new observation
        -> features (deltas vs this station's previous DISTINCT observation)
        -> choose model:  station's own models   (>= station_model_takeover_samples trusted obs
                                                  if a regional reference covers the station,
                                                  else >= min_train_samples)
                          else regional reference (nearest site, same season)
                          else none (caller falls back to its static prior)
        -> ECOD + Isolation Forest -> conformal p-values -> decision
        -> trust gate: the observation joins the station's training history
           ONLY if Layer 3 said NORMAL and the caller reports no upstream
           suspicion (Layer 1 veto / strong Layer 1 or Layer 2 evidence).

The trust gate is what stops a slowly failing sensor from teaching the model
that its failure is normal. SUSPICIOUS observations are also withheld — a
conservative choice: a missed genuine-weather sample costs little, a learned
fault costs detection.

Repeated evaluation of the same observation (ATHER re-evaluates stations on
page views/refreshes while the upstream value is unchanged) is detected by
observation time: it is scored against the same previous observation and is
never appended twice.
"""
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from multivariate import schema as S
from multivariate.decision import NORMAL, decide
from multivariate.features import (DELTA_FEATURES, DEW_POINT, DYNAMIC, STATIC, Observation,
                                   has_deltas, observation_features)
from multivariate.models import ANOMALY_SUFFIX, DetectorPair
from multivariate.training import fit_pair, split_fit_calibration

MODEL_ECOD = "ecod"
MODEL_IF = "isolation_forest"


@dataclass
class StationState:
    trusted: Deque[Tuple[Observation, Dict[str, float]]]
    last_obs: Optional[Observation] = None
    prev_obs: Optional[Observation] = None
    pairs: Dict[str, Optional[DetectorPair]] = field(default_factory=dict)
    trusted_total: int = 0
    trusted_total_at_fit: Dict[str, int] = field(default_factory=dict)


class OnlineMultivariateEngine:
    def __init__(self, cfg, reference=None):
        self.cfg = cfg
        self.reference = reference
        self.states: Dict[str, StationState] = {}

    def state(self, station_id: str) -> StationState:
        if station_id not in self.states:
            self.states[station_id] = StationState(trusted=deque(maxlen=self.cfg.buffer_max_len))
        return self.states[station_id]

    # ── model selection ─────────────────────────────────────────────────
    def _own_pair(self, st: StationState, kind: str, required: int) -> Optional[DetectorPair]:
        if len(st.trusted) < required:
            return None
        stale = st.trusted_total - st.trusted_total_at_fit.get(kind, -10**9) >= self.cfg.retrain_interval
        if kind not in st.pairs or stale:
            rows = pd.DataFrame([f for _, f in st.trusted])
            rows[S.TIMESTAMP] = [o.time_utc for o, _ in st.trusted]
            fit_rows, cal_rows = split_fit_calibration(rows, self.cfg.calibration_fraction)
            st.pairs[kind] = fit_pair(fit_rows, cal_rows, kind, self.cfg)
            st.trusted_total_at_fit[kind] = st.trusted_total
        return st.pairs.get(kind)

    def _choose(self, station_id: str, st: StationState, kind: str, obs: Observation,
                lat: float, lon: float) -> Tuple[Optional[DetectorPair], Dict[str, Any]]:
        near = None
        if self.reference is not None and self.cfg.reference_enabled:
            near = self.reference.nearest_site(lat, lon)
        # Own model: from min_train_samples when nothing else covers the station,
        # but only from station_model_takeover_samples when it would REPLACE a reference.
        required = self.cfg.station_model_takeover_samples if near is not None else self.cfg.min_train_samples
        pair = self._own_pair(st, kind, required)
        if pair is not None:
            return pair, {"model_source": "station_history"}
        if near is not None:
            site, km = near
            pair = self.reference.pair_for(site, obs.time_utc, kind)
            if pair is not None:
                return pair, {"model_source": "regional_reference", "reference_site": site,
                              "reference_distance_km": round(km, 1),
                              "reference_month": pd.Timestamp(obs.time_utc).month}
        return None, {"model_source": "none"}

    # ── evaluation ──────────────────────────────────────────────────────
    def evaluate(self, station_id: str, obs: Observation, lat: float = 0.0, lon: float = 0.0,
                 upstream_suspect: bool = False) -> Dict[str, Any]:
        """score() + commit() with the default trust rule (Layer 3 NORMAL and no upstream suspicion)."""
        result = self.score(station_id, obs, lat, lon)
        normal = result.get("decision", {}).get("status", NORMAL) == NORMAL
        self.commit(station_id, obs, result, trusted=normal and not upstream_suspect)
        return result

    def commit(self, station_id: str, obs: Observation, result: Dict[str, Any], trusted: bool) -> None:
        """Advance the station's observation stream; learn from it only if trusted."""
        st = self.state(station_id)
        duplicate = result["duplicate_observation"]
        result["trusted_for_update"] = bool(trusted and not duplicate)
        if duplicate:
            return
        st.prev_obs, st.last_obs = st.last_obs, obs
        if trusted:
            st.trusted.append((obs, result["_features_raw"]))
            st.trusted_total += 1

    def score(self, station_id: str, obs: Observation, lat: float = 0.0, lon: float = 0.0) -> Dict[str, Any]:
        """Score one observation. Does not modify the station's state (see commit())."""
        st = self.state(station_id)
        duplicate = st.last_obs is not None and st.last_obs.time_utc == obs.time_utc
        prev = st.prev_obs if duplicate else st.last_obs
        feats = observation_features(obs, prev, self.cfg.max_delta_gap_hours)
        kind = DYNAMIC if has_deltas(feats) else STATIC

        pair, src = self._choose(station_id, st, kind, obs, lat, lon)
        if pair is None and kind == DYNAMIC:
            kind = STATIC
            pair, src = self._choose(station_id, st, kind, obs, lat, lon)

        result: Dict[str, Any] = {
            "feature_set": kind,
            "features": {k: (None if not np.isfinite(v) else round(float(v), 3)) for k, v in feats.items()},
            "station_trusted_history": len(st.trusted),
            "min_train_samples": self.cfg.min_train_samples,
            "duplicate_observation": duplicate,
            **src,
        }

        decision = None
        if pair is not None:
            x = np.array([feats[n] for n in pair.input_names], dtype=float)
            scores = pair.score(x[None, :])
            ecod_p = _first(scores.get(f"{MODEL_ECOD}_p"))
            if_p = _first(scores.get(f"{MODEL_IF}_p"))
            decision = decide(ecod_p, if_p, self.cfg.alpha)
            result.update({
                "status_ml": "EVALUATED",
                "training_samples": pair.n_fit,
                "calibration_samples": pair.n_cal,
                "min_attainable_p": pair.min_attainable_p(),
                "alpha": self.cfg.alpha,
                "ecod": {"enabled": self.cfg.ecod_enabled, "score": _round(_first(scores.get(f"{MODEL_ECOD}_score"))),
                         "p_value": _round(ecod_p, 5), "anomaly": decision.ecod_anomaly},
                "isolation_forest": {"enabled": self.cfg.isolation_forest_enabled,
                                     "score": _round(_first(scores.get(f"{MODEL_IF}_score"))),
                                     "p_value": _round(if_p, 5), "anomaly": decision.isolation_forest_anomaly},
                "decision": decision.to_dict(),
                "top_features": [{**d, "tail_probability": round(d["tail_probability"], 5)}
                                 for d in pair.feature_tails(x)[:3]],
                "relationships": pair.relationships(x),
            })
            result["reason"] = explain(decision, feats, result)
        else:
            result.update({"status_ml": "NO_MODEL", "reason": None})
        result["_features_raw"] = feats
        return result


def explain(decision, feats: Dict[str, float], result: Dict[str, Any]) -> Optional[str]:
    if decision.status == NORMAL:
        return None
    if decision.layer3_anomaly:
        head = "Multivariate anomaly (ECOD and Isolation Forest agree)"
    else:
        which = "ECOD" if decision.ecod_anomaly else "Isolation Forest"
        head = f"Suspicious multivariate pattern (only {which} flags)"
    t, rh, p, td = feats[S.TEMPERATURE], feats[S.HUMIDITY], feats[S.PRESSURE], feats[DEW_POINT]
    rels = result.get("relationships") or {}
    parts = []
    t_rh, t_p = rels.get("t_rh"), rels.get("t_p")
    if t_rh and abs(t_rh["residual_z"]) >= 2.5:
        parts.append(f"unusual joint temperature-humidity pattern: RH {rh:.0f}% at {t:.1f}°C, where this "
                     f"station/season/time of day expects ~{t_rh['expected']:.0f}% (±{t_rh['residual_sd']:.0f})")
    if t_p and abs(t_p["residual_z"]) >= 2.5:
        parts.append(f"pressure {p:.1f} hPa vs ~{t_p['expected']:.1f} hPa expected for this temperature, season "
                     f"and time of day (±{t_p['residual_sd']:.1f}; weak relationship, R²={t_p['r2']:.2f})")
    top = result.get("top_features") or []
    lead = top[0]["feature"].replace(ANOMALY_SUFFIX, "") if top else None
    if lead == DEW_POINT:
        pct = top[0]["percentile"]
        side, share = ("above", pct) if pct >= 50 else ("below", 100.0 - pct)
        parts.append(f"dew point {td:.1f}°C is {side} {share:.1f}% of this station's history for the season"
                     + (" and time of day" if top[0]["feature"].endswith(ANOMALY_SUFFIX) else ""))
    elif lead == S.PRESSURE and not (t_p and abs(t_p["residual_z"]) >= 2.5):
        pct = top[0]["percentile"]
        side, share = ("above", pct) if pct >= 50 else ("below", 100.0 - pct)
        parts.append(f"pressure {p:.1f} hPa is {side} {share:.1f}% of this station's history for the season"
                     + (" and time of day" if top[0]["feature"].endswith(ANOMALY_SUFFIX) else ""))
    elif lead in DELTA_FEATURES:
        parts.append(f"joint rate of change is unusual ({lead} = {feats[lead]:+.2f}/h)")
    if not parts and top:
        parts.append("unusual combination of " + ", ".join(d["feature"] for d in top[:2]))
    src = result.get("model_source")
    basis = (f" [regional reference: {result.get('reference_site')}]" if src == "regional_reference"
             else " [station's own history]")
    return f"{head}: " + "; ".join(parts) + basis


def _first(a) -> Optional[float]:
    if a is None:
        return None
    v = float(np.asarray(a).ravel()[0])
    return v if np.isfinite(v) else None


def _round(v, nd=4):
    return None if v is None else round(float(v), nd)
