import React, { useEffect, useState } from 'react';
import { Cpu, Database, Radio, Satellite, Timer, Waves } from 'lucide-react';
import { fetchSystemHealth } from '../services/api';
import { formatAge, useLive } from '../services/live';
import { Card, Empty } from '../components/live/LiveBits';
import { useNow } from '../components/live/LivePanels';

const ms = (v?: number | null) => (v === null || v === undefined ? '—' : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${v.toFixed(1)} ms`);

const STATE_CLASS: Record<string, string> = {
  ACTIVE: 'lv-status-nominal', RUNNING: 'lv-status-nominal', OK: 'lv-status-nominal',
  DEGRADED: 'lv-status-suspect', STARTING: 'lv-status-suspect', WARMING_UP: 'lv-status-suspect', IDLE: 'lv-status-suspect',
  DOWN: 'lv-status-anomaly', ERROR: 'lv-status-anomaly',
  NOT_CONFIGURED: 'lv-status-unknown', DISABLED: 'lv-status-unknown',
};

/**
 * ATHER SYSTEM — pipeline observability (spec §18/§19): component health,
 * every data source (including the ones that are intentionally not
 * flowing, with the reason), latency distributions and throughput.
 * Live numbers arrive with the SYSTEM_METRICS heartbeat every 5 s; the
 * database block is fetched on open.
 */
export const SystemWorkspace: React.FC = () => {
  const { system: live, connection, lastEventAt } = useLive();
  const [full, setFull] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const now = useNow();

  useEffect(() => {
    fetchSystemHealth().then(setFull).catch((e) => setError(e.message));
  }, []);

  const sys = live || full;
  if (!sys) {
    return <div className="lv-page"><Empty>{error ? `System health unavailable: ${error}` : 'Loading system health…'}</Empty></div>;
  }
  const comps = sys.components || {};
  const m = sys.metrics || {};
  const db = full?.components?.database || comps.database || {};

  const latencyRows: [string, string, any][] = [
    ['Ingestion', 'received − observed (source + transport delay)', m.latency?.ingestion],
    ['Queue wait', 'dequeued − enqueued (stream lag)', m.latency?.queue_wait],
    ['Processing', '5 layers + fusion + persistence, per observation', m.latency?.processing],
    ['End-to-end', 'event published − observed', m.latency?.end_to_end],
  ];

  return (
    <div className="lv-page">
      <div className="lv-page-head">
        <div>
          <div className="lv-page-title">ATHER System</div>
          <div className="lv-page-sub">
            Continuous pipeline: sources → validation &amp; normalization → stream → 5-layer engine + conformal fusion →
            time-series &amp; incident storage → server-sent events → this dashboard.
          </div>
        </div>
        <span className={`lv-pill ${STATE_CLASS[sys.runtime_state] || 'lv-status-unknown'}`}><span className="lv-dot" />Runtime {sys.runtime_state}</span>
      </div>

      <div className="lv-grid-3">
        <Card title="Components" icon={<Cpu size={14} />}>
          <table className="lv-table">
            <tbody>
              {[
                ['Ingestion', comps.ingestion?.status],
                ['Detector', comps.detector?.status, comps.detector?.engine_version],
                ['Time-series database', comps.database?.status, db.backend],
                ['Observation stream', comps.stream?.status, comps.stream?.backend],
                ['Event stream (SSE)', connection === 'live' ? 'OK' : connection.toUpperCase(), `${comps.events?.subscribers ?? '—'} subscriber(s)`],
              ].map(([k, v, note]) => (
                <tr key={k as string}>
                  <td>{k}</td>
                  <td><span className={`lv-pill lv-pill-sm ${STATE_CLASS[v as string] || 'lv-status-unknown'}`}>{v || '—'}</span></td>
                  <td className="lv-muted">{note}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {comps.detector?.last_error && <div className="lv-callout danger" style={{ marginTop: 8 }}>Last error: {comps.detector.last_error}</div>}
        </Card>

        <Card title="Throughput" icon={<Waves size={14} />}>
          <dl className="lv-kv">
            <dt>Received / min</dt><dd>{m.throughput_per_min?.received ?? '—'}</dd>
            <dt>Processed / min</dt><dd>{m.throughput_per_min?.processed ?? '—'}</dd>
            <dt>Anomalies / min</dt><dd>{m.throughput_per_min?.anomalies ?? '—'}</dd>
            <dt>Processed total</dt><dd>{m.totals?.processed?.toLocaleString() ?? '—'}</dd>
            <dt>Duplicates · late · rejected</dt><dd>{m.totals?.duplicates ?? 0} · {m.totals?.late ?? 0} · {m.totals?.rejected ?? 0}</dd>
            <dt>Incidents opened</dt><dd>{m.totals?.incidents_created ?? 0}</dd>
            <dt>Processing errors</dt><dd style={{ color: m.totals?.errors ? 'var(--lv-anomaly)' : undefined }}>{m.totals?.errors ?? 0}</dd>
            <dt>Last event received</dt><dd>{lastEventAt ? formatAge(lastEventAt, now) : '—'}</dd>
          </dl>
        </Card>

        <Card title="Storage & stream" icon={<Database size={14} />}>
          <dl className="lv-kv">
            <dt>Time-series store</dt><dd>{db.backend || '—'}</dd>
            <dt>Observations stored</dt><dd>{db.observations?.toLocaleString() ?? '—'}</dd>
            <dt>Detections stored</dt><dd>{db.detections?.toLocaleString() ?? '—'}</dd>
            <dt>Database size</dt><dd>{db.size_mb !== undefined ? `${db.size_mb} MB` : '—'}</dd>
            <dt>Stream depth / capacity</dt><dd>{comps.stream ? `${comps.stream.depth} / ${comps.stream.capacity}` : '—'}</dd>
            <dt>Events published</dt><dd>{comps.events?.published_total?.toLocaleString() ?? '—'}</dd>
            <dt>Slow-client drops</dt><dd>{comps.events?.slow_client_drops ?? 0}</dd>
          </dl>
        </Card>
      </div>

      <Card title="Latency" icon={<Timer size={14} />}>
        <div className="lv-table-wrap">
          <table className="lv-table">
            <thead><tr><th>Stage</th><th>Definition</th><th>p50</th><th>p95</th><th>max</th><th>samples</th></tr></thead>
            <tbody>
              {latencyRows.map(([k, def, l]) => (
                <tr key={k}><td><b>{k}</b></td><td className="lv-muted">{def}</td><td>{ms(l?.p50_ms)}</td><td>{ms(l?.p95_ms)}</td><td>{ms(l?.max_ms)}</td><td>{l?.count ?? 0}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Data sources" icon={<Radio size={14} />}>
        <div className="lv-table-wrap">
          <table className="lv-table">
            <thead><tr><th>Source</th><th>Role</th><th>State</th><th>Cadence</th><th>Last success</th><th>Items</th><th>Notes</th></tr></thead>
            <tbody>
              {(sys.sources || []).map((s: any) => (
                <tr key={s.name}>
                  <td><b>{s.label}</b>{s.simulated && <div><span className="lv-badge lv-badge-sim">SIMULATED</span></div>}</td>
                  <td>{s.kind === 'REFERENCE' ? <span className="lv-row"><Satellite size={12} />Reference (NWP)</span> : 'Observations'}</td>
                  <td><span className={`lv-pill lv-pill-sm ${STATE_CLASS[s.state] || 'lv-status-unknown'}`}>{s.state}</span></td>
                  <td>{s.cadence_s >= 60 ? `${Math.round(s.cadence_s / 60)} min` : `${s.cadence_s} s`}</td>
                  <td>{s.last_success_at ? formatAge(s.last_success_at, now) : '—'}</td>
                  <td>{s.items_total?.toLocaleString?.() ?? 0}</td>
                  <td className="lv-muted" style={{ maxWidth: 420 }}>{s.last_error ? <span style={{ color: 'var(--lv-anomaly)' }}>{s.last_error}</span> : s.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="lv-muted" style={{ marginTop: 8 }}>
          Open-Meteo is used only as a model/reference layer for observed-vs-NWP comparison — never as station observations.
          If it becomes unavailable, detection continues and comparisons show “Reference source unavailable”.
        </p>
      </Card>
    </div>
  );
};
