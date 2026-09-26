import React, { useEffect, useState } from 'react';
import { Activity, Clock, Cpu, Radio, ShieldAlert, Zap } from 'lucide-react';
import { LiveEvent, formatAge, useLive, INTERPRETATION_LABEL } from '../../services/live';
import { Card, Empty, LayerStrip, SourceBadge, fmtTime, pct } from './LiveBits';

/** Re-render every second so relative ages ("12s ago") stay honest. */
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

// ── event feed ───────────────────────────────────────────────────────────
function describe(e: LiveEvent): { cls: string; kind: string; title: string; text: string; stationId?: string; incidentId?: string } {
  const d = e.data || {};
  switch (e.type) {
    case 'ANOMALY_DETECTED':
      return {
        cls: d.overall_status === 'anomaly' ? 'anomaly' : 'suspect',
        kind: `${d.escalation ? 'Escalated to ' : ''}${d.overall_status === 'anomaly' ? 'Anomaly' : 'Suspect'} · ${pct(d.confidence)}`,
        title: `${d.station_id} — ${d.rca_label || d.root_cause}`,
        text: d.summary, stationId: d.station_id,
      };
    case 'WEATHER_EVENT_DETECTED':
      return { cls: 'weather', kind: 'Weather event · no incident', title: `${d.station_id} — neighbours corroborate`, text: d.summary, stationId: d.station_id };
    case 'STATION_RECOVERED':
      return { cls: 'recovered', kind: 'Recovered', title: `${d.station_id} back to nominal`, text: d.summary, stationId: d.station_id };
    case 'STATION_STALE':
      return { cls: 'system', kind: 'Stale telemetry', title: `${d.station_id} silent ${d.silent_s}s`, text: d.summary, stationId: d.station_id };
    case 'INCIDENT_CREATED':
      return { cls: 'incident', kind: `Incident opened · ${d.severity}`, title: `${d.incident_id} — ${d.station_name || d.station_id}`, text: `${d.parameter}: ${d.rca_label || d.root_cause} (${pct(d.confidence)} confidence)`, stationId: d.station_id, incidentId: d.incident_id };
    case 'INCIDENT_UPDATED':
      return { cls: 'incident', kind: `Incident ${String(d.status || '').toLowerCase()}`, title: `${d.incident_id} — ${d.station_name || d.station_id}`, text: `${d.severity} · ${d.observation_count} observation(s)`, stationId: d.station_id, incidentId: d.incident_id };
    case 'FAULT_INJECTED':
      return { cls: 'system', kind: 'Test Lab · fault injected', title: `${d.label} → ${d.station_name || d.station_id}`, text: `${d.parameter || 'station'} · ${d.severity} · ${Math.round(d.duration_s / 60)} min. Expect ${d.expected_layers?.join(', ') || 'freshness monitor'}.`, stationId: d.station_id };
    case 'FAULT_CLEARED':
      return { cls: 'recovered', kind: `Test Lab · fault ${String(d.state || '').toLowerCase()}`, title: `${d.label} on ${d.station_id}`, text: 'Injected fault no longer applied.', stationId: d.station_id };
    case 'DATA_SOURCE_STATUS_CHANGED':
      return { cls: 'system', kind: 'Data source', title: `${d.label}: ${d.state}`, text: d.reason || d.note || '' };
    default:
      return { cls: 'system', kind: e.type, title: '', text: '' };
  }
}

export const LiveEventFeed: React.FC<{
  onSelectStation?: (id: string) => void;
  onOpenIncident?: (id: string) => void;
  limit?: number;
  stationFilter?: string;
}> = ({ onSelectStation, onOpenIncident, limit = 40, stationFilter }) => {
  const { feed } = useLive();
  const now = useNow(5000);
  const items = feed.filter((e) => !stationFilter || e.data?.station_id === stationFilter).slice(0, limit);
  if (!items.length) {
    return <Empty>No events yet. New anomalies, incidents and weather events appear here the moment the backend detects them.</Empty>;
  }
  return (
    <div className="lv-feed">
      {items.map((e) => {
        const d = describe(e);
        return (
          <button
            key={`${e.id}-${e.type}`}
            className={`lv-feed-item ${d.cls}`}
            onClick={() => (d.incidentId && onOpenIncident ? onOpenIncident(d.incidentId) : d.stationId && onSelectStation?.(d.stationId))}
          >
            <span className="lv-feed-bar" />
            <span>
              <span className="lv-feed-top">
                <span className="lv-feed-kind">{d.kind}</span>
                <span className="lv-feed-time" title={new Date(e.ts * 1000).toISOString()}>{formatAge(e.ts, now)}</span>
              </span>
              <div className="lv-feed-title">{d.title}</div>
              {d.text && <div className="lv-feed-text">{d.text}</div>}
              {e.data?.triggered_layers && (
                <div style={{ marginTop: 4 }} className="lv-row">
                  <LayerStrip triggered={e.data.triggered_layers} compact />
                  {e.data.simulated && <SourceBadge simulated />}
                </div>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
};

// ── network status ───────────────────────────────────────────────────────
export const NetworkStatusCard: React.FC<{ statusFilter?: string | null; onFilter?: (s: string | null) => void }> = ({ statusFilter, onFilter }) => {
  const { counts, connection, pipelineAvailable } = useLive();
  const c = counts || {};
  const tiles: { key: string; label: string; sub?: string }[] = [
    { key: 'nominal', label: 'Healthy' },
    { key: 'suspect', label: 'Suspect' },
    { key: 'degraded', label: 'Degraded' },
    { key: 'anomaly', label: 'Anomalous' },
  ];
  return (
    <Card
      title="Network status"
      icon={<Radio size={14} />}
      right={<span className="lv-row lv-muted"><span className={`lv-live-dot ${connection === 'live' ? '' : connection === 'offline' ? 'off' : 'wait'}`} />{connection === 'live' ? 'Live' : connection}</span>}
    >
      {!pipelineAvailable ? (
        <Empty>Real-time pipeline unavailable — showing catalogue only.</Empty>
      ) : (
        <>
          <div className="lv-spread" style={{ marginBottom: 8 }}>
            <span><span className="lv-stat-val" style={{ fontSize: '1.5rem', fontWeight: 800 }}>{c.live_stations ?? '—'}</span> <span className="lv-muted">stations processed live</span></span>
            <span className="lv-muted">{c.catalogue_total ? `${c.catalogue_total.toLocaleString()} in catalogue` : ''}</span>
          </div>
          <div className="lv-stats">
            {tiles.map((t) => (
              <button
                key={t.key}
                className={`lv-stat ${t.key} ${statusFilter === t.key ? 'active' : ''}`}
                onClick={() => onFilter?.(statusFilter === t.key ? null : t.key)}
                title={`Filter map to ${t.label.toLowerCase()} stations`}
              >
                <span className="lv-stat-val">{c[t.key] ?? 0}</span>
                <span className="lv-stat-lbl">{t.label}</span>
              </button>
            ))}
          </div>
          <div className="lv-row lv-muted" style={{ marginTop: 8 }}>
            {!!c.weather_events && <span className="lv-pill lv-pill-sm lv-status-weather">{c.weather_events} weather event</span>}
            {!!c.stale && <span className="lv-pill lv-pill-sm lv-status-degraded">{c.stale} stale</span>}
            {!!c.watch && <span className="lv-pill lv-pill-sm lv-status-unknown">{c.watch} on watch</span>}
            {!!c.simulated && <SourceBadge simulated />}
            {!!c.simulated && <span>{c.simulated} simulated · {c.measured || 0} measured</span>}
          </div>
        </>
      )}
    </Card>
  );
};

// ── data freshness & system health (compact) ─────────────────────────────
const ms = (v?: number | null) => (v === null || v === undefined ? '—' : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`);

export const FreshnessCard: React.FC = () => {
  const { system } = useLive();
  const now = useNow();
  const m = system?.metrics;
  const sim = system?.sources?.find((s: any) => s.kind === 'OBSERVATION' && s.state === 'ACTIVE');
  return (
    <Card title="Data freshness" icon={<Clock size={14} />}>
      <dl className="lv-kv">
        <dt>Last observation processed</dt><dd>{m?.last_processed_at ? formatAge(m.last_processed_at, now) : '—'}</dd>
        <dt>Active observation source</dt><dd>{sim ? <span className="lv-row">{sim.label}{sim.simulated && <SourceBadge simulated />}</span> : 'none'}</dd>
        <dt>Source cadence</dt><dd>{sim ? `every ${Math.round(sim.cadence_s)} s per station` : '—'}</dd>
        <dt>Ingestion latency p50</dt><dd>{ms(m?.latency?.ingestion?.p50_ms)}</dd>
        <dt>End-to-end latency p50 / p95</dt><dd>{ms(m?.latency?.end_to_end?.p50_ms)} / {ms(m?.latency?.end_to_end?.p95_ms)}</dd>
        <dt>Stale stations</dt><dd>{system?.counts?.stale ?? 0}</dd>
      </dl>
    </Card>
  );
};

export const SystemHealthCard: React.FC<{ onOpen?: () => void }> = ({ onOpen }) => {
  const { system, connection } = useLive();
  const comps = system?.components || {};
  const rows: [string, string][] = [
    ['Ingestion', comps.ingestion?.status],
    ['Detector', comps.detector?.status],
    ['Database', comps.database?.status],
    ['Stream', comps.stream ? `${comps.stream.status} · depth ${comps.stream.depth}` : undefined],
    ['Live events', connection === 'live' ? 'CONNECTED' : connection.toUpperCase()],
  ] as [string, string][];
  const ref = system?.sources?.find((s: any) => s.kind === 'REFERENCE');
  const tp = system?.metrics?.throughput_per_min;
  return (
    <Card title="System health" icon={<Cpu size={14} />} right={onOpen && <button className="lv-link" onClick={onOpen}>Details</button>}>
      <dl className="lv-kv">
        {rows.map(([k, v]) => (
          <React.Fragment key={k}>
            <dt>{k}</dt>
            <dd style={{ color: /OK|RUNNING|CONNECTED|ACTIVE/.test(v || '') ? 'var(--lv-nominal)' : /IDLE|WARMING|connecting|reconnecting/i.test(v || '') ? 'var(--lv-suspect)' : 'var(--lv-anomaly)' }}>{v || '—'}</dd>
          </React.Fragment>
        ))}
        <dt>NWP reference</dt>
        <dd style={{ color: ref?.state === 'ACTIVE' ? 'var(--lv-nominal)' : 'var(--lv-suspect)' }}>
          {ref ? (ref.state === 'ACTIVE' ? 'Available' : ref.state === 'NOT_CONFIGURED' ? 'Disabled' : 'Reference source unavailable') : '—'}
        </dd>
        <dt>Throughput</dt><dd>{tp ? `${tp.processed} obs/min · ${ms(system?.metrics?.latency?.processing?.p50_ms)} per obs` : '—'}</dd>
      </dl>
    </Card>
  );
};

export const IncidentsSummaryCard: React.FC<{ onOpen?: () => void }> = ({ onOpen }) => {
  const { incidentCounts } = useLive();
  const c = incidentCounts || {};
  return (
    <Card title="Active incidents" icon={<ShieldAlert size={14} />} right={onOpen && <button className="lv-link" onClick={onOpen}>Open</button>}>
      <div className="lv-stats">
        <div className="lv-stat anomaly"><span className="lv-stat-val">{c.critical ?? 0}</span><span className="lv-stat-lbl">Critical</span></div>
        <div className="lv-stat suspect"><span className="lv-stat-val">{c.warning ?? 0}</span><span className="lv-stat-lbl">Warning</span></div>
        <div className="lv-stat"><span className="lv-stat-val">{c.new ?? 0}</span><span className="lv-stat-lbl">New</span></div>
        <div className="lv-stat"><span className="lv-stat-val">{(c.investigating ?? 0) + (c.escalated ?? 0)}</span><span className="lv-stat-lbl">In progress</span></div>
      </div>
      <p className="lv-muted" style={{ marginTop: 8 }}>Incidents open automatically from the pipeline; weather-classified events never open one.</p>
    </Card>
  );
};

export const ThroughputCard: React.FC = () => {
  const { system } = useLive();
  const t = system?.metrics?.totals || {};
  const l = system?.metrics?.latency || {};
  return (
    <Card title="Detection pipeline" icon={<Zap size={14} />}>
      <dl className="lv-kv">
        <dt>Observations processed</dt><dd>{(t.processed ?? 0).toLocaleString()}</dd>
        <dt>Anomalies detected</dt><dd>{t.anomalies ?? 0}</dd>
        <dt>Duplicates / late / rejected</dt><dd>{t.duplicates ?? 0} / {t.late ?? 0} / {t.rejected ?? 0}</dd>
        <dt>Engine time p50 / p95</dt><dd>{ms(l.processing?.p50_ms)} / {ms(l.processing?.p95_ms)}</dd>
        <dt>Queue wait p95</dt><dd>{ms(l.queue_wait?.p95_ms)}</dd>
        <dt>Errors</dt><dd style={{ color: t.errors ? 'var(--lv-anomaly)' : undefined }}>{t.errors ?? 0}</dd>
      </dl>
    </Card>
  );
};

export const InterpretationText: React.FC<{ value?: string }> = ({ value }) => (
  <span className={`lv-pill lv-pill-sm ${value === 'likely_weather_event' ? 'lv-status-weather' : value === 'likely_sensor_fault' ? 'lv-status-anomaly' : value === 'communication_issue' ? 'lv-status-degraded' : 'lv-status-unknown'}`}>
    <Activity size={10} /> {INTERPRETATION_LABEL[value || ''] || value || '—'}
  </span>
);

export { fmtTime };
