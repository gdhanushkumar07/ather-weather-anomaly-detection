"""
ATHER Temporal Intelligence — Synthetic Dataset Generator (Stage 1)
====================================================================
Generates a synthetic, labeled-normal, station-aware temporal dataset
(temperature_c, pressure_hpa, relative_humidity_pct at 10-minute cadence)
seeded from the real per-station baselines in data/stations.json.

This package implements ONLY Stage 1 of the Temporal Intelligence plan:
dataset generation. It does not implement, train, or reference any LSTM
model. See generate_dataset.py for the CLI entrypoint.

REALISM NOTE: this is a synthetic normal-weather approximation (diurnal
cycle + AR(1) slow/fast components), not a physical weather model. It
does not reproduce fronts, rainfall, cloud-driven irregular changes, or
monsoon transitions, and it must never be presented as real Indian AWS
telemetry or as a measure of real-world detection accuracy.
"""
