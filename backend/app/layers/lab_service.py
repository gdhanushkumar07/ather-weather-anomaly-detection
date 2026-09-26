"""
Layer Lab — demonstration service for Layer 1 (Physics) and Layer 3
(Multivariate Intelligence).

Everything returned here comes from the production code paths:
  - physics:      PhysicsValidationLayer.explain() (same thresholds/formulas as
                  evaluate(), which supplies the authoritative verdict)
  - multivariate: a fresh MultivariateConsistencyLayer sharing the live
                  detector's regional-reference cache, so the models, features,
                  calibration and decision are exactly the ones ATHER uses.
                  A fresh layer means no station history: the lab always shows
                  the regional-reference path (optionally with one previous
                  reading so the rate-of-change features are active).
  - context:      the seasonal-window rows those models are trained on, plus
                  presets derived from that same climatology (never hand-typed
                  numbers).
Nothing here writes to the live detector's station state.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from config import CONFIG
from schema import AWSReading, ObservationSource
from engine.layer1_physics import PhysicsValidationLayer
from engine.layer3_multivariate import MultivariateConsistencyLayer
from multivariate import schema as S
from multivariate.features import DYNAMIC, STATIC, dew_point_c, input_feature_names, solar_hour
from multivariate.models import ANOMALY_SUFFIX

_physics = PhysicsValidationLayer()


def _reference():
    from app.anomaly.detector import detector
    return detector.layer3.engine.reference


def _ts(value: Optional[str]) -> datetime:
    if not value:
        raise ValueError("timestamp is required (ISO-8601). The lab never assumes 'now' for season/time of day.")
    t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def _q(s: pd.Series, q: float) -> float:
    return round(float(s.quantile(q)), 2)


def _hour_rows(season: pd.DataFrame, hours: np.ndarray, h: float, width: float = 1.0) -> pd.DataFrame:
    d = np.abs(((hours - h) + 12) % 24 - 12)
    return season[d <= width]


def context(lat: float, lon: float, timestamp: str) -> Dict[str, Any]:
    ts = _ts(timestamp)
    ref = _reference()
    near = ref.nearest_site(lat, lon) if ref is not None else None
    hour = float(solar_hour(ts, lon)[0])
    base = {"timestamp": ts.isoformat(), "solar_hour": round(hour, 2), "season_window_days": CONFIG.multivariate.season_window_days,
            "alpha": CONFIG.multivariate.alpha}
    if near is None:
        return {**base, "reference": None,
                "note": f"No regional reference site within {CONFIG.multivariate.reference_max_distance_km:.0f} km — "
                        "Layer 3 would use the station's own history once it has enough trusted readings, "
                        "or a labelled static prior until then."}
    site, km = near
    season = ref.season_frame(site, ts)
    site_lat, site_lon = ref._sites[site]
    hours = solar_hour(season[S.TIMESTAMP], site_lon)
    season = season.assign(solar_h=hours)

    step = max(1, len(season) // 1500)
    sample = season.iloc[::step]
    scatter = [{"t": round(float(r.temperature_c), 1), "rh": round(float(r.humidity_pct), 1),
                "p": round(float(r.pressure_hpa), 1), "h": round(float(r.solar_h), 1)} for r in sample.itertuples()]

    profile = []
    for h in range(24):
        rows = _hour_rows(season, hours, h + 0.5, 0.5)
        if len(rows) < 10:
            continue
        td = pd.Series(dew_point_c(rows[S.TEMPERATURE], rows[S.HUMIDITY]))
        profile.append({"hour": h + 0.5, **{f"{k}_{q}": _q(v, qq) for k, v in (
            ("t", rows[S.TEMPERATURE]), ("rh", rows[S.HUMIDITY]), ("p", rows[S.PRESSURE]), ("td", td))
            for q, qq in (("p05", 0.05), ("p50", 0.5), ("p95", 0.95))}})

    # learned relationship curves at THIS solar hour, from the model itself
    curves = {}
    pair = ref.pair_for(site, ts, STATIC)
    at_hour = _hour_rows(season, hours, hour)
    if pair is not None and len(at_hour):
        names = input_feature_names(STATIC)
        t_grid = np.linspace(season[S.TEMPERATURE].quantile(0.01), season[S.TEMPERATURE].quantile(0.99), 40)
        rows = np.zeros((len(t_grid), len(names)))
        med = {S.PRESSURE: at_hour[S.PRESSURE].median(), S.HUMIDITY: at_hour[S.HUMIDITY].median()}
        for j, n in enumerate(names):
            rows[:, j] = {S.TEMPERATURE: t_grid, S.PRESSURE: med[S.PRESSURE], S.HUMIDITY: med[S.HUMIDITY],
                          "dew_point_c": dew_point_c(t_grid, med[S.HUMIDITY]),
                          "solar_hour_sin": np.sin(2 * np.pi * hour / 24), "solar_hour_cos": np.cos(2 * np.pi * hour / 24)}[n]
        for key in ("t_rh", "t_p"):
            out = pair.expected_by_relationship(key, rows)
            if out is not None:
                exp, sd = out
                curves[key] = {"t": [round(float(v), 2) for v in t_grid],
                               "expected": [round(float(v), 2) for v in exp], "sd": round(float(sd), 2)}

    presets = _presets(season, hours, hour)
    return {**base, "reference": {"site": site, "distance_km": round(km, 1), "latitude": site_lat, "longitude": site_lon,
                                  "rows_in_season_window": int(len(season)),
                                  "years": sorted(int(y) for y in season[S.TIMESTAMP].dt.year.unique())},
            "scatter": scatter, "diurnal_profile": profile, "relationship_curves": curves, "presets": presets}


def _presets(season: pd.DataFrame, hours: np.ndarray, hour: float):
    at = _hour_rows(season, hours, hour)
    day = 8 <= hour <= 18
    opposite = _hour_rows(season, hours, 4.0 if day else 14.0)
    t, rh, p = _q(at[S.TEMPERATURE], 0.5), _q(at[S.HUMIDITY], 0.5), _q(at[S.PRESSURE], 0.5)
    hot = at[at[S.TEMPERATURE] >= at[S.TEMPERATURE].quantile(0.97)]
    # Decoupling: the opposite time of day's humidity, taken from the tail that
    # moves AWAY from this hour's norm (the direction the data says is unusual).
    away = 0.9 if opposite[S.HUMIDITY].median() >= rh else 0.1
    decoupled_rh = _q(opposite[S.HUMIDITY], away)

    def r(temp, hum, pres, **extra):
        return {"temperature_c": round(float(temp), 1), "humidity_pct": round(float(hum)), "pressure_hpa": round(float(pres), 1), **extra}

    return [
        {"id": "normal", "label": "Typical for this hour", "expect": "NORMAL",
         "description": "Median temperature, humidity and pressure observed at this station, season and time of day.",
         "reading": r(t, rh, p)},
        {"id": "diurnal_extreme", "label": "Hot but normal for the hour", "expect": "NORMAL",
         "description": "The hottest 3% of readings at this hour — extreme overall, yet normal for this time of day, with humidity that fits.",
         "reading": r(hot[S.TEMPERATURE].median(), hot[S.HUMIDITY].median(), hot[S.PRESSURE].median())},
        {"id": "t_rh_decoupling", "label": "Temperature–humidity decoupling", "expect": "MULTIVARIATE",
         "description": f"Normal temperature for this hour, but a humidity that occurs here only around {'pre-dawn' if day else 'mid-afternoon'} "
                        f"— each value is common at this station, the pair is not. (In climates that stay humid all day the "
                        f"contrast is small and Layer 3 may rightly call it normal.)",
         "reading": r(t, decoupled_rh, p)},
        {"id": "joint_extreme", "label": "Hot + humid + high pressure together", "expect": "MULTIVARIATE",
         "description": "Each value at its 97.5th percentile for this hour — individually plausible, jointly unprecedented.",
         "reading": r(_q(at[S.TEMPERATURE], 0.975), _q(at[S.HUMIDITY], 0.975), _q(at[S.PRESSURE], 0.975))},
        {"id": "pressure_context", "label": "Pressure out of context", "expect": "EVIDENCE",
         "description": "Temperature and humidity typical; pressure at the season's 99.9th percentile. Evidence rises sharply, but "
                        "pressure is only weakly tied to temperature and humidity, so on its own it rarely reaches ANOMALY "
                        "(8.6% recall on the 2023–24 test years).",
         "reading": r(t, rh, _q(season[S.PRESSURE], 0.999))},
        {"id": "dew_point_violation", "label": "Sensor dew point above air temperature", "expect": "PHYSICS",
         "description": "The station reports a dew point 3 °C above air temperature — thermodynamically impossible (physics veto).",
         "reading": r(t, rh, p, dew_point_c=round(float(t) + 3.0, 1))},
        {"id": "humidity_fault", "label": "Humidity sensor reads 104%", "expect": "PHYSICS",
         "description": "Relative humidity above 100% cannot exist in free air — hard physical bound (physics veto).",
         "reading": r(t, 104, p)},
        {"id": "wet_bulb", "label": "Unsurvivable heat-humidity", "expect": "PHYSICS",
         "description": "37 °C with 95% humidity implies a wet-bulb temperature above 35 °C — beyond the physical survivability limit.",
         "reading": r(37.0, 95, p)},
    ]


def analyze(payload: Dict[str, Any]) -> Dict[str, Any]:
    ts = _ts(payload.get("timestamp"))
    lat, lon = float(payload.get("latitude", 0.0)), float(payload.get("longitude", 0.0))
    elev = float(payload.get("elevation_m") or 0.0)

    def reading(values: Dict[str, Any], when: datetime, sid: str = "LAYER_LAB") -> AWSReading:
        return AWSReading(station_id=sid, lat=lat, lon=lon, elevation_m=elev,
                          temperature_c=values.get("temperature_c"), pressure_hpa=values.get("pressure_hpa"),
                          humidity_pct=values.get("humidity_pct"), dew_point_c=values.get("dew_point_c"),
                          observation_timestamp=when, source=ObservationSource.SYNTHETIC_TEST)

    current = reading(payload, ts)
    physics = _physics.explain(current)

    ref = _reference()
    layer = MultivariateConsistencyLayer(config=CONFIG.multivariate, reference=ref)
    prev = payload.get("previous")
    if prev:
        minutes = float(prev.get("minutes_before", 60))
        layer.evaluate(reading(prev, ts - timedelta(minutes=minutes)))
    score, reason, d3 = layer.evaluate(current)

    mv: Dict[str, Any] = {
        "layer_score": round(float(score), 4), "reason": reason, "status": d3.get("status"),
        "method": d3.get("method"), "valid_channel_count": d3.get("valid_channel_count"),
        "clausius_clapeyron": d3.get("clausius_clapeyron"),
    }
    for k in ("model_source", "reference_site", "reference_distance_km", "reference_month", "feature_set",
              "training_samples", "calibration_samples", "min_attainable_p", "alpha", "ecod", "isolation_forest",
              "decision", "relationships", "features", "status_ml", "note", "euclidean_fallback"):
        if k in d3:
            mv[k] = d3[k]

    # Full per-feature breakdown from the SAME model pair that scored the reading.
    site = d3.get("reference_site")
    kind = d3.get("feature_set")
    if site and kind and d3.get("status_ml") == "EVALUATED":
        pair = ref.pair_for(site, ts, kind)
        feats = {k: (np.nan if v is None else float(v)) for k, v in d3["features"].items()}
        x = np.array([feats[n] for n in pair.input_names], dtype=float)
        expected = pair.diurnal_expectation(x)
        value_names = [n for n in pair.input_names if n not in ("solar_hour_sin", "solar_hour_cos")]
        exp_map = {} if expected is None else {n: round(float(v), 3) for n, v in zip(value_names, expected[0])}
        rows = []
        for tail in pair.feature_tails(x):
            name = tail["feature"]
            base_name = name.replace(ANOMALY_SUFFIX, "")
            rows.append({**tail, "tail_probability": round(tail["tail_probability"], 5),
                         "base_feature": base_name,
                         "observed": None if base_name not in feats or not np.isfinite(feats[base_name]) else round(feats[base_name], 3),
                         "expected_for_hour": exp_map.get(base_name),
                         "kind": "relationship" if name.endswith("_residual_z") else
                                 ("rate_of_change" if base_name.startswith("d_") else "contextual")})
        mv["model_features"] = rows
        mv["tail_floor"] = round(1.0 / (pair.n_fit + 1.0), 6)

    return {"input": {"timestamp": ts.isoformat(), "latitude": lat, "longitude": lon, "elevation_m": elev,
                      "temperature_c": payload.get("temperature_c"), "pressure_hpa": payload.get("pressure_hpa"),
                      "humidity_pct": payload.get("humidity_pct"), "dew_point_c": payload.get("dew_point_c"),
                      "solar_hour": round(float(solar_hour(ts, lon)[0]), 2)},
            "physics": physics, "multivariate": mv,
            "config": {"alpha": CONFIG.multivariate.alpha, "season_window_days": CONFIG.multivariate.season_window_days}}
