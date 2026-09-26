import React, { useEffect, useMemo, useState } from 'react';
import { FlaskConical, History, ListChecks, Play, Radio, Square, Syringe } from 'lucide-react';
import { cancelFault, fetchFaultTypes, fetchFaults, injectFault, startReplay } from '../services/api';
import { INTERPRETATION_LABEL, useLive, useLiveEvents } from '../services/live';
import { Card, Empty, LayerStrip, StatusPill, fmt, fmtTime, pct } from '../components/live/LiveBits';
import { TestLabModal } from '../components/TestLabModal';

interface Props {
  stations: { id: string; name: string }[];
  onOpenIncident: (id: string) => void;
  onViewStation: (id: string) => void;
  onClose: () => void;
}

const PARAM_LABEL: Record<string, string> = { temperature: 'Temperature', humidity: 'Humidity', pressure: 'Pressure' };

function useSimStations() {
  const { stations, stationsVersion } = useLive();
  return useMemo(() => {
    const out: { id: string; name: string }[] = [];
    stations.forEach((s) => { if (s.simulated) out.push({ id: s.station_id, name: s.name || s.station_id }); });
    return out.sort((a, b) => a.name.localeCompare(b.name));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stationsVersion]);
}

// ── live fault injection ─────────────────────────────────────────────────
const LiveInjection: React.FC<{ types: any; onOpenIncident: (id: string) => void; onViewStation: (id: string) => void }> = ({ types, onOpenIncident, onViewStation }) => {
  const simStations = useSimStations();
  const { stations } = useLive();
  const [stationId, setStationId] = useState('');
  const [faultType, setFaultType] = useState('spike');
  const [parameter, setParameter] = useState('temperature');
  const [severity, setSeverity] = useState('medium');
  const [duration, setDuration] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [faults, setFaults] = useState<any[]>([]);
  const [watch, setWatch] = useState<{ fault: any; injectedAt: number; rows: any[]; incident?: any; firstAlarm?: number; weather?: number } | null>(null);

  useEffect(() => { if (!stationId && simStations.length) setStationId(simStations.find((s) => /Koramangala/i.test(s.name))?.id || simStations[0].id); }, [simStations, stationId]);
  const spec = types?.fault_types?.find((f: any) => f.id === faultType);
  useEffect(() => { if (spec?.parameters?.length && !spec.parameters.includes(parameter)) setParameter(spec.parameters[0]); }, [spec, parameter]);

  const refreshFaults = () => fetchFaults().then((r) => setFaults(r.faults || [])).catch(() => {});
  useEffect(() => { refreshFaults(); }, []);
  useLiveEvents(['FAULT_INJECTED', 'FAULT_CLEARED'], refreshFaults);

  // Follow the target station's detections as they stream in.
  useLiveEvents(['STATION_UPDATED', 'INCIDENT_CREATED', 'WEATHER_EVENT_DETECTED'], (e) => {
    if (!watch) return;
    const d = e.data;
    const affected = watch.fault.fault_type === 'regional_event'
      ? d.injected_fault?.fault_id === watch.fault.fault_id || d.station_id === watch.fault.station_id
      : d.station_id === watch.fault.station_id;
    if (!affected) return;
    setWatch((w) => {
      if (!w) return w;
      if (e.type === 'INCIDENT_CREATED') return { ...w, incident: w.incident || d };
      if (e.type === 'WEATHER_EVENT_DETECTED') return { ...w, weather: w.weather ?? Date.now() };
      if (d.station_id !== w.fault.station_id) return w;
      const alarm = d.overall_status === 'suspect' || d.overall_status === 'anomaly';
      return {
        ...w,
        rows: [{ ...d, at: Date.now() }, ...w.rows].slice(0, 60),
        firstAlarm: w.firstAlarm ?? (alarm ? Date.now() : undefined),
      };
    });
  });

  const inject = async () => {
    setBusy(true); setError(null);
    try {
      const f = await injectFault({
        station_id: stationId, fault_type: faultType, parameter: spec?.parameters?.length ? parameter : null,
        severity, duration_minutes: duration,
      });
      setWatch({ fault: f, injectedAt: Date.now(), rows: [] });
      refreshFaults();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  const secs = (t?: number) => (t && watch ? `${Math.round((t - watch.injectedAt) / 1000)} s after injection` : '—');
  const target = watch ? stations.get(watch.fault.station_id) : null;

  if (!types?.simulation_enabled) {
    return <Empty>Live fault injection needs the simulated AWS feed (ATHER_SIM_ENABLED=1). Replay and the scenario suite still work.</Empty>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card title="Inject a fault into the live network" icon={<Syringe size={14} />}>
        <div className="lv-callout warn" style={{ marginBottom: 12 }}>
          Faults are applied to the <b>simulated</b> AWS feed only, at the next observation (every {types.cadence_s}s per station).
          ATHER is not told a fault exists — it has to find it through the same pipeline as any other observation.
        </div>
        <div className="lv-form">
          <label className="lv-field">Station
            <select value={stationId} onChange={(e) => setStationId(e.target.value)}>
              {simStations.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.id})</option>)}
            </select>
          </label>
          <label className="lv-field">Failure type
            <select value={faultType} onChange={(e) => setFaultType(e.target.value)}>
              {types.fault_types.map((f: any) => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
          </label>
          <label className="lv-field">Parameter
            <select value={parameter} onChange={(e) => setParameter(e.target.value)} disabled={!spec?.parameters?.length}>
              {(spec?.parameters?.length ? spec.parameters : ['—']).map((p: string) => <option key={p} value={p}>{PARAM_LABEL[p] || p}</option>)}
            </select>
          </label>
          <label className="lv-field">Severity
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              {types.severities.map((s: string) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="lv-field">Duration (min)
            <input type="number" min={1} max={240} value={duration} onChange={(e) => setDuration(Number(e.target.value))} />
          </label>
          <button className="lv-btn lv-btn-primary" onClick={inject} disabled={busy || !stationId}><Syringe size={14} />Inject fault</button>
        </div>
        {spec && (
          <p className="lv-muted" style={{ marginTop: 10 }}>
            {spec.description} Expected: {spec.expected_layers.length ? spec.expected_layers.join(' + ') : 'freshness / data-quality checks'} →
            {' '}{INTERPRETATION_LABEL[spec.expected_interpretation] || spec.expected_interpretation}. Expected time to detection: {spec.expected_time_to_detection}.
          </p>
        )}
        {error && <div className="lv-callout danger" style={{ marginTop: 8 }}>{error}</div>}
      </Card>

      {watch && (
        <Card title={`Watching ${watch.fault.station_id} — ${watch.fault.label}`} icon={<Radio size={14} />}
          right={<button className="lv-link" onClick={() => onViewStation(watch.fault.station_id)}>Open station</button>}>
          <div className="lv-stats" style={{ marginBottom: 12 }}>
            <div className="lv-stat"><span className="lv-stat-lbl">Current status</span><span>{target ? <StatusPill status={target.overall_status} watch={target.watch} /> : '—'}</span></div>
            <div className="lv-stat"><span className="lv-stat-lbl">First alarm</span><span className="lv-stat-sub" style={{ color: 'var(--lv-ink)', fontWeight: 700 }}>{secs(watch.firstAlarm)}</span></div>
            <div className="lv-stat"><span className="lv-stat-lbl">Weather classification</span><span className="lv-stat-sub" style={{ color: 'var(--lv-ink)', fontWeight: 700 }}>{secs(watch.weather)}</span></div>
            <div className="lv-stat"><span className="lv-stat-lbl">Incident</span>
              {watch.incident ? <button className="lv-link" onClick={() => onOpenIncident(watch.incident.incident_id)}>{watch.incident.incident_id}</button> : <span className="lv-stat-sub">none yet</span>}
            </div>
          </div>
          {!watch.rows.length ? <Empty>Waiting for the next observation from this station…</Empty> : (
            <div className="lv-table-wrap lv-scroll">
              <table className="lv-table">
                <thead><tr><th>Observed</th><th>Status</th><th>Conf.</th><th>Layers</th><th>Interpretation</th><th>{PARAM_LABEL[watch.fault.parameter] || 'Temp'}</th><th>Summary</th></tr></thead>
                <tbody>
                  {watch.rows.map((r) => (
                    <tr key={r.detection_id}>
                      <td>{fmtTime(r.last_observed_at)}</td>
                      <td><StatusPill status={r.overall_status} watch={r.watch} small /></td>
                      <td>{pct(r.confidence)}</td>
                      <td><LayerStrip triggered={r.triggered_layers} compact /></td>
                      <td>{INTERPRETATION_LABEL[r.interpretation] || r.interpretation}</td>
                      <td>{fmt(r.values?.[watch.fault.parameter || 'temperature'], 1)}</td>
                      <td style={{ maxWidth: 380 }} className="lv-muted">{r.summary}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <Card title="Injected faults" icon={<FlaskConical size={14} />}>
        {!faults.length ? <Empty>No faults injected yet.</Empty> : (
          <div className="lv-table-wrap">
            <table className="lv-table">
              <thead><tr><th>Fault</th><th>Station</th><th>Parameter</th><th>Severity</th><th>Started</th><th>Ends</th><th>State</th><th /></tr></thead>
              <tbody>
                {faults.map((f) => (
                  <tr key={f.fault_id}>
                    <td>{f.label}</td>
                    <td><button className="lv-link" onClick={() => onViewStation(f.station_id)}>{f.station_id}</button>{f.affected_station_ids?.length > 1 ? ` +${f.affected_station_ids.length - 1}` : ''}</td>
                    <td>{f.parameter || '—'}</td><td>{f.severity}</td>
                    <td>{fmtTime(f.started_at_iso)}</td><td>{fmtTime(f.ends_at_iso)}</td>
                    <td>{f.state}</td>
                    <td>{f.state === 'ACTIVE' && <button className="lv-btn lv-btn-danger" onClick={() => cancelFault(f.fault_id).then(refreshFaults)}><Square size={12} />Stop</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
};

// ── replay ───────────────────────────────────────────────────────────────
const ReplayPanel: React.FC<{ types: any; catalogue: { id: string; name: string }[] }> = ({ types, catalogue }) => {
  const simStations = useSimStations();
  const options = simStations.length ? simStations : catalogue;
  const [mode, setMode] = useState<'synthetic' | 'history'>('synthetic');
  const [stationId, setStationId] = useState('');
  const [faultType, setFaultType] = useState('drift');
  const [parameter, setParameter] = useState('temperature');
  const [severity, setSeverity] = useState('medium');
  const [windowMin, setWindowMin] = useState(120);
  const [startMin, setStartMin] = useState(30);
  const [replay, setReplay] = useState<{ id: string; total: number; steps: any[]; markers: any[]; done: boolean; ttd?: number | null } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (!stationId && options.length) setStationId(options.find((s) => /Koramangala/i.test(s.name))?.id || options[0].id); }, [options, stationId]);
  const spec = types?.fault_types?.find((f: any) => f.id === faultType);
  useEffect(() => { if (spec?.parameters?.length && !spec.parameters.includes(parameter)) setParameter(spec.parameters[0]); }, [spec, parameter]);

  useLiveEvents(['REPLAY_STEP', 'REPLAY_COMPLETED'], (e) => {
    setReplay((r) => {
      if (!r || e.data.replay_id !== r.id) return r;
      if (e.type === 'REPLAY_COMPLETED') return { ...r, done: true, ttd: e.data.time_to_detection_min, markers: e.data.markers };
      return { ...r, steps: [...r.steps, e.data.step], markers: [...r.markers, ...(e.data.markers || [])] };
    });
  });

  const run = async () => {
    setError(null);
    try {
      const res = await startReplay({
        mode, station_id: stationId, window_minutes: windowMin, interval_minutes: 5,
        ...(mode === 'synthetic' && faultType !== 'none' ? { fault_type: faultType, parameter: spec?.parameters?.length ? parameter : null, severity, fault_start_minute: startMin } : {}),
        playback_ms: 400,
      });
      setReplay({ id: res.replay_id, total: res.steps, steps: [], markers: [], done: false });
    } catch (e: any) { setError(e.message); }
  };

  const p = spec?.parameters?.length ? parameter : 'temperature';
  const vals = replay?.steps.filter((s) => s.values).map((s) => s.values[p]) || [];
  const lo = Math.min(...vals), hi = Math.max(...vals);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card title="Replay observations through a fresh engine" icon={<History size={14} />}>
        <div className="lv-callout info" style={{ marginBottom: 12 }}>
          Replay re-runs a window of observations through a <b>new, isolated</b> instance of the same pipeline and plays the verdicts back step by step,
          so you can see exactly when each layer triggers. Nothing is persisted; incidents are virtual.
        </div>
        <div className="lv-form">
          <label className="lv-field">Source
            <select value={mode} onChange={(e) => setMode(e.target.value as any)}>
              <option value="synthetic">Synthetic (virtual clock + injected fault)</option>
              <option value="history">Recorded history of this station</option>
            </select>
          </label>
          <label className="lv-field">Station
            <select value={stationId} onChange={(e) => setStationId(e.target.value)}>
              {options.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.id})</option>)}
            </select>
          </label>
          {mode === 'synthetic' && (
            <>
              <label className="lv-field">Failure
                <select value={faultType} onChange={(e) => setFaultType(e.target.value)}>
                  <option value="none">None (healthy baseline)</option>
                  {types?.fault_types?.filter((f: any) => f.id !== 'dropout').map((f: any) => <option key={f.id} value={f.id}>{f.label}</option>)}
                </select>
              </label>
              <label className="lv-field">Parameter
                <select value={parameter} onChange={(e) => setParameter(e.target.value)} disabled={!spec?.parameters?.length}>
                  {(spec?.parameters?.length ? spec.parameters : ['—']).map((x: string) => <option key={x} value={x}>{PARAM_LABEL[x] || x}</option>)}
                </select>
              </label>
              <label className="lv-field">Severity
                <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
                  {(types?.severities || ['low', 'medium', 'high']).map((s: string) => <option key={s}>{s}</option>)}
                </select>
              </label>
              <label className="lv-field">Fault starts at (min)
                <input type="number" min={0} max={windowMin - 5} value={startMin} onChange={(e) => setStartMin(Number(e.target.value))} />
              </label>
            </>
          )}
          <label className="lv-field">Window
            <select value={windowMin} onChange={(e) => setWindowMin(Number(e.target.value))}>
              <option value={60}>1 hour</option><option value={120}>2 hours</option><option value={240}>4 hours</option><option value={480}>8 hours</option>
            </select>
          </label>
          <button className="lv-btn lv-btn-primary" onClick={run} disabled={!stationId || (replay !== null && !replay.done)}><Play size={14} />Replay</button>
        </div>
        {error && <div className="lv-callout danger" style={{ marginTop: 8 }}>{error}</div>}
      </Card>

      {replay && (
        <div className="lv-grid-2">
          <Card title={`Timeline ${replay.steps.length}/${replay.total}${replay.done ? ' — complete' : ''}`} icon={<Play size={14} />}>
            {vals.length > 1 && (
              <svg viewBox="0 0 400 80" style={{ width: '100%', height: 80 }} preserveAspectRatio="none" aria-label="Replayed parameter">
                <path fill="none" stroke="#2563eb" strokeWidth={2} vectorEffect="non-scaling-stroke"
                  d={vals.map((v, i) => `${i ? 'L' : 'M'}${(i / Math.max(1, replay.total - 1)) * 400},${76 - ((v - lo) / Math.max(0.1, hi - lo)) * 70}`).join('')} />
              </svg>
            )}
            <div className="lv-strip" style={{ margin: '6px 0 10px' }}>
              {Array.from({ length: replay.total }).map((_, i) => {
                const s = replay.steps[i];
                const cls = !s ? '' : s.missing ? 'degraded' : s.interpretation === 'likely_weather_event' ? 'weather' : s.overall_status;
                return <span key={i} className={`${cls} ${s?.fault_active ? 'fault' : ''}`} title={s ? `${fmtTime(s.t)} ${s.overall_status || 'no data'}` : ''} />;
              })}
            </div>
            <div className="lv-legend" style={{ marginBottom: 8 }}>
              <span><i style={{ background: '#a7f3d0' }} />Nominal</span><span><i style={{ background: '#fcd34d' }} />Suspect</span>
              <span><i style={{ background: '#f87171' }} />Anomaly</span><span><i style={{ background: '#7dd3fc' }} />Weather</span>
              <span><i style={{ background: '#fff', boxShadow: 'inset 0 -3px 0 #7c2d12' }} />Fault active</span>
            </div>
            <div className="lv-table-wrap lv-scroll">
              <table className="lv-table">
                <thead><tr><th>Time</th><th>{PARAM_LABEL[p]}</th><th>Status</th><th>Layers</th><th>Conf.</th></tr></thead>
                <tbody>
                  {[...replay.steps].reverse().map((s, i) => (
                    <tr key={i}>
                      <td>{fmtTime(s.t)}{s.fault_active ? ' ⚑' : ''}</td>
                      <td>{s.values ? fmt(s.values[p], 2) : 'no data'}</td>
                      <td>{s.overall_status ? (s.interpretation === 'likely_weather_event' ? <span className="lv-pill lv-pill-sm lv-status-weather">weather</span> : <StatusPill status={s.overall_status} small />) : '—'}</td>
                      <td><LayerStrip triggered={s.triggered_layers || []} compact /></td>
                      <td>{pct(s.confidence)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="What happened, and when" icon={<ListChecks size={14} />}>
            {!replay.markers.length ? <Empty>Markers appear as the replay reaches them.</Empty> : (
              <ol className="lv-timeline">
                {replay.markers.map((m, i) => (
                  <li key={i}>
                    <span className={`lv-tl-dot ${m.key === 'anomaly' || m.key === 'incident' ? 'hit' : m.key === 'suspect' ? 'warn' : m.key === 'weather' ? 'weather' : m.key.startsWith('layer') ? 'warn' : ''}`} />
                    <span><span className="lv-tl-stage">{fmtTime(m.at)}</span><div className="lv-tl-text">{m.text}</div></span>
                  </li>
                ))}
              </ol>
            )}
            {replay.done && (
              <div className="lv-callout ok" style={{ marginTop: 8 }}>
                {replay.ttd != null ? <>Time to first alarm after fault onset: <b>{replay.ttd.toFixed(0)} min</b>.</> : 'No fault onset or no alarm in this window.'}
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
};

// ── workspace ────────────────────────────────────────────────────────────
export const TestLabWorkspace: React.FC<Props> = ({ stations, onOpenIncident, onViewStation, onClose }) => {
  const [tab, setTab] = useState<'live' | 'replay' | 'suite'>('live');
  const [types, setTypes] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { fetchFaultTypes().then(setTypes).catch((e) => setError(e.message)); }, []);

  return (
    <div className="lv-page">
      <div className="lv-page-head">
        <div>
          <div className="lv-page-title">ATHER Test Lab</div>
          <div className="lv-page-sub">Inject realistic sensor failures into the running network, replay a window step by step, or run the curated scenario suite — and watch ATHER detect, explain and escalate them.</div>
        </div>
        <div className="lv-tabs">
          <button className={`lv-tab ${tab === 'live' ? 'active' : ''}`} onClick={() => setTab('live')}><Syringe size={13} />Live injection</button>
          <button className={`lv-tab ${tab === 'replay' ? 'active' : ''}`} onClick={() => setTab('replay')}><History size={13} />Replay</button>
          <button className={`lv-tab ${tab === 'suite' ? 'active' : ''}`} onClick={() => setTab('suite')}><ListChecks size={13} />Scenario suite</button>
        </div>
      </div>
      {error && tab !== 'suite' && <div className="lv-callout danger">Real-time pipeline unavailable: {error}</div>}
      {tab === 'live' && types && <LiveInjection types={types} onOpenIncident={onOpenIncident} onViewStation={onViewStation} />}
      {tab === 'replay' && types && <ReplayPanel types={types} catalogue={stations} />}
      {tab === 'suite' && <TestLabModal variant="page" isOpen onClose={onClose} stations={stations} />}
    </div>
  );
};
