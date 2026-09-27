import React, { useEffect, useMemo, useState } from 'react';
import { MapPinned, Siren, UserCheck, Search as InvestigateIcon, XCircle, CheckCircle2 } from 'lucide-react';
import {
  acknowledgeIncident, dismissIncident, fetchDetection, fetchIncidentDetail, fetchStationTimeseries, investigateIncident, resolveIncident,
} from '../../services/api';
import { INTERPRETATION_LABEL, formatAge, useLive, useLiveEvents } from '../../services/live';
import { Empty, SourceBadge, fmt, fmtDateTime, pct } from '../live/LiveBits';
import { IntelligencePipeline } from './IntelligencePipeline';
import { MiniChart, PARAMS } from './StationEvidence';
import { CONFIDENCE_NOTE, PipelineModel, fromAssessment, fromDetection } from '../../utils/pipeline';
import { EscalationPreviewModal } from '../EscalationPreviewModal';
import { ResolveIncidentModal } from '../ResolveIncidentModal';
import { DismissIncidentModal } from '../DismissIncidentModal';

const PARAM_KEY: Record<string, string> = { Temperature: 'temperature', Humidity: 'humidity', Pressure: 'pressure' };
const UNIT: Record<string, string> = { temperature: '°C', humidity: '%', pressure: 'hPa' };
const NEXT: Record<string, string[]> = {
  NEW: ['ACKNOWLEDGED', 'DISMISSED'], ACKNOWLEDGED: ['INVESTIGATING', 'DISMISSED'],
  INVESTIGATING: ['ESCALATED', 'RESOLVED', 'DISMISSED'], ESCALATED: ['RESOLVED', 'DISMISSED'],
};
const STAGE_DOT: Record<string, string> = {
  DETECTION: 'hit', INCIDENT_CREATED: 'hit', ESCALATION: 'warn', ESCALATED: 'warn', RESOLVED: 'ok', DISMISSED: 'ok', DIAGNOSIS_REVISED: 'warn',
};

const Q: React.FC<{ n: string; label: string; wide?: boolean; children: React.ReactNode }> = ({ n, label, wide, children }) => (
  <div className={`a-q ${wide ? 'wide' : ''}`}>
    <div className="a-q-label"><b>{n}</b>{label}</div>
    <div style={{ minWidth: 0 }}>{children}</div>
  </div>
);

/**
 * One investigation, told in order:
 * what happened → when → where → what changed → which layers detected it &
 * the evidence → how certain → root cause → context → operational insight.
 * Detection (stage 1), evidence (layers), fusion, root cause and insight stay
 * visibly separate — never collapsed into one "anomaly detected" message.
 */
export const InvestigationConsole: React.FC<{
  incidentId: string;
  onOpenStation: (id: string) => void;
  onShowOnMap: (id: string) => void;
}> = ({ incidentId, onOpenStation, onShowOnMap }) => {
  const [inc, setInc] = useState<any | null>(null);
  const [det, setDet] = useState<any | null>(null);
  const [series, setSeries] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState<'escalate' | 'resolve' | 'dismiss' | null>(null);
  const { stations, stationsVersion } = useLive();

  const load = () => fetchIncidentDetail(incidentId).then(setInc).catch((e) => setError(e.message));
  useEffect(() => { setInc(null); setDet(null); setSeries(null); setError(null); load(); /* eslint-disable-next-line */ }, [incidentId]);
  useEffect(() => {
    const id = inc?.context?.detection_id;
    if (id) fetchDetection(id).then(setDet).catch(() => setDet(null));
    if (inc?.station_id) fetchStationTimeseries(inc.station_id, 6, 240).then(setSeries).catch(() => setSeries(null));
  }, [inc?.context?.detection_id, inc?.station_id]);
  useLiveEvents(['INCIDENT_UPDATED'], (e) => { if (e.data?.incident_id === incidentId) load(); });

  const model: PipelineModel | null = useMemo(() => {
    if (det) return fromDetection(det);
    if (!inc) return null;
    // Incidents opened before evidence capture: rebuild from the stored layer cards.
    const layers = { ...(inc.diagnostic_layers || {}) };
    if (layers.drift && !layers.sensor_health) layers.sensor_health = layers.drift;
    return fromAssessment({
      layers, status: inc.fusion_result?.status || inc.status,
      overall: { confidence: inc.confidence, score: inc.anomaly_score },
      diagnosis: { primary: inc.root_cause, confidence: inc.root_cause_confidence, evidence: inc.evidence },
      operator_action: inc.recommended_action,
    });
  }, [det, inc]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const liveNow = useMemo(() => (inc ? stations.get(inc.station_id) : undefined), [stations, stationsVersion, inc?.station_id]);

  if (error) return <Empty>{error}</Empty>;
  if (!inc) return <Empty>Loading investigation…</Empty>;

  const ctx = inc.context || {};
  const prov = ctx.provenance || {};
  const param = PARAM_KEY[inc.parameter] || (inc.parameter || '').toLowerCase();
  const unit = UNIT[param] || inc.unit || '';
  const exp = ctx.expected?.[param] || {};
  const atDetection = ctx.observed_values?.[param] ?? inc.observed_value;
  const nowVal = liveNow?.values?.[param];
  const chartParam = PARAMS.find((p) => p.key === param);
  const detectedEpoch = Date.parse(ctx.first_observation_at || inc.observation_timestamp || inc.detected_at) / 1000;
  const ref = ctx.reference_comparison;
  const allowed = NEXT[inc.status] || [];
  const closed = inc.status === 'RESOLVED' || inc.status === 'DISMISSED';
  const isWeather = ctx.interpretation === 'likely_weather_event';
  // Before/onset come from the recorded series: the incident's evidence
  // context is refreshed with every new observation, so its "recent median"
  // describes the latest reading, not the pre-fault baseline.
  const pts: any[] = series?.points || [];
  const has = (pt: any) => typeof pt?.[param] === 'number';
  const before = Number.isFinite(detectedEpoch) ? [...pts].reverse().find((pt) => pt.epoch < detectedEpoch - 1 && has(pt)) : undefined;
  const onset = Number.isFinite(detectedEpoch) ? pts.find((pt) => pt.epoch >= detectedEpoch - 1 && has(pt)) : undefined;

  const act = async (fn: () => Promise<any>) => {
    setBusy(true);
    try { setInc(await fn()); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* summary */}
      <section className="lv-card">
        <div className="lv-card-body" style={{ padding: '18px 20px' }}>
          <div className="lv-spread" style={{ alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <div>
              <div className="a-eyebrow">{inc.incident_id} · {inc.status.toLowerCase()}</div>
              <h2 className="a-h1" style={{ fontSize: '1.25rem' }}>{ctx.rca_label || `${inc.parameter} anomaly`} — {inc.station_name || inc.station_id}</h2>
              <p className="a-lead" style={{ fontSize: '0.84rem' }}>{ctx.summary || (inc.evidence || []).join('; ') || 'No summary was captured for this investigation.'}</p>
            </div>
            <div className="lv-row">
              <span className={`lv-pill ${inc.severity === 'CRITICAL' ? 'lv-status-anomaly' : 'lv-status-suspect'}`}><span className="lv-dot" />{inc.severity}</span>
              {inc.source === 'SIMULATED_FEED' && <SourceBadge simulated />}
            </div>
          </div>
          {prov.injected_fault && (
            <div className="lv-callout warn" style={{ marginTop: 12 }}>
              Produced from simulated telemetry with a Test Lab fault (<b>{prov.injected_fault.label}</b>, {prov.injected_fault.severity}). ATHER was not told a fault existed.
            </div>
          )}
          {!inc.context && (
            <div className="lv-callout info" style={{ marginTop: 12 }}>
              Opened before per-detection evidence capture existed: only the stored layer cards and evidence list are available for this investigation.
            </div>
          )}
        </div>
      </section>

      <section className="lv-card">
        <div className="lv-card-body" style={{ padding: '6px 20px 18px' }}>
          <Q n="01" label="What happened">
            <div className="lv-row" style={{ marginBottom: 6 }}>
              <span className="lv-pill lv-status-unknown">Detection</span>
              <span style={{ fontSize: '0.86rem' }}>{inc.parameter} reading at {inc.station_name || inc.station_id} was judged <b>{String(det?.overall_status || inc.fusion_result?.status || 'abnormal').toLowerCase()}</b> by the fused evidence.</span>
            </div>
            <div className="lv-muted">Root cause code {String(inc.root_cause).replace(/_/g, ' ').toLowerCase()} · {inc.observation_count} observation(s) so far</div>
          </Q>

          <Q n="02" label="When">
            <div className="lv-kv" style={{ marginBottom: 10 }}>
              {ctx.first_observation_at
                ? <><dt>First observed</dt><dd>{fmtDateTime(ctx.first_observation_at)}</dd></>
                : <><dt>Latest observation</dt><dd>{fmtDateTime(inc.observation_timestamp)}</dd></>}
              <dt>Detected</dt><dd>{fmtDateTime(inc.detected_at)}</dd>
              <dt>Last updated</dt><dd>{fmtDateTime(inc.last_seen_at)} ({formatAge(inc.last_seen_at)})</dd>
            </div>
            <ol className="lv-timeline">
              {(inc.lifecycle || [])
                .map((s: any) => (!inc.context && s.stage === 'OBSERVATION' ? { ...s, stage: 'LATEST_OBSERVATION' } : s))
                .sort((a: any, b: any) => Date.parse(a.at) - Date.parse(b.at))
                .map((s: any, i: number) => (
                <li key={i}>
                  <span className={`lv-tl-dot ${STAGE_DOT[s.stage] || ''}`} />
                  <span><span className="lv-tl-stage">{s.stage.replace(/_/g, ' ')}</span><span className="lv-tl-at">{fmtDateTime(s.at)}{s.actor ? ` · ${s.actor}` : ''}</span>
                    {s.detail && <div className="lv-tl-text">{s.detail}</div>}</span>
                </li>
              ))}
            </ol>
          </Q>

          <Q n="03" label="Where">
            <div className="lv-spread" style={{ flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontWeight: 700 }}>{inc.station_name || inc.station_id} <span className="lv-mono lv-muted">{inc.station_id}</span></div>
                <div className="lv-muted">{inc.town && inc.region && String(inc.town).includes(inc.region) ? inc.town : [inc.town, inc.region, inc.country].filter(Boolean).join(' · ') || '—'}</div>
              </div>
              <div className="lv-row">
                <button className="lv-btn" onClick={() => onShowOnMap(inc.station_id)}><MapPinned size={14} />Show on map</button>
                <button className="lv-btn" onClick={() => onOpenStation(inc.station_id)}>Open station</button>
              </div>
            </div>
          </Q>

          <Q n="04" label="What changed">
            <div className="lv-stats" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', marginBottom: 10 }}>
              <div className="lv-stat"><span className="lv-stat-lbl">Affected variable</span><span className="lv-stat-val" style={{ fontSize: '1.05rem' }}>{inc.parameter}</span></div>
              <div className="lv-stat"><span className="lv-stat-lbl">Before onset</span><span className="lv-stat-val" style={{ fontSize: '1.05rem' }}>{before ? fmt(before[param], 1, ` ${unit}`) : '—'}</span><span className="lv-stat-sub">{before ? `last reading before, ${fmtDateTime(before.t)}` : 'not in recorded window'}</span></div>
              <div className="lv-stat anomaly"><span className="lv-stat-lbl">At onset</span><span className="lv-stat-val" style={{ fontSize: '1.05rem' }}>{fmt(onset ? onset[param] : atDetection, 1, ` ${unit}`)}</span><span className="lv-stat-sub">first anomalous reading</span></div>
              <div className="lv-stat"><span className="lv-stat-lbl">Neighbour consensus</span><span className="lv-stat-val" style={{ fontSize: '1.05rem' }}>{fmt(exp.spatial_consensus, 1, ` ${unit}`)}</span><span className="lv-stat-sub">{exp.spatial_z != null ? `${fmt(exp.spatial_z, 1)}σ away · latest evidence` : 'latest evidence'}</span></div>
              <div className="lv-stat"><span className="lv-stat-lbl">Now</span><span className="lv-stat-val" style={{ fontSize: '1.05rem' }}>{fmt(nowVal, 1, ` ${unit}`)}</span><span className="lv-stat-sub">{liveNow ? formatAge(liveNow.last_observed_at) : 'no live feed'}</span></div>
            </div>
            {chartParam && series?.points?.length > 1 ? (
              <>
                <MiniChart points={series.points} param={chartParam} markers={Number.isFinite(detectedEpoch) ? [detectedEpoch] : []} />
                <p className="a-note">Last 6 h of {chartParam.label.toLowerCase()} at this station; the dashed line marks the first anomalous observation.</p>
              </>
            ) : <p className="a-note">No recorded series is available for this variable in the last 6 h.</p>}
          </Q>

          <Q n="05" label="Which layers detected it — and the evidence" wide>
            {model ? <IntelligencePipeline model={model} hideConfidenceNote /> : <Empty>Evidence unavailable.</Empty>}
            {!det && inc.context && <p className="a-note" style={{ marginTop: 6 }}>The original detection record has aged out of the time-series store; showing the evidence captured with the investigation.</p>}
          </Q>

          <Q n="06" label="How certain">
            <div className="lv-kv">
              <dt>Fused confidence*</dt><dd>{pct(inc.confidence)}</dd>
              <dt>Diagnosis confidence</dt><dd>{String(inc.root_cause_confidence || '—').toLowerCase()}</dd>
              <dt>Layers with evidence</dt><dd>{(ctx.triggered_layers || det?.triggered_layers || []).join(', ') || 'none recorded'}</dd>
              <dt>Layers that could not assess</dt><dd>{model ? model.phases[1].stages.filter((s) => s.tone === 'unassessed').map((s) => s.name).join(', ') || 'none' : '—'}</dd>
            </div>
            <p className="a-note" style={{ marginTop: 6 }}>* {CONFIDENCE_NOTE}</p>
          </Q>

          <Q n="07" label="Likely root cause">
            <div style={{ fontWeight: 800, fontSize: '0.98rem' }}>{ctx.rca_label || String(inc.root_cause).replace(/_/g, ' ').toLowerCase()}</div>
            <p style={{ margin: '4px 0 8px', fontSize: '0.84rem', color: 'var(--a-ink-2)' }}>{det?.diagnosis?.primary_signal || (inc.evidence || [])[0] || '—'}</p>
            {(det?.diagnosis?.alternatives || []).length > 0 && (
              <div className="lv-muted">Also considered: {det.diagnosis.alternatives.join(' · ')}</div>
            )}
          </Q>

          <Q n="08" label="Weather & neighbour context">
            <div className="lv-grid-2" style={{ gap: 14 }}>
              <div>
                <div className="a-eyebrow" style={{ marginBottom: 6 }}>Neighbours at detection</div>
                {ctx.neighbors?.length ? (
                  <table className="lv-table">
                    <thead><tr><th>Station</th><th>Dist.</th><th>{inc.parameter}</th><th>Status</th></tr></thead>
                    <tbody>
                      {ctx.neighbors.slice(0, 6).map((n: any) => (
                        <tr key={n.station_id} className="clickable" onClick={() => onOpenStation(n.station_id)}>
                          <td>{n.name || n.station_id}</td><td className="a-num">{fmt(n.distance_km, 1, ' km')}</td>
                          <td className="a-num">{fmt(n[param], 1, ` ${unit}`)}</td><td>{n.overall_status || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <p className="lv-muted">No neighbour snapshot was captured.</p>}
                <p className="a-note" style={{ marginTop: 6 }}>{isWeather ? 'Neighbours showed the same change, so this is treated as weather.' : 'Had the neighbours shown the same change, ATHER would have classified it as weather and opened no investigation.'}</p>
              </div>
              <div>
                <div className="a-eyebrow" style={{ marginBottom: 6 }}>Weather model reference <span className="lv-badge lv-badge-nwp" style={{ marginLeft: 6 }}>MODEL DATA</span></div>
                {ref?.available && ref.parameters?.[param] ? (
                  <div className="lv-kv">
                    <dt>Observed</dt><dd>{fmt(ref.parameters[param].observed, 1, ` ${unit}`)}</dd>
                    <dt>Model (Open-Meteo)</dt><dd>{fmt(ref.parameters[param].reference, 1, ` ${unit}`)}</dd>
                    <dt>Observed − model</dt><dd>{fmt(ref.parameters[param].difference, 1, ` ${unit}`)}</dd>
                  </div>
                ) : <p className="lv-muted">{ref?.reason || 'No model reference was captured for this variable.'}</p>}
                {ref?.note && <p className="a-note" style={{ marginTop: 6 }}>{ref.note}</p>}
              </div>
            </div>
          </Q>

          <Q n="09" label="Operational insight">
            <div className="lv-row" style={{ marginBottom: 6 }}>
              <span className="lv-pill lv-status-unknown">{INTERPRETATION_LABEL[ctx.interpretation] || 'Assessment'}</span>
              {ctx.action_label && <b>{ctx.action_label}</b>}
            </div>
            <p style={{ margin: '0 0 12px', fontSize: '0.86rem', lineHeight: 1.5 }}>{inc.recommended_action || '—'}</p>
            {!closed ? (
              <div className="lv-row">
                <button className="lv-btn" disabled={busy || !allowed.includes('ACKNOWLEDGED')} onClick={() => act(() => acknowledgeIncident(inc.incident_id))}><UserCheck size={14} />Acknowledge</button>
                <button className="lv-btn" disabled={busy || !allowed.includes('INVESTIGATING')} onClick={() => act(() => investigateIncident(inc.incident_id))}><InvestigateIcon size={14} />Start investigating</button>
                <button className="lv-btn" disabled={busy || !allowed.includes('ESCALATED')} onClick={() => setModal('escalate')}><Siren size={14} />Escalate</button>
                <button className="lv-btn lv-btn-primary" disabled={busy || !allowed.includes('RESOLVED')} onClick={() => setModal('resolve')}><CheckCircle2 size={14} />Resolve</button>
                <button className="lv-btn lv-btn-danger" disabled={busy || !allowed.includes('DISMISSED')} onClick={() => setModal('dismiss')}><XCircle size={14} />Dismiss</button>
              </div>
            ) : (
              <div className="lv-callout ok">Closed ({inc.status.toLowerCase()}){inc.resolution_notes ? `: ${inc.resolution_notes}` : inc.dismissal_reason ? `: ${inc.dismissal_reason}` : ''}.</div>
            )}
          </Q>
        </div>
      </section>

      {modal === 'escalate' && <EscalationPreviewModal incidentId={inc.incident_id} onClose={() => setModal(null)} onEscalated={load} />}
      {modal === 'resolve' && <ResolveIncidentModal incidentId={inc.incident_id} onClose={() => setModal(null)}
        onResolve={async (notes, type) => { await act(() => resolveIncident(inc.incident_id, notes, type)); }} />}
      {modal === 'dismiss' && <DismissIncidentModal incidentId={inc.incident_id} onClose={() => setModal(null)}
        onDismiss={async (reason) => { await act(() => dismissIncident(inc.incident_id, reason)); }} />}
    </div>
  );
};
