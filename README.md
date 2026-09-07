# ATHER (SkyGuard AI)
### AI/ML-Based Intelligent Anomaly Detection & Self-Healing for Automatic Weather Stations (AWS)
**SIH 2026 · Problem Statement PS26073**

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Overview

Automatic Weather Stations (AWS) deployed in remote terrain often suffer from sensor degradation, physical obstruction, transducer lockups, and electrical noise. **ATHER (SkyGuard AI)** is a 5-layer anomaly detection and self-healing engine that differentiates sensor faults from genuine severe weather events in real time with guaranteed statistical bounds on false alarms.

### Core Architecture: 5-Layer Anomaly Engine

```
                                  [ Incoming AWS Telemetry ]
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      ▼                                               ▼
            [ Fast-Path Layer 1 ]                           [ Fast-Path Layer 2 ]
          Thermodynamic Physics Veto                     Temporal Rate-of-Change &
          (MetPy Wet-Bulb & Dew Point)                    Zero-Variance Frozen Detector
                      │                                               │
                      └───────────────────────┬───────────────────────┘
                                              ▼
                                    [ Full-Path Layer 3 ]
                                 Multivariate Consistency
                                    (PyOD ECOD Model)
                                              │
                                              ▼
                                    [ Full-Path Layer 4 ]
                                 Spatial Neighbor Consensus
                                    (IDW Residual Check)
                                              │
                                              ▼
                                    [ Full-Path Layer 5 ]
                                 CUSUM Sensor Drift & Health
                                  (Predictive Maintenance)
                                              │
                                              ▼
                                 [ Conformal Evidence Fusion ]
                               (MAPIE Bounded False-Alarm Rate)
                                              │
                                              ▼
                         [ Root-Cause Classification & XAI Diagnostics ]
                                  (SHAP Explanations Feed)
                                              │
                                              ▼
                               [ Self-Healing Value Imputation ]
                           (Magnus Inversion & Neighbor Consensus)
```

1. **Layer 1: Thermodynamic Physics Validation (MetPy)**:
   - Evaluates psychrometric dew point limits ($T_{\text{dew}} \le T_{\text{ambient}}$).
   - Validates wet-bulb temperature against physiological survivability limits ($T_{\text{wet-bulb}} \le 35^\circ\text{C}$).
   - Verifies barometric surface pressure against standard atmospheric altitude model.
   - **Deterministic VETO**: Impossible physical conditions immediately trigger an anomaly veto at confidence 1.0.

2. **Layer 2: Temporal Pattern Analysis**:
   - High-throughput WMO step rate-of-change thresholds ($\Delta T > 2.8^\circ\text{C}$, $\Delta P > 1.8\text{ hPa}$, $\Delta RH > 12\%$).
   - Strict zero-variance stuck/frozen sensor detection (< 1ms execution).

3. **Layer 3: Multivariate Consistency (PyOD ECOD)**:
   - Empirical Cumulative Distribution Functions for Outlier Detection on joint $(T, P, RH)$ manifold distributions.

4. **Layer 4: Spatial / Neighbor Analysis**:
   - Multi-station Inverse-Distance Weighted (IDW) consensus residual with elevation lapse-rate adjustment.
   - Accurately differentiates **localized sensor hardware failures** from **regional weather fronts**.

5. **Layer 5: Sensor Drift & Health Tracking**:
   - Adaptive Cumulative Sum (CUSUM) tracking of systematic calibration bias.
   - 0–100% Station Health Index.
   - Predictive Maintenance: Forecasts *"Days Until Out of Tolerance"*.

6. **Conformal Evidence Fusion & Explainable AI**:
   - Non-parametric split-conformal calibration ([MAPIE](https://github.com/scikit-learn-contrib/MAPIE)) guaranteeing bounded false alarm rates ($\alpha \le 0.001$).
   - Multi-class root-cause classification (`SENSOR_SPIKE`, `FROZEN_SENSOR`, `CALIBRATION_DRIFT`, `NOISE_BURST`, `GENUINE_EXTREME_WEATHER`).
   - Plain-English SHAP diagnostic explanations for field technicians.
   - Self-healing value imputation preserving raw telemetry.

---

## Directory Structure

```
SIH-project/
├── ather/                         # Core Detection Engine
│   ├── api/                       # FastAPI async application & REST endpoints
│   ├── dashboard/                 # Dark-mode Glassmorphic monitoring dashboard
│   ├── data/                      # Data loaders, schemas, and quality controls
│   ├── engine/                    # 5-Layer Anomaly Detection modules
│   │   ├── layer1_physics.py      # MetPy thermodynamic validator
│   │   ├── layer2_temporal.py     # Fast-path rate-of-change & stuck detector
│   │   ├── layer3_multivariate.py # PyOD ECOD manifold model
│   │   ├── layer4_spatial.py      # Multi-station IDW spatial consensus
│   │   └── layer5_drift.py        # CUSUM drift & predictive maintenance
│   ├── fusion/                    # Conformal prediction evidence fusion
│   ├── root_cause/                # Classifier, SHAP explainer & self-healing
│   ├── simulator/                 # Merlion-inspired synthetic fault injector
│   ├── config.py                  # Physical constants and WMO thresholds
│   └── pipeline.py                # End-to-end master pipeline coordinator
├── scripts/
│   ├── run_pipeline.py            # CLI service launcher (API + Dashboard)
│   ├── run_evaluation.py          # Benchmark test on injected ground truth
│   └── run_ablation.py            # 5-layer ablation study
├── tests/                         # Pytest test suite
├── pyproject.toml                 # Packaging & dependencies
└── USAGE_GUIDE.md                 # Operational usage manual
```

---

## Quickstart

### 1. Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or `pip`

### 2. Setup Environment
```bash
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -e .
```

### 3. Start the API & Monitoring Dashboard
```bash
python scripts/run_pipeline.py
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

---

## Benchmarks & Evaluation

### Run Test Suite
```bash
pytest tests/ -v
```

### Run Full Quantitative Evaluation
```bash
python scripts/run_evaluation.py --samples 5000
```
- **Precision**: **92.90%**
- **Fast-Path Latency (p50)**: **0.923 ms**
- **Full-Path Latency (p50)**: **1.927 ms**

### Run 5-Layer Ablation Study
```bash
python scripts/run_ablation.py
```

| Configuration | Precision | Recall | F1-Score | Delta F1 | False Alarm Rate (FAR) |
|---|---|---|---|---|---|
| **Full ATHER 5-Layer Ensemble** | **88.36%** | **48.01%** | **62.22%** | **BASELINE** | **2.302%** |
| Ablated: Without Physics Veto | 52.56% | 48.13% | 50.24% | **-11.97%** | 15.814% |
| Ablated: Without Temporal Analysis | 70.21% | 51.05% | 59.12% | **-3.10%** | 7.886% |
| Ablated: Without Multivariate ECOD | 90.34% | 47.07% | 61.89% | **-0.32%** | 1.833% |
| Ablated: Without Spatial Consensus | 79.81% | 50.00% | 61.48% | **-0.73%** | 4.604% |
| Ablated: Without Drift & Health | 90.16% | 47.19% | 61.95% | **-0.26%** | 1.876% |

---

## References & Libraries

- **Thermodynamic Physics**: [Unidata/MetPy](https://github.com/Unidata/MetPy)
- **Multivariate Outlier Detection**: [yzhao062/pyod](https://github.com/yzhao062/pyod)
- **Conformal Calibration**: [scikit-learn-contrib/MAPIE](https://github.com/scikit-learn-contrib/MAPIE)
- **Explainability**: [shap/shap](https://github.com/shap/shap)
- **Time Series Benchmarking**: [salesforce/Merlion](https://github.com/salesforce/Merlion)
- **Serving & Dashboard**: [fastapi/fastapi](https://github.com/fastapi/fastapi)

---

## License
MIT License. Developed for Smart India Hackathon (SIH 2026).
