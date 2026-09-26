# Layer 3 — Multivariate Intelligence

Detects observations whose **joint** temperature / relative humidity / pressure
state is unusual for the station (or its region), the season and the time of
day — even when every value is individually plausible. Physical limits are
Layer 1's job; single-channel temporal behaviour (spikes, drift, frozen) is
Layer 2's.

## Inputs

Layer 3 consumes exactly: `temperature_c`, `humidity_pct`, `pressure_hpa`
(mean-sea-level), and the **verified observation timestamp**. Station
latitude/longitude are used only to choose the nearest regional reference and
to compute local solar time — never as model features. `preprocessing.standardize`
drops every other dataset column (wind, rain, surface pressure, labels, ...).

A reading with no verified `observation_timestamp` (e.g. the static
`data/stations.json` snapshot) is **not** scored by the learned models and is
never learned: season and time of day cannot be known, and "now" is never assumed.

## Pipeline

```
AWSReading ─► Observation(T, P, RH, observation time, longitude)
   ─► features.py        raw T, P, RH · dew point (Magnus, Alduchov & Eskridge 1996)
                         · per-hour deltas vs the station's previous observation (≤3 h gap)
                         · local solar hour
   ─► model choice       station's own models (≥1440 trusted obs if a reference covers it, else ≥400)
                         else regional reference: nearest of 24 Indian sites ≤75 km, same season
                         else labelled static prior (no ML verdict claimed)
   ─► DetectorPair       contextual deviations: every feature minus its learned diurnal
                         expectation (solar-hour harmonics, fit on the pair's own rows)
                         + learned T-RH residual  (RH | T, hour), standardized
                         + learned T-P residual   (P | T, hour, semi-diurnal tide), standardized
   ─► ECOD + Isolation Forest ─► split-conformal p-values (per model)
   ─► decision.py        both p ≤ α → ANOMALY (HIGH) · one → SUSPICIOUS (LOW) · none → NORMAL
   ─► trust gate         only NORMAL, not upstream-suspect, non-duplicate readings are committed
```

Seasonal context: one value, `season_window_days` (±30 d), used identically by the
live reference, offline validation and injection plausibility bands.
Fit/calibration split: `training.split_fit_calibration` — every 4th calendar day is
calibration — used identically everywhere.

## Relationships

| Pair | Data support (2.1 M rows, within station-month) | Use |
|---|---|---|
| T–RH | median r = −0.82; RH ~ T + hour R² = 0.71 | model feature `rh_given_t_residual_z` |
| T–P | median r = −0.26; P ~ T + hour R² = 0.15 | model feature `p_given_t_residual_z` by project decision (`use_pressure_temperature_residual`). Measured effect — 2022 validation: normal any-flag 1.32 % → 1.56 %, multivariate F1 .554 → .503; 2023–24 test: pressure-context recall (any flag) 7.9 % → 22.1 %, normal ANOMALY rate 1.14 % → 1.06 %, multivariate F1 .517 → .489 |
| RH–P | median r ≈ 0.01 after removing the daily cycle | not modelled — a residual would be noise |

## Dataset

**Open-Meteo Historical Weather API** (ERA5-based reanalysis), 24 Indian cities,
hourly 2015-01-01 → 2024-12-31, 2,104,128 rows, `timezone=Asia/Kolkata`.
Licence CC BY 4.0 (Open-Meteo; Copernicus ERA5). Same provider and variables as
ATHER's live feed (`temperature_2m`, `relative_humidity_2m`, `pressure_msl`).

```
python -m multivariate.download open-meteo   # -> data/historical/open_meteo_india_hourly.csv (126 MB, gitignored)
python -m multivariate.download isd          # optional: NOAA ISD-Lite real station obs -> data/raw/isd_lite/
```
The first live evaluation builds `models/multivariate/reference/*.npz` (gitignored cache).
Optional extra validation sets: NOAA ISD-Lite (6 Indian synoptic stations, 3-hourly;
Bengaluru has no usable pressure in ISD) and ATHER's synthetic temporal dataset.

## Validation

```
python engine/validate_multivariate.py --dataset open_meteo --splits validation   # choices only here
python engine/validate_multivariate.py --dataset open_meteo --splits test         # final numbers
python engine/validate_multivariate.py --dataset isd --splits test
python -m multivariate.live_check                                                 # live forecast feed
```
Split: train 2015–2021, validation 2022 (all model choices), test 2023–2024.
Injected anomalies (`injection.py`) keep every value inside the station-season
[0.5, 99.5] percentile band and break a relationship instead.

Final configuration, α = 0.01 (normal-data rates are alarm rates, not accuracy;
P/R/F1 over all relationship-breaking types):

| Split | Obs | Stations | Normal ANOMALY / any-flag | ANOMALY P/R/F1 | Any-flag P/R/F1 |
|---|---|---|---|---|---|
| Open-Meteo validation 2022 | 210,240 | 24 | 0.82 % / 1.56 % | .416/.181/.252 | .509/.498/.503 |
| Open-Meteo test 2023–24 | 420,912 | 24 | 1.06 % / 1.86 % | .372/.193/.255 | .471/.510/.489 |
| NOAA ISD test 2023–24 | 32,231 | 6 | 0.51 % / 1.04 % | .551/.125/.204 | .597/.311/.409 |
| Synthetic temporal | 15,120 | 60 | 1.88 % / 3.51 % | .750/.495/.597 | .674/.626/.649 |

Univariate per-channel diurnal baseline on the Open-Meteo test years: F1 .257 at a 3.8 % normal alarm rate.

## Known limitations

- The reference is reanalysis at a city centre; the live feed is forecast-model output
  at the station. Live replay: Chennai stations flagged 9.1 % ANOMALY in one week vs
  ≤1.1 % elsewhere — unresolved whether that is feed mismatch or real weather.
- Test-year normal ANOMALY rate (1.06 %) is slightly above the ~1 % design target:
  year-to-year climate drift weakens the conformal guarantee.
- ECOD is rank-based: beyond the training maximum a feature's tail is capped at
  1/(n_fit+1), which is why a station's own model takes over only after 1440 readings.
- Recall on sustained, moderate relationship breaks is limited (RH offset: 11 % of rows
  at ANOMALY level on the test years).
- The T–P relationship is weak in real data; the P|T residual buys pressure-context
  sensitivity at a measured cost in multivariate F1 (see Relationships). Without it,
  jointly unprecedented T/RH/P states at the 97.5th percentile are not flagged.
- No labelled real-world fault data exists; normal-data figures are alarm rates, not accuracy.
