# ATHER real-time architecture

How ATHER turns the existing 5-layer anomaly engine into a continuously running
detection system, what was measured along the way, and how it scales.

## 1. What changed, in one paragraph

Before this work, detection ran only at startup, on `POST /api/ingest`, or lazily
when a user clicked a station. Station history was a synthesized sine wave, and the
dashboard's counts were partly hard-coded. Now every observation flows through
one pipeline:

```
source adapters ──► ingest: schema · timestamp · units · catalogue ──► ObservationStream
   ──► ObservationProcessor (worker thread): 5 layers + conformal fusion ──► DetectionResult
   ──► TimeSeriesStore (observations + detections) · station health · incidents
   ──► EventBroker ──► GET /api/stream (SSE) ──► Command Center
```

The browser loads one snapshot (`/api/network/state`) and then only applies events.
Station history is fetched per station, per time window, on demand.

## 2. Components

| Component | File | Role |
|---|---|---|
| Inbound contract | `backend/app/pipeline/models.py` | `ObservationIn`: well-formedness only. Physically impossible values are *valid payloads* so they can reach L1. |
| Normalization | `backend/app/pipeline/normalize.py` | Unit conversion (°F/K, Pa/kPa/inHg, m/s/kt/mph, fraction RH), future-timestamp rejection, LATE flag, deterministic `observation_id`. |
| Stream | `backend/app/pipeline/stream.py` | Bounded `asyncio.Queue`; back-pressure for adapters, 503 for push when full; micro-batches for the consumer. |
| Processor | `backend/app/pipeline/processor.py` | Dedup, out-of-order handling, synchronous spatial snapshot, engine call, DetectionResult, health, incident policy, events. |
| DetectionResult | `backend/app/pipeline/detection.py` | Spec §7 record: status, confidence, triggered layers, per-layer results, fusion, evidence, expected values, neighbours, NWP comparison, action, provenance. |
| Store | `backend/app/pipeline/store.py` | SQLite (WAL): `observations`, `detections`; time-bucket downsampling; retention. |
| Events | `backend/app/pipeline/events.py` | Monotonic ids, 2,000-event replay ring, thread-safe publish, `RESYNC_REQUIRED` for slow clients. |
| Runtime | `backend/app/pipeline/runtime.py` | Starts adapters, consumer, staleness monitor, heartbeat, retention; exposes read models. |
| API | `backend/app/pipeline/api.py` | SSE, snapshot, health, per-station views, lab, replay. |
| Replay | `backend/app/pipeline/replay.py` | Same processor code with a fresh detector, shadow registry, null store and virtual incidents. |
| Adapters | `backend/app/sources/` | Simulation, NOAA ISD, Weather Union, IMD (stub), Open-Meteo reference. |
| Live UI store | `frontend/src/services/live.tsx` | One EventSource per tab; snapshot → `since=event_seq` → incremental updates. |

## 3. Data sources: what is real, what is not

| Adapter | Kind | State by default | Notes |
|---|---|---|---|
| `SimulationAdapter` | observations | **active** | Generates telemetry for the 296 real WeatherUnion AWS *locations*. Tagged `SIMULATED_AWS` everywhere and labelled SIMULATED in the UI. |
| `NOAAISDAdapter` | observations | not configured | Real hourly synoptic data from NCEI. Enable with `ATHER_NOAA_STATIONS=<USAF+WBAN,...>`. The parser is unit-tested; it has not been exercised against the live endpoint in this environment. |
| `WeatherUnionAdapter` | observations | not configured | Needs `WEATHERUNION_API_KEY`. Uses a daily call budget and rotates through localities. Written against the public v0 API; not verified here. |
| `IMDAWSAdapter` | observations | not configured | IMD has no public real-time API. Integrate by POSTing to `/api/observations`. |
| `OpenMeteoReferenceAdapter` | **reference** | active | Keeps the NWP cache warm at the model's hourly cadence. **Never** emits observations. If it fails, detection continues and the UI shows "Reference source unavailable". |

The 1,655 stations in `data/stations.json` are a frozen community-mesonet
snapshot with no verifiable observation time. Incidents derived from them are
now filed as `STATIC_SNAPSHOT`, not `LIVE_AWS`, and are excluded from operational
views.

## 4. Decisions

**ADR-1 · In-process queue, not Redis/Kafka.**
The engine costs 1.1–1.6 ms per observation on one thread, about 600–900 obs/s. An
India-wide network of 5,000 stations at a 5-minute cadence needs about 17 obs/s, which
is roughly 2–3% of one core. A broker would add an operational dependency (there is no
Redis on the target machine) without solving any current problem. The stream
interface (`put` / `put_nowait` / `get_batch`) is the seam. A Redis Streams
implementation (XADD / XREADGROUP / XACK) gives at-least-once delivery across
processes, and redelivery is already harmless because processing is idempotent on
`observation_id`. Kafka becomes relevant only when a single consumer group can no
longer keep up. Flink becomes relevant only if windowed joins leave the Python engine.

**ADR-2 · SQLite (WAL), not TimescaleDB, for now.**
The project already uses stdlib `sqlite3` for incidents, and no database server is
available. A single writer (the pipeline thread) commits one transaction per
micro-batch, and API readers use their own WAL connections. Nominal detections are
stored compactly, while abnormal ones keep full evidence. Retention defaults to 24 h
(`ATHER_RETENTION_HOURS`). A TimescaleDB store maps directly: hypertables for both
tables, `time_bucket()` for `history()`, a retention policy for `prune()`, and
continuous aggregates for long windows.

**ADR-3 · SSE, not WebSocket.**
Traffic is server-to-client only. SSE works through the Vite proxy, reconnects
natively and resends `Last-Event-ID`, and needs no extra dependency.
Operator actions stay ordinary REST calls, and their results are broadcast as
`INCIDENT_UPDATED`.

**ADR-4 · Synchronous spatial snapshot per micro-batch.**
All readings in a batch enter the neighbour pool *before* any is evaluated, so L4
compares stations observed at the same instant. Without this, a front reaching ten
stations in one batch looked like ten isolated spikes. Neighbours must also be
fresh, within 250 km, and of the same source class: a real sensor is never
"corroborated" by simulated data, and NWP values are never neighbours.

**ADR-5 · Two axes: sensor trust vs interpretation.**
The engine's fusion marks a corroborated regional change as `ANOMALY /
GENUINE_EXTREME_WEATHER`, and the old path would have opened a *maintenance
incident for a thunderstorm*. Each DetectionResult now carries `overall_status`
(nominal / suspect / degraded / anomaly, i.e. how far to trust the sensor) and
`interpretation` (likely sensor fault / likely weather event / communication issue /
uncertain). Weather-classified detections never open incidents.

**ADR-6 · Incident policy and alarm hysteresis.**
`anomaly` opens or updates an incident immediately. `suspect` opens one only after
two consecutive observations with a *diagnosed* fault cause. A single undiagnosed
statistical excursion is shown as nominal + watch for one observation, and the raw
engine verdict is still stored. The pipeline, which holds history the per-observation
classifier cannot see, applies two further rules:
- A "weather" verdict right after a sensor-fault verdict is treated as a sensor
  recovery or reset.
- Weather claims are withheld for one hour after a sensor fault, while the temporal
  baseline is still contaminated.

Open incidents are correlated per station + parameter + source, so one physical problem
stays one incident while its diagnosis evolves. For example, a first-reading `SENSOR_SPIKE`
that persists is re-diagnosed as `SINGLE_CHANNEL_FAULT`, and this is recorded as
`DIAGNOSIS_REVISED` on the incident's timeline.

**ADR-7 · Staleness is a station-level signal only when the source is healthy.**
If a station is silent for more than 3 cadences it becomes degraded. After more than
5 cadences a `COMMUNICATION_OUTAGE` incident opens. If the whole adapter is down,
that shows as one source outage rather than hundreds of station incidents.

**ADR-8 · Replay reuses production code.**
Replay runs the same `ObservationProcessor` against isolated state, so a replay
cannot drift from real behaviour, and it cannot write production state (a test
asserts this).

## 5. Engine findings from running continuously

Running the engine on continuous data for the first time exposed defects that
single-snapshot evaluation never hit. Each was verified with a harness before and
after the fix.

| # | Finding | Fix |
|---|---|---|
| 1 | **L5 flagged normal diurnal cycles as drift.** CUSUM ran on `value − EMA(value)`, so RH falling ~8%/h every morning accumulated like calibration drift. It produced 225 false incidents in 2 h on a healthy 296-station network. | L5 tracks drift on the residual against the **L4 neighbour consensus** (or an NWP background), where weather is common-mode. Raw mode is kept only when no reference exists. |
| 2 | L5 constants assumed a 10-min cadence (×144 samples/day, per-sample leak and EMA). | Increments and EMA are weighted by elapsed time. Behaviour is identical at 10-min spacing. |
| 3 | The README claimed Mann-Kendall, but it was not implemented. | Kendall's τ trend test now gates tolerance-breach projections. |
| 4 | L2 stuck-sensor test was count-based (12 readings), so a healthy 1-min barometer looked frozen. | Requires the unchanged run to span ≥ 60 min (`ATHER_FROZEN_MIN_SPAN_MIN`). |
| 5 | L2 robust z-score: in quiet periods the MAD collapsed to the 0.1 °C quantization step, so a 0.6 °C change scored z ≈ 4 ("genuine extreme weather"). | MAD floor at WMO-No. 8 achievable uncertainty (T 0.2 K, P 0.15 hPa, RH 1%). |
| 6 | **L4 and L3 canonical keys missing.** L4 wrote `total_neighbors_in_radius`, and L3 wrote `n_valid`, while the detector, cards and fusion read `neighbor_count` and `valid_channel_count`. Result: UI "0 neighbours" / "0 channels", and understated fusion coverage and confidence for every station. | Both layers now emit the expected keys. Regression tests added. |
| 7 | Classifier checked "statistical outlier" before "spatial outlier", so a sustained isolated step became `NOISE_BURST`. | Spatial-isolation rule runs first. |
| 8 | A drifting sensor snapping back into agreement with its neighbours was called weather. | Classifier guard plus pipeline history rule (ADR-6). |
| 9 | Saturation: RH plateaus near 97–100% in fog or rain were read as stuck sensors, and RH residuals shift non-linearly across a dry → saturated regime change. | L2 persistence exemption from 97% RH; L5 suspends RH drift tracking above 95%. |
| 10 | After a stuck sensor recovered, its frozen values stayed in the L2 baseline for hours. | The frozen run is purged from the baseline when it ends. |

**Measured outcome.** 296 simulated stations at a 1-min cadence over 2 h (35,520 observations):
- Before the fixes: 225 false incidents; most stations "degraded" or "anomaly".
- After: **99.6% nominal, 0 incidents**. The residual 0.4% are persistent single-channel statistical excursions, shown as suspect and never escalated.

**Fault sweep.** Replay of 8 fault types × 3 severities:
- Every sensor fault opens an incident.
- Time to detection:
  - spike, impossible RH, T/RH inconsistency: next observation
  - stuck: 55–60 min (by design)
  - drift: 35–115 min, depending on rate
- Regional weather events open **0 incidents at every severity**. In the live run, 32 of 32 affected stations were classified as weather.
- Known behaviour: after a drift or spike fault ends, the station can stay flagged for up to about 2 h while L5 CUSUM decays. This is conservative, since the incident is already open.

## 6. Latency (live, 296 stations, 15–20 s simulated cadence)

| Stage | p50 | p95 |
|---|---|---|
| Ingestion (observed → received) | ~0.4–0.5 s (the simulator stamps whole seconds) | ~0.5 s |
| Queue wait | 1.5 ms | 4 ms |
| Processing (5 layers + fusion + persistence) | 1.3–1.4 ms | 2 ms |
| End-to-end (observed → event published) | ~0.8–1.0 s | ~1.1 s |

## 7. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `ATHER_PIPELINE_ENABLED` | 1 | Start the runtime with the API |
| `ATHER_SIM_ENABLED` | 1 | Run the simulated feed |
| `ATHER_SIM_INTERVAL_S` | 60 | Simulated cadence per station (labelled in the UI) |
| `ATHER_SIM_MAX_STATIONS` | all | Limit simulated stations |
| `ATHER_REFERENCE_ENABLED` | 1 | Keep the Open-Meteo reference warm |
| `ATHER_RETENTION_HOURS` | 24 | Time-series retention |
| `ATHER_INGEST_TOKEN` | — | If set, required as `X-ATHER-Token` on `POST /api/observations` |
| `ATHER_NOAA_STATIONS` | — | Enables the NOAA ISD adapter |
| `WEATHERUNION_API_KEY` | — | Enables Weather Union (server-side only) |
| `ATHER_FROZEN_MIN_SPAN_MIN` | 60 | L2 persistence window |
| `ATHER_TIMESERIES_DB_PATH` / `ATHER_INCIDENTS_DB_PATH` | `data/*.db` | Storage locations (tests use temp files) |

Credentials exist only in the backend environment. The React app never sees them.
Open-Meteo calls now verify TLS (they previously disabled certificate checks).

## 8. Real-time API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/stream?since=<id>` | SSE: `STATION_UPDATED`, `ANOMALY_DETECTED`, `WEATHER_EVENT_DETECTED`, `STATION_RECOVERED`, `STATION_STALE`, `INCIDENT_CREATED`, `INCIDENT_UPDATED`, `DATA_SOURCE_STATUS_CHANGED`, `SYSTEM_METRICS`, `FAULT_*`, `REPLAY_*`, `RESYNC_REQUIRED` |
| GET | `/api/network/state` | Snapshot + `event_seq` |
| GET | `/api/system/health` · `/api/sources` | Components, latency, throughput, sources |
| POST | `/api/observations` | Push ingestion (validated, queued, 202; per-item rejections) |
| GET | `/api/stations/{id}/live` · `/timeseries` · `/detections` · `/spatial` | Station workspace data, per time window |
| GET | `/api/detections/{id}` | Full DetectionResult with provenance |
| GET/POST/DELETE | `/api/lab/fault-types` · `/api/lab/faults[/{id}]` | Live fault injection |
| POST/GET | `/api/replay` · `/api/replay/{id}` | Replay |

The pre-existing endpoints keep their contracts, with these changes:
- `/api/ingest` now runs through the pipeline.
- `/observations` returns persisted telemetry, never a synthesized curve.
- `GET /anomaly` no longer writes incidents for pipeline-fed stations.
- `/api/incidents` accepts `source=LIVE_AWS,SIMULATED_FEED`.

## 9. Tests

`backend/tests/test_realtime.py` adds 34 tests to the original 86 (120 total). They cover:
- normalization and unit conversion
- future and late timestamps
- duplicate and out-of-order observations
- detector failure isolation
- source failure with backoff
- "reference unavailable"
- broker replay and resync
- the incident lifecycle
- weather-vs-sensor classification
- each engine fix
- the simulator
- the NOAA parser
- replay isolation
- staleness incidents
- **an end-to-end test over real HTTP and SSE**: observation → ingestion → engine → anomaly → incident → persisted → API → live event

## 10. Not done / next steps

- Dead frontend code still in the tree, recommended for removal:
  - `MapContainer`, `AtherStationDrawer`, `GlobalStationDrawer`, `AtherTopBar`, `MenuDrawer`, `BottomControlBar`, `AtherScenarioBar`, `LayerSwitcher`, `MeteogramPanel`, `InfoModal`, `WebcamModal`, `TopSearchBar`, `TimelineSlider`
  - `utils/atherEngine.ts`, a second TypeScript copy of the engine that nothing live uses
  - `ather/frontend/frontend folder/`
- Engine L2/L5 state lives in memory. On restart it is re-warmed from the last 20 persisted observations per station, not restored exactly.
- Real station elevation is missing for the WeatherUnion catalogue (0 m assumed).
- The NOAA and Weather Union adapters need live-endpoint verification with real credentials and station lists.
- The homepage's illustrative "platform preview" still contains static example numbers (the homepage was intentionally left as designed).
