import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, ArrowLeft, Compass, Gauge, History, Layers, Satellite, ShieldAlert } from 'lucide-react';
import { Station } from '../types/weather';
import {
  fetchStationAnomaly, fetchStationDetections, fetchStationIncidents, fetchStationLive, fetchStationTimeseries,
} from '../services/api';
import { formatAge, INTERPRETATION_LABEL, useLive, useLiveEvents } from '../services/live';
import { Card, Empty, SourceBadge, StatusPill, fmt, fmtDateTime, pct } from '../components/live/LiveBits';
import { useNow } from '../components/live/LivePanels';
import { IntelligencePipeline } from '../components/intel/IntelligencePipeline';
import { LayerScoreTable, MiniChart, PARAMS, SpatialPanel, StatusStrip } from '../components/intel/StationEvidence';
import { CONFIDENCE_NOTE, fromAssessment } from '../utils/pipeline';

interface Props {
  station: Station;
  onBack: () => void;
  onOpenIncident: (id: string) => void;
  onOpenStation: (id: string) => void;
}

const CH_LABEL: Record<string, string> = { temperature_c: 'Temperature', pressure_hpa: 'Pressure', humidity_pct: 'Humidity' };

/**
 * STATION — a focused investigation context for one AWS:
 * identity → current telemetry → sensor health → how ATHER assessed the
 * latest observation → history → anomalies → context (neighbours, NWP).
 */
export const StationWorkspace: React.FC<Props> = ({ station, onBack, onOpenIncident, onOpenStation }) => {
  const id = station.id;
  const { stations, stationsVersion, warmingIds } = useLive();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const liveState = useMemo(() => stations.get(id), [stations, stationsVersion, id]);
  const [assessment, setAssessment] = useState<any | null>(null);
  const [live, setLive] = useState<any | null>(null);
  const [series, setSeries] = useState<any | null>(null);
  const [detections, setDetections] = useState<any[]>([]);
  const [incidents, setIncidents] = useState<any[]>([]);
  const [hours, setHours] = useState(6);
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const now = useNow(5000);
  const lastHist = useRef(0);

  const loadState = useCallback(() => {
    fetchStationAnomaly(id).then(setAssessment).catch((e) => setError(e.message));
    fetchStationLive(id).then(setLive).catch(() => setLive(null));
  }, [id]);
  const loadHistory = useCallback(() => {
    fetchStationTimeseries(id, hours, 360).then(setSeries).catch(() => setSeries(null));
    fetchStationDetections(id, hours).then((d) => setDetections(d.detections || [])).catch(() => setDetections([]));
    fetchStationIncidents(id).then((r) => setIncidents(r.incidents || [])).catch(() => setIncidents([]));
  }, [id, hours]);

  useEffect(() => { setAssessment(null); setLive(null); setError(null); loadState(); }, [loadState]);
  useEffect(() => { loadHistory(); }, [loadHistory]);
  useLiveEvents(['STATION_UPDATED'], (e) => {
    if (e.data?.station_id !== id) return;
    loadState();
    if (Date.now() - lastHist.current > 15000) { lastHist.current = Date.now(); loadHistory(); setRefreshKey((k) => k + 1); }
  });

  const model = useMemo(() => (assessment
    ? fromAssessment(assessment, liveState, live?.latest_detection?.recommended_action)
    : null), [assessment, liveState, live?.latest_detection?.recommended_action]);
  const isLive = !!liveState;
  // Health, history readiness and source are separate facts: a healthy station
  // can still be gathering the history some layers need.
  const warming = !isLive && warmingIds.has(id);
  const pendingLayers = model ? model.phases[1].stages.filter((s) => s.tone === 'unassessed') : [];
  const historyPts: number | undefined = assessment?.data_quality?.historical_points;
  const readiness = !isLive ? null : !model ? '—' : !pendingLayers.length
    ? 'Ready — all five layers evaluated'
    : `Warming up — ${pendingLayers.map((s) => s.name).join(', ')} not yet evaluated${typeof historyPts === 'number' ? ` (${historyPts} observation${historyPts === 1 ? '' : 's'} so far)` : ''}`;
  const det = live?.latest_detection;
  const v = liveState?.values || {};
  const dq = assessment?.data_quality;
  const drift = assessment?.layers?.sensor_health?.details?.channel_drift || {};
  const ref = live?.reference_comparison;
  // Mark only the ONSET of each anomalous run, not every anomalous point.
  const markers = detections.filter((d, i) => d.overall_status === 'anomaly' && detections[i - 1]?.overall_status !== 'anomaly').map((d) => d.observed_at);
  const rainRecorded = !!series?.points?.some((pt: any) => typeof pt.rainfall === 'number' && pt.rainfall > 0);
  const available = new Set(series?.parameters_available || []);
  const abnormal = detections.filter((d) => d.overall_status !== 'nominal').slice().reverse();
  const openInc = incidents.filter((i) => i.status !== 'RESOLVED' && i.status !== 'DISMISSED');

  const telemetry: [string, number | null | undefined, number, string][] = isLive
    ? [['Temperature', v.temperature, 1, ' °C'], ['Humidity', v.humidity, 1, ' %'], ['Pressure', v.pressure, 1, ' hPa'],
       ['Dew point', v.dew_point, 1, ' °C'], ['Wind speed', v.wind_speed, 1, ' km/h'], ['Rainfall', v.rainfall, 1, ' mm']]
    : [['Temperature', station.temperature, 1, ' °C'], ['Humidity', station.humidity, 0, ' %'], ['Pressure', station.pressure, 1, ' hPa'],
       ['Wind speed', station.windSpeed, 1, ' km/h']];

  return (
    <div className="lv-page">
      <div>
        <button className="lv-btn" onClick={onBack}><ArrowLeft size={14} />Live map</button>
      </div>

      {/* identity */}
      <div className="lv-page-head" style={{ paddingBottom: 0 }}>
        <div>
          <div className="a-eyebrow">{id} · {(station.town && station.region && String(station.town).includes(station.region) ? station.town : [station.town, station.region].filter(Boolean).join(' · ')) || '—'}</div>
          <h1 className="a-h1">{station.name}</h1>
          <p className="a-lead lv-mono" style={{ fontSize: '0.76rem' }}>
            {station.latitude?.toFixed(4)}°N, {station.longitude?.toFixed(4)}°E
            {isLive ? ` · last observation ${formatAge(liveState?.last_observed_at, now)}` : warming ? ' · warming up — joins the live feed shortly' : ' · not monitored live'}
          </p>
        </div>
        <div className="lv-row">
          {isLive ? <StatusPill status={liveState!.overall_status} watch={liveState!.watch} /> : <span className="lv-pill lv-status-unknown">{warming ? 'Warming up' : 'Not monitored live'}</span>}
          <SourceBadge source={liveState?.source || assessment?.observation?.source} simulated={liveState?.simulated} />
          {openInc[0] && (
            <button className="lv-btn lv-btn-primary" onClick={() => onOpenIncident(openInc[0].incident_id)}><ShieldAlert size={14} />Open investigation</button>
          )}
        </div>
      </div>
      {error && <div className="lv-callout danger">{error}</div>}
      {warming && (
        <div className="lv-callout info">
          This ATHER station's simulated history is being processed through the full engine at start-up; it joins the live feed within a few minutes. Values below are the catalogue snapshot until then.
        </div>
      )}
      {!isLive && !warming && (
        <div className="lv-callout info">
          This station is in the catalogue but has no live observation feed. Its values are a static snapshot and the assessment below was run once on that snapshot, not continuously.
        </div>
      )}

      {/* current telemetry + sensor health */}
      <div className="lv-grid-2">
        <Card title="Current telemetry" icon={<Gauge size={14} />} right={<span className="lv-muted">{isLive ? `observed ${formatAge(liveState?.last_observed_at, now)}` : 'catalogue snapshot'}</span>}>
          <div className="lv-stats" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
            {telemetry.map(([l, val, d, u]) => (
              <div key={l} className="lv-stat"><span className="lv-stat-lbl">{l}</span>
                <span className="lv-stat-val" style={{ fontSize: '1.2rem' }}>{typeof val === 'number' ? fmt(val, d, u) : '—'}</span></div>
            ))}
          </div>
          {isLive && v.dew_point == null && <p className="a-note" style={{ marginTop: 8 }}>Dew point is not reported by this station.</p>}
        </Card>

        <Card title="Sensor health" icon={<Activity size={14} />}>
          {!dq ? <Empty>Loading…</Empty> : (
            <>
              <dl className="lv-kv">
                <dt>Data quality</dt><dd>{String(dq.status).replace(/_/g, ' ').toLowerCase()}</dd>
                <dt>Valid channels</dt><dd>{(dq.valid_fields || []).map((c: string) => CH_LABEL[c] || c).join(', ') || 'none'}</dd>
                <dt>Missing / invalid</dt><dd>{[...(dq.missing_fields || []), ...(dq.zero_substituted_fields || [])].map((c: string) => CH_LABEL[c] || c).join(', ') || 'none'}</dd>
                {readiness && <><dt>History readiness</dt><dd>{readiness}</dd></>}
                <dt>Freshness</dt><dd>{liveState?.freshness === 'STALE' ? 'stale — no recent observation' : (liveState?.freshness || assessment?.observation?.freshness || '—').toString().toLowerCase()}</dd>
                <dt>Suspicious now</dt><dd>{liveState?.triggered_layers?.length ? `evidence from ${liveState.triggered_layers.join(', ')}` : liveState?.watch ? 'single excursion on watch' : 'none'}</dd>
                {typeof det?.sensor_health_index === 'number' && <><dt>Sensor health index</dt><dd>{det.sensor_health_index} / 100</dd></>}
              </dl>
              {Object.keys(drift).length > 0 && (
                <table className="lv-table" style={{ marginTop: 10 }}>
                  <thead><tr><th>Channel</th><th>Drift</th><th>Bias</th><th>Reference</th></tr></thead>
                  <tbody>
                    {Object.entries(drift).map(([ch, c]: [string, any]) => (
                      <tr key={ch}><td>{CH_LABEL[ch] || ch}</td><td>{String(c.drift_tier).replace(/_/g, ' ').toLowerCase()}</td>
                        <td className="a-num">{typeof c.estimated_bias === 'number' ? c.estimated_bias.toFixed(2) : '—'}</td>
                        <td className="lv-muted">{c.reference_mode === 'SPATIAL' ? 'neighbours' : c.reference_mode === 'BACKGROUND' ? 'NWP' : c.reference_mode === 'SUSPENDED_SATURATION' ? 'suspended (saturated)' : 'own history'}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
              {live?.active_faults?.length > 0 && (
                <div className="lv-callout warn" style={{ marginTop: 10 }}>Test Lab fault active: {live.active_faults.map((f: any) => `${f.label} (${f.parameter || 'station'}, ${f.severity})`).join(', ')}.</div>
              )}
            </>
          )}
        </Card>
      </div>

      {/* intelligence pipeline */}
      <Card title="How ATHER assessed the latest observation" icon={<Layers size={14} />}
        right={liveState ? <span className="lv-muted">{fmtDateTime(liveState.last_observed_at)}</span> : undefined}>
        {!model ? <Empty>Loading assessment…</Empty> : (
          <>
            <div className="lv-row" style={{ marginBottom: 12 }}>
              {liveState && <StatusPill status={liveState.overall_status} watch={liveState.watch} />}
              {liveState?.interpretation && <span className="lv-pill lv-status-unknown">{INTERPRETATION_LABEL[liveState.interpretation]}</span>}
              {model.headline.confidence !== null && <span className="lv-muted" title={CONFIDENCE_NOTE}>confidence {pct(model.headline.confidence)}*</span>}
            </div>
            {model.headline.summary && <p style={{ margin: '0 0 14px', fontSize: '0.86rem', lineHeight: 1.5 }}>{model.headline.summary}</p>}
            {liveState?.freshness === 'STALE' && (
              <div className="lv-callout warn" style={{ marginBottom: 12 }}>
                Telemetry is stale: the newest observation is from {formatAge(liveState.last_observed_at, now)}. The layer
                evidence below is historical — it belongs to the observation of {fmtDateTime(liveState.last_observed_at)},
                not to the station's current state.
              </div>
            )}
            <IntelligencePipeline model={model} />
          </>
        )}
      </Card>

      {/* history */}
      <Card title="Historical behaviour" icon={<History size={14} />}
        right={<div className="lv-tabs">{[1, 6, 24].map((h) => <button key={h} className={`lv-tab ${hours === h ? 'active' : ''}`} onClick={() => setHours(h)}>{h}h</button>)}</div>}>
        {!isLive ? <Empty>{warming ? 'History warming up — this station joins the live feed shortly.' : 'No recorded telemetry — this station is not monitored live.'}</Empty>
          : !series?.points?.length ? <Empty>No telemetry recorded in the last {hours} h.</Empty>
          : series.points.length < 3 ? <Empty>History warming up — {series.points.length} observation{series.points.length === 1 ? '' : 's'} recorded so far; trend charts and temporal analysis become available after 3 observations.</Empty> : (
          <>
            <div className="lv-grid-2" style={{ gap: 14 }}>
              {PARAMS.filter((p) => available.has(p.key) && (p.key !== 'rainfall' || rainRecorded)).map((p) => (
                <div key={p.key}>
                  <div className="a-eyebrow" style={{ marginBottom: 2 }}>{p.label} ({p.unit}){p.key === 'dew_point' && series.points.some((x: any) => x.dew_point_derived) ? ' · derived' : ''}</div>
                  <MiniChart points={series.points} param={p} markers={markers} />
                </div>
              ))}
            </div>
            <div style={{ marginTop: 14 }}>
              <div className="a-eyebrow" style={{ marginBottom: 6 }}>Detection status per observation</div>
              <StatusStrip detections={detections} />
            </div>
            <p className="a-note" style={{ marginTop: 6 }}>{series.points.length} points{series.downsampled ? ' (time-bucket means)' : ''}. Dashed lines mark the onset of each critical episode.{available.has('rainfall') && !rainRecorded ? ' No rainfall recorded in this window.' : ''}</p>
          </>
        )}
      </Card>

      {/* anomalies */}
      <div className="lv-grid-2">
        <Card title={`Detected events (${hours} h)`} icon={<ShieldAlert size={14} />}>
          {!isLive ? <Empty>{warming ? 'No detected events yet — history is warming up.' : 'Not monitored live.'}</Empty>
            : !abnormal.length ? <Empty>{pendingLayers.length ? 'No detected events yet. Detection history is still warming up.' : `No anomalies detected — no warning, degraded or critical observations in the last ${hours} h.`}</Empty>
            : <LayerScoreTable detections={detections} />}
        </Card>
        <Card title="Investigations for this station" icon={<ShieldAlert size={14} />}>
          {!incidents.length ? <Empty>No active investigation.</Empty> : (
            <table className="lv-table">
              <thead><tr><th>ID</th><th>Finding</th><th>Severity</th><th>Status</th><th>Opened</th></tr></thead>
              <tbody>
                {incidents.slice(0, 8).map((i) => (
                  <tr key={i.incident_id} className="clickable" onClick={() => onOpenIncident(i.incident_id)}>
                    <td className="lv-mono" style={{ fontSize: '0.72rem' }}>{i.incident_id}</td>
                    <td>{i.context?.rca_label || String(i.root_cause || '').replace(/_/g, ' ').toLowerCase()}</td>
                    <td>{i.severity?.toLowerCase()}</td><td>{i.status?.toLowerCase()}</td>
                    <td className="lv-muted">{formatAge(i.created_at, now)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      {/* context */}
      {isLive && (
        <div className="lv-grid-2">
          <SpatialPanel stationId={id} refreshKey={refreshKey} onSelectStation={onOpenStation} />
          <Card title="Weather model reference" icon={<Satellite size={14} />} right={<span className="lv-badge lv-badge-nwp">MODEL DATA</span>}>
            {!ref?.available ? <Empty>{ref?.reason || 'Reference source unavailable'}</Empty> : (
              <>
                <table className="lv-table">
                  <thead><tr><th>Variable</th><th>Observed</th><th>Model</th><th>Difference</th></tr></thead>
                  <tbody>
                    {Object.entries(ref.parameters || {}).map(([k, p]: [string, any]) => (
                      <tr key={k}><td>{k.replace('_', ' ')}</td><td>{fmt(p.observed, 1, ` ${p.unit}`)}</td><td>{fmt(p.reference, 1, ` ${p.unit}`)}</td>
                        <td style={{ fontWeight: 700 }}>{p.difference == null ? '—' : `${p.difference > 0 ? '+' : ''}${p.difference.toFixed(1)} ${p.unit}`}</td></tr>
                    ))}
                  </tbody>
                </table>
                <p className="a-note" style={{ marginTop: 8 }}>Open-Meteo NWP, model time {ref.model_time || '—'}{ref.stale ? ' (stale)' : ''}. {ref.note}</p>
              </>
            )}
          </Card>
        </div>
      )}
      <p className="a-note"><Compass size={11} style={{ verticalAlign: -1 }} /> Detection runs continuously in the backend; this page only reads its results and updates when this station reports.</p>
    </div>
  );
};
