"""
ATHER Temporal Intelligence — Stage 2: standalone LSTM next-step predictor.

Trains and evaluates a small LSTM that predicts the next 10-minute
(temperature_c, pressure_hpa, relative_humidity_pct) reading from the
previous 144 readings (24 hours), using the Stage 1 synthetic normal
dataset (backend/data/temporal/).

Stage 2 scope ONLY:
  dataset loading -> quality checks -> windowing -> scaling -> LSTM
  training -> evaluation -> standalone inference -> artifact saving.

This package is fully isolated from the production anomaly engine: it does
NOT import from, and is NOT imported by, engine/layer2_temporal.py,
fusion/, root_cause/, or app/. No anomaly labels, thresholds, or fusion
logic are implemented here — this is a next-step prediction baseline only.

LIMITATION: trained and evaluated entirely on Stage 1's synthetic normal
dataset. Strong prediction performance here does not demonstrate real-world
AWS anomaly-detection accuracy, production readiness, or failure-prediction
capability.
"""
