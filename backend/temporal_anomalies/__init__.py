"""
ATHER Temporal Intelligence — Stage 3: anomaly injection, LSTM residual
evaluation, and initial detection-threshold calibration experiment.

Stage 3 does NOT retrain the Stage 2 LSTM, does NOT modify its
architecture, and does NOT touch backend/models/temporal_lstm/model.pt or
scaler.pkl (the already-trained artifacts are loaded read-only). It is a
standalone, isolated evaluation pipeline: nothing here is imported by, or
imports from, engine/layer2_temporal.py, fusion/, root_cause/, or app/.

Pipeline: inject synthetic anomalies into copies of Stage 1's normal
sequences (data/temporal/synthetic_temporal_normal.csv is never modified)
-> run the frozen Stage 2 model -> compute residuals -> calibrate an
"initial_lstm_residual_score" from NORMAL VALIDATION residuals only ->
evaluate detection performance on the held-out ANOMALOUS TEST cases.

LIMITATION: all anomalies here are synthetically injected into synthetic
normal data. Results characterize this LSTM prediction pipeline's
behavior under controlled, labeled synthetic faults — they do not
demonstrate real-world AWS anomaly-detection accuracy.
"""
