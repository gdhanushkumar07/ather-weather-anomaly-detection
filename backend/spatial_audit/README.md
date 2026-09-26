# S1 — Spatial Neighborhood Foundation

Branch: `feature/spatial-intelligence`

This directory documents and supports **S1** of the Spatial Intelligence
upgrade (see `engine/spatial_neighbors.py` for the implementation). S1's
scope is narrow and deliberate: make Spatial able to reliably answer one
question —

> "For this target station, which valid nearby stations should be
> considered its spatial neighbors, in deterministic distance order?"

Nothing about interpreting those neighbors (robust statistics, regional
clustering, event fingerprinting/evolution, counterfactual attribution,
final sensor-vs-weather classification) is part of S1. Those are S2+.

## 1. What existed before S1

The hackathon-era Spatial layer (`engine/layer4_spatial.py`) already had
working Haversine distance, IDW consensus, elevation lapse-rate correction,
per-channel z-scoring, and confidence-by-neighbor-count logic. What it
lacked was a *reliable neighbor pool*:

- `AnomalyDetector.get_neighbors_for_reading()` used a ±3° lat/lon bounding
  box (not a true radius — inaccurate at higher latitudes) over a
  dictionary's `.values()`, stopping at the first 8 matches in whatever
  order the dict happened to iterate. Not distance-sorted, not
  deterministic.
- `SpatialNeighborLayer.evaluate()` did its own separate self-exclusion +
  distance + radius-filter loop, with no K limit and no coordinate
  validation, so a single call site could accept an unbounded number of
  neighbors and would crash or misbehave on a NaN/out-of-range coordinate.

## 2. The S1 neighborhood foundation

`engine/spatial_neighbors.py` is the single, shared, reusable
implementation of:

```
candidate stations
    -> coordinate validation      (finite; lat in [-90,90], lon in [-180,180])
    -> self-station exclusion     (by station_id)
    -> geographic distance        (haversine, unchanged formula)
    -> radius filtering           (CONFIG.spatial.neighbor_distance_km_max, still 250km)
    -> distance sorting           (primary: distance_km, secondary: station_id)
    -> K-nearest selection        (CONFIG.spatial.spatial_k_neighbors, default 8)
    -> final neighbor list
```

Both production entry points now call this same function, so there is one
source of truth for "what counts as a valid, ranked neighbor":

- `app/anomaly/detector.py :: AnomalyDetector.get_neighbors_for_reading()` —
  selects candidates from the live `_spatial_pool`.
- `engine/layer4_spatial.py :: SpatialNeighborLayer.evaluate()` — re-applies
  the same validation/ranking/capping to whatever neighbor list it is
  handed (it can also be called directly, e.g. by tests and the simulation
  Test Lab, with a raw, unsorted, unvalidated list).

### Deterministic ordering

Sorting uses `(distance_km, station_id)` as the key, so exact or
near-exact distance ties always resolve the same way regardless of input
order — important for reproducible tests and, later, reproducible event
analysis.

### Coordinate validation

A coordinate is valid when both latitude and longitude are present,
finite, and within their physically possible ranges
(`-90 <= lat <= 90`, `-180 <= lon <= 180`). Invalid coordinates are
**excluded**, never repaired or invented. If the *target* station's own
coordinate is invalid, no neighbors can be computed at all (there is no
distance to measure from) and the result reports
`target_coordinate_valid=False`.

### Configurable K

`SpatialThresholds.spatial_k_neighbors` (default **8**) is new. It is
distinct from the existing `min_neighbors_required` (2): the latter is the
*floor* below which Spatial refuses to draw a conclusion; the new value is
the *ceiling* on how many of the nearest-in-radius candidates are used once
there are enough. The default of 8 was chosen specifically to match the
previous hardcoded `max_neighbors=8` in `get_neighbors_for_reading()`, so
existing behavior is unchanged by default — no currently exercised
production scenario or test has more than 5 neighbors within radius.

### Radius unchanged

`neighbor_distance_km_max` stays at 250 km — S1 does not touch it.

## 3. Relationship to the existing IDW consensus

S1 changes **only** how the neighbor pool is assembled. The existing IDW
math in `layer4_spatial.py::_channel_consensus()` (inverse-distance-squared
weighting, elevation lapse-rate adjustment, per-channel z-scoring,
confidence capping) is **unmodified** — it now simply operates on a
correctly validated, sorted, K-capped pool instead of an unordered,
unvalidated one. `total_neighbors_in_radius` in the returned `detail`
dict still reports the **true** pool size before the K cap (unaffected by
`spatial_k_neighbors`); `distance_range_km` reports the range of the
neighbors actually used in the computation (i.e. after the K cap).

Channel-wise `DataQuality` handling is untouched: a neighbor with valid
temperature but invalid/missing humidity still contributes temperature
evidence — it is not discarded as a whole station.

## 4. Historical dataset usage and provenance limitation

`neighborhood_audit.py` in this directory audits the new selection
pipeline against `ATHER_DATA/indian_weather_1996_2026/Indian_Weather_Dataset.csv`
(~7.2GB, outside the repository, read-only, never modified/copied/committed).

**Provenance**: this is historical Indian weather data of **uncertain**
provenance. It is documented (in the earlier `real_weather_audit`
workstream) as likely model/reanalysis-derived, based on data
characteristics — zero missing values, zero malformed rows, near-perfect
30-year hourly continuity — that are atypical of raw physical sensor
telemetry. **It is NOT confirmed AWS telemetry and NOT confirmed IMD AWS
telemetry.** It is used here only to check that the K-nearest pipeline
behaves sensibly against a real, geographically distributed set of
station-like locations — never as production input, never as ground truth
for a regional-event conclusion.

The audit script reads only the `city, lat, lon` columns (never the other
~19), and builds one real `AWSReading` per unique city, then runs the
**actual production** `select_k_nearest_neighbors()` (not a reimplemented
distance calc) with the **actual production** `CONFIG.spatial` values.
See `results/spatial_neighborhood_audit.json` for the latest run's output,
and §5 of the S1 final report for the interpreted numbers.

## 5. Production compatibility

The new pipeline was validated directly against `data/stations.json` (the
same 1,655-record file the production `_spatial_pool` is seeded from) —
see `tests/test_spatial_neighbor_foundation.py::TestProductionShapeValidation`.
Records load, coordinates parse as floats, self-exclusion and K-selection
work, and every returned neighbor's distance is confirmed `<=
neighbor_distance_km_max`. The production station schema was **not**
changed.

## 6. Files

```
spatial_audit/
    __init__.py
    neighborhood_audit.py        # S1 historical-dataset neighborhood audit (read-only)
    README.md                    # this file
    results/
        spatial_neighborhood_audit.json
```

Run the audit:

```bash
cd backend
python3 -m spatial_audit.neighborhood_audit
```

## What this workstream explicitly does NOT do

- Does not implement Median/MAD robust statistics, regional clustering
  (DBSCAN/HDBSCAN), event fingerprinting, event evolution, counterfactual
  verification, or final sensor-vs-weather attribution — all deferred to S2+.
- Does not modify the IDW mathematics or elevation lapse-rate correction.
- Does not modify Temporal (`engine/layer2_temporal.py`,
  `engine/lstm_temporal.py`, `temporal_lstm/`, `models/temporal_lstm/`,
  `data/temporal/`, `temporal_dataset/`, `temporal_validation/`).
- Does not modify the frontend.
- Does not copy, modify, or commit the raw 7.2GB historical CSV.
- Does not claim the historical dataset is AWS or IMD telemetry.

## S7 -- Production integration (output contract additions)

All additions are backward compatible (new keys only). S1-S6 evidence already
flowed into `alert.layer_details["spatial"]` and the `/api/stations/{id}/debug`
route; S7 makes it reach the primary `/api/stations/{id}/anomaly` payload and
root-cause reasoning.

New/changed canonical fields (`canonical_result`):

- `layers.spatial.regional_attribution` -- `{classification, evidence_strength, applicable_channels, explanation}` (S3), or `null` when unavailable.
- `layers.spatial.counterfactual_verification` -- `{overall_status, channel_status, summary}` (S6; `SUPPORTED` / `CONTRADICTED` / `INSUFFICIENT_EVIDENCE`), or `null`.
- `diagnosis.spatial_corroboration` -- `{state: CORROBORATED|CONFLICTING|MIXED|INSUFFICIENT, ...}` or `null`. Purely additive context: it never changes the selected category or confidence tier.
- `layers.<layer>.status == "UNAVAILABLE"` -- a layer raised; its evidence is excluded (score 0.0, marked), never treated as normal or as a fault signal.
- `AnomalyAlert.spatial_neighbor_count` / `spatial_neighbor_range_km` / `data_quality.nearby_stations` now report real values (previously always 0/None).

No double counting: fusion still consumes only the single primary spatial score
and neighbor count. S3/S6 fields are explanatory evidence states (not
probabilities) and are not fed into fusion or the category decision.

Bugs fixed (detector read keys that layer4_spatial.py never sets):
`neighbor_count` -> `total_neighbors_in_radius`, `min_distance_km` ->
`distance_range_km.min`, `deviations` -> `channel_results`. Effects: fusion's
scarcity penalty no longer fires on every station, the canonical Spatial card
reflects the real evaluation, and the narrative/insights/data-quality blocks
report real neighbor counts.

Estimated value: only produced when the diagnosis does not consider the
observation genuine (GENUINE_EXTREME_WEATHER / POSSIBLE_WEATHER_CHANGE keep the
raw reading); raw values are always preserved in `raw_values` /
`observation`.


## Phase 2 -- Spatial runtime integrity (evidence eligibility)

What counts as usable spatial evidence changed; all additions are visible in
`layers.spatial.details`:

- **Same source only.** `AWS_IN_SITU`, `NWP_MODEL_REFERENCE`, `SYNTHETIC_TEST`
  etc. are never mixed inside one neighborhood.
- **Simultaneous only.** A neighbor must have been observed within
  `CONFIG.spatial.neighbor_time_tolerance_minutes` (30, a policy default) of the
  target, by `observation_timestamp` (never the processing clock). Unknown
  observation time (target or neighbor) => not verifiable => not used.
- **Accounted exclusions.** `details.neighbor_selection` lists candidates
  considered, geographic pool, eligible pool and per-reason exclusions (self,
  duplicate station, invalid coordinate, radius, source mismatch, time
  unverified, time misaligned). `total_neighbors_in_radius` is now the
  ELIGIBLE pool size before the K cap.
- **Elevation is never invented.** Unknown stays `None`; the lapse-rate
  correction is applied only when target and neighbor elevation are both known
  (`details.elevation_adjustment.status`).
- **Pool ordering.** An older observation never overwrites a newer one in the
  detector's neighbor registry.
- **Startup order.** The WeatherUnion batch is fully pooled before any of its
  stations is evaluated.

The offline audit scripts in this directory that build `AWSReading` objects
without an `observation_timestamp` predate this contract and would now report
INSUFFICIENT_NEIGHBORS through the Spatial layer; they were not re-run.
