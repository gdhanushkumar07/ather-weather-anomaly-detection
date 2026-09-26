"""
ATHER Layer 3 — Multivariate Intelligence.

Station/region-specific learning of the JOINT behaviour of temperature,
pressure, humidity and derived features, using ECOD and Isolation Forest.

Module map (each stage is separate on purpose):
    schema.py         standard observation schema every dataset is mapped to
    datasets.py       dataset loading adapters (Open-Meteo, NOAA ISD-Lite,
                      ATHER synthetic temporal dataset, generic CSV)
    download.py       reproducible download of the real datasets
    preprocessing.py  cleaning / de-duplication / physical-bound filtering
    features.py       feature engineering (raw, per-station deltas, dew point,
                      local-solar-hour)
    models.py         ECOD + Isolation Forest wrappers, split-conformal calibration
    decision.py       explicit ensemble decision rule + layer score mapping
    reference.py      regional historical reference models (live cold start)
    online.py         per-station online state, trust-gated updates
    injection.py      controlled multivariate (relationship-breaking) anomalies
    evaluation.py     validation runner (normal-data FPR + injected P/R/F1)

engine/layer3_multivariate.py is the ATHER pipeline entry point and uses
online.py; it does not duplicate any of the logic here.
"""
