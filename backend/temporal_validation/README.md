# Temporal Intelligence — Final Acceptance Test

Validation-only. No production code, frontend, API, or configuration was modified.
Reuses the FROZEN Stage 1-6 `TemporalPatternLayer` (`engine/layer2_temporal.py`),
the frozen Stage 2 LSTM (`models/temporal_lstm/`), and the frozen Stage 3
calibration (`models/temporal_lstm/stage3_results/calibration_stats.json`)
exactly as they stand.

## How to reproduce

```
cd backend
python3 -m temporal_validation.run_acceptance_test
python3 -m unittest discover -s tests -p "test_*.py"
```

## Files

- `normal_results.json` — Section 2 (normal behavior on 75 real Stage 1 validation stations)
- `anomaly_results.json` — Sections 3/4/5/6 (10 anomaly types: rule/LSTM/recent-peak/integrated
  scores, detection delay, recovery time, prediction samples, rule-vs-LSTM classification)
- `recovery_results.json` — condensed recovery-time summary
- `robustness_results.json` — Section 7 (direct re-reproduction of the 3 Stage 6 bug fixes +
  gap-boundary behavior), Section 8 (output-contract checks), Section 9 (performance)
- `final_validation.json` — the acceptance table and final decision

## Scope and honesty notes

- All results are **synthetic-data engineering validation** — no real-world AWS accuracy,
  IMD validation, or production false-positive rate is claimed anywhere in this package.
- The already-documented Stage 5/6 limitations (9.6% of normal readings >0.70, 21.2%
  reason-string rate) are reproduced exactly and are **not** treated as new failures.
- One new observation was made during this acceptance pass (see `normal_results.json`'s
  `max_continuous_elevated_run_investigation`): the longest continuous elevated-score run
  traces to exactly 2 of 75 stations, which are the same two baseline-humidity-at-the-
  physical-boundary stations already flagged in Stage 1.5 as heavily clipped during
  synthetic generation. This is a synthetic-data limitation, not a new Temporal
  Intelligence code defect, and does not block acceptance.
