# ATHER product structure and UI system

ATHER's UI tells one story:

> ATHER continuously observes AWS telemetry, detects abnormal behaviour, combines independent evidence layers, explains why an anomaly occurred, and turns that evidence into an operational insight.

Workflow: **OBSERVE → DETECT → PROVE → EXPLAIN → ACT**.

## Information architecture

| Destination | Answers | File |
|---|---|---|
| Home (public) | What is ATHER? "Launch ATHER" opens Overview | `pages/HomePage.tsx` |
| **Overview** | What is happening across the network right now? | `workspaces/OverviewWorkspace.tsx` |
| **Live Map** | Where is it happening? | `workspaces/MapWorkspace.tsx` |
| **Investigations** | What happened, why, and what should we do? | `workspaces/InvestigationsWorkspace.tsx` + `components/intel/InvestigationConsole.tsx` |
| **Test Lab** | Does the engine behave as designed? Kept separate from operations. | `workspaces/TestLabWorkspace.tsx` + `components/intel/ScenarioSuite.tsx` |
| Station (in-product) | Focused context for one AWS | `workspaces/StationWorkspace.tsx` |
| System (from the LIVE indicator) | Is the pipeline healthy? | `workspaces/SystemWorkspace.tsx` |

URLs: `/`, `/overview`, `/map`, `/investigations`, `/test-lab`, `/station`, `/system`.

Old links still resolve:
- `/anomalies` and `/incidents` → `/investigations`
- `/health` → `/overview`

## The intelligence pipeline (one component, everywhere)

`utils/pipeline.ts` normalizes both backend shapes into the same 10 stages:
- the station assessment, `GET /api/stations/{id}/anomaly`
- a stored DetectionResult, `GET /api/detections/{id}`

`components/intel/IntelligencePipeline.tsx` renders the stages. The station page, the investigation console and the Test Lab all use this one view.

| Phase | Stages |
|---|---|
| OBSERVE | 1 Data quality |
| DETECT | 2 Physics · 3 Temporal · 4 Multivariate · 5 Spatial · 6 Sensor health |
| FUSE | 7 Evidence fusion · 8 Anomaly decision |
| EXPLAIN | 9 Root cause |
| ACT | 10 Operational insight |

Each stage shows four things, and expands to the evidence the backend reported:
- what it checks
- its state
- what it found
- how it contributed

## Integrity rules (enforced in code, not by convention)

- **Nothing is estimated in the browser.** The backend is the only judge. The client-side "validation verdict" (`aws/awsGeo.ts`) and the duplicate TypeScript engine (`utils/atherEngine.ts`) were removed.
- **Not evaluated ≠ passed.** A layer that could not assess an observation shows *Not evaluated* with the backend's reason, is excluded from fusion, and never gets a 0 score. This reuses `utils/layerEvidence.ts`.
- **Layer scores** are labelled *evidence scores, not probabilities*.
- **Confidence** always carries the backend's own caveat: a heuristic evidence-quality score, not a calibrated probability.
- **Simulated data** is badged SIMULATED wherever it appears. Model (NWP) data is badged MODEL DATA.
- **Missing values render as "—"**, never as a fallback number. The homepage's placeholder counts were replaced.
- **Investigation "before/at onset"** values come from the recorded time series, because the incident's evidence context is refreshed with every observation.
- **Test Lab outcomes** are shown as *Matches* or *Differs*, never forced, and labelled as synthetic test performance.

## Design system

Everything lives in `styles/ather-theme.css` (tokens on `:root`). It is derived from the homepage identity, so the landing page and the app are one product.

| Role | Token | Value |
|---|---|---|
| Page / secondary / card | `--a-bg` / `--a-bg-2` / `--a-surface` | `#F7F6F1` / `#F2F0E8` / `#FFFFFF` |
| Ink (text, primary buttons) | `--a-ink` · `--a-ink-2` · `--a-ink-3` | `#111214` · `#5F6164` · `#8C8E91` |
| Brand accent: brand mark, active nav, focus only, never data | `--a-accent` | `#D97706` |
| Status: nominal / warning / critical / weather-info / neutral | `--s-*` | `#46A477` / `#D49A1A` / `#9B1C24` / `#2F6DB5` / `#8C8E91` |
| Type | `--a-font` / `--a-mono` | Plus Jakarta Sans / JetBrains Mono |

**Status palette.** The palette was checked with the dataviz palette validator against the ivory surface (all pairs pass, including colour-vision separation). Status is always paired with a label or an icon, never colour alone. Status *text* uses darker `--s-*-ink` companions for contrast. "Degraded / not monitored live" is the neutral grey, not a fifth hue.

**Map.**
- Markers use the same palette.
- Only critical (or selected) stations animate; nominal stations are static.
- Catalogue-only stations render neutral, because they are not evaluated live.

## Removed

**Screens.** The Sensor Health workspace and the legacy Network Overview. Their content moved into Overview and the station page.

**Legacy components that nothing reachable imported.** These were:
- the old top bars, drawers and map container
- the legacy station panel
- the old incident detail
- the legacy Test Lab modal

**Decoration.** The star field, the sun, the 3D station model, and the spinning rotors / radar rings on nominal stations.

**Other.** The duplicate TypeScript engine, and 7.4 MB of unreferenced public assets.

**Nav changes.** The globe toggle now lives in the map's own controls. The status filter lives in the map's filter bar, not the display popover.

## Follow-ups

- `three`, `@react-three/*` and `globe.gl` are no longer imported. They can be removed from `package.json` together with a lockfile refresh (npm and bun).
- `index.css` still contains rules for removed components. They are harmless, but can be pruned.
- Local `data/incidents.db` files created before the source-labelling fix still hold legacy rows filed as `LIVE_AWS` (for example, root cause NORMAL). Clearing that local, gitignored file removes them.
