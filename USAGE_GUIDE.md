# ATHER (SkyGuard AI) — Operational Usage & Presentation Guide
### SIH 2026 · PS26073 · AI/ML-Based Anomaly Detection for Automatic Weather Stations

This prototype implements a software anomaly detection, root-cause diagnosis, and self-healing system for Automatic Weather Stations (AWS). It uses the Max Planck Institute **Jena Climate Dataset (2009–2016)** (420,551 records) as its baseline.

---

## 1. Quickstart (One-Command Launch)

The project has a dedicated virtual environment provisioned via `uv` with Python 3.11.

### Start the API & Interactive Dashboard
```bash
source .venv/bin/activate
python scripts/run_pipeline.py
```
Open your browser to: **[http://localhost:8000](http://localhost:8000)**

---

## 2. Interactive Dashboard Features

The dashboard provides a dark-mode interface with live streaming telemetry:
- **Telemetry Chart (Chart.js)**: Displays real-time Temperature (°C), Raw sensor telemetry, and Self-Healed Imputed values with anomaly markers.
- **5-Layer Telemetry Progress Gauges**:
  1. **Layer 1: Physics Validation (MetPy)**: Dew point bounds, wet-bulb survivability (<35°C), barometric altitude consistency. Triggers instant deterministic **VETO**.
  2. **Layer 2: Temporal Pattern Analysis**: Step rate-of-change ($\Delta x / \Delta t$) and zero-variance stuck/frozen sensor detection.
  3. **Layer 3: Multivariate Consistency (PyOD ECOD)**: Joint $(T, P, RH)$ empirical atmospheric manifold validation.
  4. **Layer 4: Spatial / Neighbor Analysis**: Inverse-distance weighted (IDW) consensus residual vs. 3 adjacent AWS nodes. Distinguishes regional weather fronts from local hardware failures.
  5. **Layer 5: Sensor Drift & Health**: CUSUM systematic bias accumulator, Station Sensor Health index (0–100%), and predictive maintenance forecasting.
- **Demonstration Fault Injection Console**:
  - `⚡ Sudden Spike (+15°C)`: Injects an acute transient impulse error.
  - `❄️ Frozen Sensor`: Freezes transducer values to test ADC lockup detection.
  - `📈 Calibration Drift`: Injects cumulative calibration bias.
  - `🚫 Impossible Physics`: Injects $T_{\text{dew}} > T_{\text{ambient}}$ to trigger thermodynamic VETO.
- **Real-Time Diagnostic & XAI Feed**: Plain-English explanations generated from SHAP and physics attribution for AWS field engineers.

---

## 3. Running Automated Tests & Verification

### Run Pytest Test Suite
```bash
.venv/bin/pytest tests/ -v
```
Verifies thermodynamic physics validation, synthetic fault injector, and end-to-end detection and imputation.

### Run SIH 2026 Evaluation Benchmark
```bash
.venv/bin/python scripts/run_evaluation.py --samples 5000
```
Outputs:
- Overall Precision, Recall, and F1-score.
- Bounded False Alarm Rate (FAR).
- Fast-Path latency (p50 < 1.0 ms) vs. Full-Path latency (p50 < 2.0 ms).
- Detection rate breakdown across fault categories (`SENSOR_SPIKE`, `FROZEN_SENSOR`, `CALIBRATION_DRIFT`, `NOISE_BURST`).

### Run 5-Layer Ablation Study
```bash
.venv/bin/python scripts/run_ablation.py
```
Ablates each of the 5 detection layers one at a time to quantify its marginal accuracy contribution for the SIH 25% Innovation & Novelty rubric.

---

## 4. Architecture & Vetted Repositories Reference

| Module | Reference Repository | Role in ATHER |
|---|---|---|
| **Layer 1: Physics** | [Unidata/MetPy](https://github.com/Unidata/MetPy) | Psychrometric wet-bulb temperature, dew point bounds, barometric height formula. |
| **Layer 2: Temporal** | [MOMENT](https://github.com/moment-timeseries-foundation-model/moment) | Rate-of-change spikes, stuck-at-constant run length. |
| **Layer 3: Multivariate** | [yzhao062/pyod](https://github.com/yzhao062/pyod) | ECOD empirical distribution outlier detection for $(T, P, RH)$ triples. |
| **Layer 4: Spatial** | IDW consensus | Multi-station spatial cluster consistency residual. |
| **Layer 5: Drift** | CUSUM / Page-Hinkley | Systematic bias accumulation and "Days Until Out of Tolerance". |
| **Fusion** | [scikit-learn-contrib/MAPIE](https://github.com/scikit-learn-contrib/MAPIE) | Conformal prediction calibrating false alarm probability $\alpha \le 0.001$. |
| **Explainability** | [shap/shap](https://github.com/shap/shap) | Feature attribution translated into field-technician diagnostic text. |
| **API & Serving** | [fastapi/fastapi](https://github.com/fastapi/fastapi) | High-throughput async REST endpoints + embedded static dashboard. |
