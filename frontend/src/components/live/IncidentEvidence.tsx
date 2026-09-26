import React from 'react';
import { Brain, FileSearch, GitBranch, ListChecks, Satellite, Users } from 'lucide-react';
import { INTERPRETATION_LABEL } from '../../services/live';
import { Card, LayerStrip, SourceBadge, fmt, fmtDateTime, pct } from './LiveBits';

const PARAM_KEY: Record<string, string> = { Temperature: 'temperature', Humidity: 'humidity', Pressure: 'pressure' };
const UNIT: Record<string, string> = { temperature: '°C', humidity: '%', pressure: 'hPa', wind_speed: 'km/h' };

const STAGE_DOT: Record<string, string> = {
  OBSERVATION: '', DETECTION: 'hit', ESCALATION: 'warn', INCIDENT_CREATED: 'hit', RECOMMENDATION: '',
  ACKNOWLEDGED: '', INVESTIGATING: '', ESCALATED: 'warn', RESOLVED: 'ok', DISMISSED: 'ok',
};

/**
 * Incident evidence (spec §11): the lifecycle narrative, what ATHER thinks is
 * happening and why, and every piece of supporting evidence captured by the
 * pipeline at detection time (incident.context).
 */
export const IncidentEvidence: React.FC<{ incident: any; onViewStation?: (id: string) => void }> = ({ incident, onViewStation }) => {
  const ctx = incident.context || {};
  const prov = ctx.provenance || {};
  const param = PARAM_KEY[incident.parameter] || (incident.parameter || '').toLowerCase();
  const unit = UNIT[param] || incident.unit || '';
  const observed = ctx.observed_values?.[param] ?? incident.observed_value;
  const expected = ctx.expected?.[param] || {};
  const ref = ctx.reference_comparison;
  const refParam = ref?.parameters?.[param];
  const lifecycle: any[] = incident.lifecycle || [];

  return (
    <>
      {prov.simulated && (
        <div className="lv-callout warn">
          This incident was produced by ATHER's detection pipeline from <b>simulated</b> AWS telemetry
          {prov.injected_fault ? <> with an injected Test Lab fault (<b>{prov.injected_fault.label}</b>, {prov.injected_fault.severity})</> : null}.
          It demonstrates the operational workflow; it is not a real field fault.
        </div>
      )}

      <div className="lv-grid-2">
        <Card title="What ATHER thinks is happening" icon={<Brain size={14} />}>
          {ctx.rca_label ? (
            <>
              <div className="lv-row" style={{ marginBottom: 8 }}>
                <span className="lv-pill lv-status-anomaly">{ctx.rca_label}</span>
                <span className={`lv-pill ${ctx.interpretation === 'likely_weather_event' ? 'lv-status-weather' : 'lv-status-unknown'}`}>
                  {INTERPRETATION_LABEL[ctx.interpretation] || ctx.interpretation}
                </span>
                <span className="lv-muted">root cause {String(incident.root_cause || '').replace(/_/g, ' ')} · {incident.root_cause_confidence} confidence</span>
              </div>
              <p style={{ fontSize: '0.82rem', lineHeight: 1.5, margin: '0 0 10px', color: 'var(--lv-ink)' }}>{ctx.summary}</p>
              <LayerStrip triggered={ctx.triggered_layers} results={ctx.layer_results} />
              <div className="lv-callout info" style={{ marginTop: 10 }}>
                <b>Recommended action — {ctx.action_label || 'Operator review'}:</b> {incident.recommended_action}
              </div>
            </>
          ) : (
            <p className="lv-muted">This incident predates the real-time pipeline, so no structured evidence bundle was captured. See the layer cards and evidence list below.</p>
          )}
        </Card>

        <Card title="Lifecycle" icon={<GitBranch size={14} />}>
          {lifecycle.length === 0 ? <p className="lv-muted">No lifecycle recorded.</p> : (
            <ol className="lv-timeline">
              {lifecycle.map((s, i) => (
                <li key={i}>
                  <span className={`lv-tl-dot ${STAGE_DOT[s.stage] ?? ''}`} />
                  <span>
                    <span className="lv-tl-stage">{s.stage.replace(/_/g, ' ')}</span>
                    <span className="lv-tl-at">{fmtDateTime(s.at)}{s.actor ? ` · ${s.actor}` : ''}</span>
                    {s.detail && <div className="lv-tl-text">{s.detail}</div>}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>

      {ctx.expected && (
        <Card title="Evidence" icon={<FileSearch size={14} />}>
          <div className="lv-table-wrap">
            <table className="lv-table">
              <thead><tr><th>Evidence</th><th>Value</th><th>Source</th></tr></thead>
              <tbody>
                <tr><td>Affected parameter</td><td><b>{incident.parameter}</b></td><td>engine diagnosis</td></tr>
                <tr><td>Abnormal (observed) value</td><td style={{ color: 'var(--lv-anomaly)', fontWeight: 800 }}>{fmt(observed, 2, ` ${unit}`)}</td><td><SourceBadge source={prov.data_source} simulated={prov.simulated} /></td></tr>
                <tr><td>Expected — neighbour consensus (L4)</td><td>{fmt(expected.spatial_consensus, 2, ` ${unit}`)}{expected.spatial_deviation != null && <span className="lv-muted"> · Δ {fmt(expected.spatial_deviation, 2)} ({fmt(expected.spatial_z, 1)}σ)</span>}</td><td>IDW of neighbour observations</td></tr>
                <tr><td>Historical baseline (station's own recent median)</td><td>{fmt(expected.rolling_median, 2, ` ${unit}`)}<span className="lv-muted"> · {expected.history_points ?? 0} pts</span></td><td>L2 rolling window</td></tr>
                <tr>
                  <td>NWP / reference value</td>
                  <td>{refParam ? <>{fmt(refParam.reference, 1, ` ${unit}`)} <span className="lv-muted">· obs − model {fmt(refParam.difference, 1)}</span></> : <span className="lv-muted">{ref?.reason || 'not available'}</span>}</td>
                  <td><span className="lv-badge lv-badge-nwp"><Satellite size={10} />MODEL / REFERENCE</span></td>
                </tr>
                <tr><td>Triggered layers</td><td colSpan={2}><LayerStrip triggered={ctx.triggered_layers} results={ctx.layer_results} compact /></td></tr>
              </tbody>
            </table>
          </div>
          {ref?.note && <p className="lv-muted" style={{ marginTop: 6 }}>{ref.note}</p>}
        </Card>
      )}

      {ctx.neighbors?.length > 0 && (
        <Card title={`Neighbouring stations at detection (${ctx.neighbors.length})`} icon={<Users size={14} />}>
          <div className="lv-table-wrap">
            <table className="lv-table">
              <thead><tr><th>Station</th><th>Distance</th><th>Temp</th><th>RH</th><th>Pressure</th><th>Status</th></tr></thead>
              <tbody>
                {ctx.neighbors.map((n: any) => (
                  <tr key={n.station_id} className={onViewStation ? 'clickable' : ''} onClick={() => onViewStation?.(n.station_id)}>
                    <td><b>{n.station_id}</b> <span className="lv-muted">{n.name}</span></td>
                    <td>{fmt(n.distance_km, 1, ' km')}</td>
                    <td>{fmt(n.temperature, 1, ' °C')}</td>
                    <td>{fmt(n.humidity, 1, ' %')}</td>
                    <td>{fmt(n.pressure, 1, ' hPa')}</td>
                    <td>{n.overall_status || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="lv-muted" style={{ marginTop: 6 }}>
            If the neighbours had shown the same change, ATHER would classify it as a weather event and open no incident.
          </p>
        </Card>
      )}

      {ctx.detection_id && (
        <Card title="Provenance" icon={<ListChecks size={14} />}>
          <dl className="lv-kv">
            <dt>Detection id</dt><dd className="lv-mono">{ctx.detection_id}</dd>
            <dt>Observation id</dt><dd className="lv-mono">{ctx.observation_id}</dd>
            <dt>Data source</dt><dd><SourceBadge source={prov.data_source} simulated={prov.simulated} /></dd>
            <dt>First observation</dt><dd>{fmtDateTime(ctx.first_observation_at)}</dd>
            <dt>Detector</dt><dd>{prov.detector_version} · {prov.pipeline_version}</dd>
            <dt>Reference model</dt><dd>{ref?.available ? `Open-Meteo NWP (model time ${ref.model_time || '—'})` : '—'}</dd>
            <dt>Confidence</dt><dd>{pct(incident.confidence)}</dd>
            {prov.injected_fault && (<><dt>Injected fault (ground truth)</dt><dd>{prov.injected_fault.label} · {prov.injected_fault.parameter || 'station'} · {prov.injected_fault.severity}</dd></>)}
          </dl>
        </Card>
      )}
    </>
  );
};
