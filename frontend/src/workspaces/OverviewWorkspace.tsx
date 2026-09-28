import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Layers, MapPinned, Radio, ShieldAlert, Thermometer } from 'lucide-react';
import { LiveStation, formatAge, useLive, useLiveEvents, INTERPRETATION_LABEL } from '../services/live';
import { fetchIncidents } from '../services/api';
import { human, isClosed, opsStatus } from '../components/ops/incidentModel';
import { Card, Empty, SourceBadge, StatusPill, fmt } from '../components/live/LiveBits';
import { LiveEventFeed, useNow } from '../components/live/LivePanels';
import { Workspace } from '../types/workspace';

interface Props {
  stationsGeoJSON: GeoJSON.FeatureCollection | null;
  onNavigate: (w: Workspace) => void;
  onOpenStation: (id: string) => void;
  onOpenIncident: (id: string) => void;
}

const RANK: Record<string, number> = { anomaly: 0, suspect: 1, degraded: 2, nominal: 3 };
const LAYERS: [string, string][] = [['L1', 'Physics'], ['L2', 'Temporal'], ['L3', 'Multivariate'], ['L4', 'Spatial'], ['L5', 'Sensor health']];

/**
 * OVERVIEW — "What is happening across the AWS network right now?"
 * Everything here is the live pipeline's current state (SSE store) or the
 * station catalogue; nothing is estimated.
 */
export const OverviewWorkspace: React.FC<Props> = ({ stationsGeoJSON, onNavigate, onOpenStation, onOpenIncident }) => {
  const { stations, stationsVersion, counts, incidentCounts, system, connection, pipelineAvailable } = useLive();
  const now = useNow(5000);
  const [incidents, setIncidents] = useState<any[] | null>(null);
  const lastInc = useRef(0);
  const loadIncidents = () => fetchIncidents(null).then((r) => setIncidents((r.incidents || []).filter((i: any) => !isClosed(i)))).catch(() => setIncidents(null));
  useEffect(() => { loadIncidents(); }, []);
  useLiveEvents(['INCIDENT_CREATED', 'INCIDENT_UPDATED'], () => {
    if (Date.now() - lastInc.current > 3000) { lastInc.current = Date.now(); loadIncidents(); }
  });

  const regionOf = useMemo(() => {
    const m = new Map<string, string>();
    stationsGeoJSON?.features.forEach((f) => m.set(String(f.properties?.id), String(f.properties?.region || '—')));
    return m;
  }, [stationsGeoJSON]);

  const { attention, layerHits, env, regions } = useMemo(() => {
    const list: LiveStation[] = [];
    stations.forEach((s) => list.push(s));
    const attention = list.filter((s) => s.overall_status !== 'nominal').sort((a, b) => RANK[a.overall_status] - RANK[b.overall_status]);
    const layerHits: Record<string, number> = {};
    list.forEach((s) => (s.triggered_layers || []).forEach((l) => { layerHits[l] = (layerHits[l] || 0) + 1; }));
    let t = 0, tn = 0, h = 0, hn = 0, p = 0, pn = 0;
    list.forEach((s) => {
      const v = s.values || {};
      if (typeof v.temperature === 'number') { t += v.temperature; tn++; }
      if (typeof v.humidity === 'number' && v.humidity <= 100) { h += v.humidity; hn++; }
      if (typeof v.pressure === 'number') { p += v.pressure; pn++; }
    });
    const regions = new Map<string, { total: number; attention: number; critical: number }>();
    list.forEach((s) => {
      const r = regionOf.get(s.station_id) || '—';
      const e = regions.get(r) || { total: 0, attention: 0, critical: 0 };
      e.total += 1;
      if (s.overall_status !== 'nominal') e.attention += 1;
      if (s.overall_status === 'anomaly') e.critical += 1;
      regions.set(r, e);
    });
    return {
      list, attention, layerHits,
      env: { t: tn ? t / tn : null, h: hn ? h / hn : null, p: pn ? p / pn : null, n: tn },
      regions: [...regions.entries()].sort((a, b) => b[1].attention - a[1].attention || b[1].total - a[1].total),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stationsVersion, regionOf]);

  const c = counts || {};
  const obsSource = system?.sources?.find((s: any) => s.kind === 'OBSERVATION' && s.state === 'ACTIVE');
  const lastObs = system?.metrics?.last_processed_at;
  const openInv = incidentCounts?.active ?? 0;
  const warmup = system?.warmup;
  const critical = c.anomaly || 0;
  const warning = c.suspect || 0;
  const degraded = c.degraded || 0;

  const headline = !pipelineAvailable
    ? 'Live pipeline unavailable'
    : !c.live_stations
      ? 'Waiting for the first observations'
      : critical === 0 && warning === 0 && degraded === 0
        ? `All ${c.live_stations} monitored stations are nominal`
        : `${critical ? `${critical} anomalous` : ''}${critical && (warning || degraded) ? ' · ' : ''}${warning ? `${warning} warning` : ''}${warning && degraded ? ' · ' : ''}${degraded ? `${degraded} degraded` : ''} across ${c.live_stations} monitored stations`;

  return (
    <div className="lv-page">
      <div className="lv-page-head">
        <div>
          <div className="a-eyebrow">Network overview</div>
          <h1 className="a-h1">{headline}</h1>
          <p className="a-lead">
            SkyGuard AI checks every observation through five independent detection layers, fuses the evidence, and explains what it found.
            {obsSource && <> Source: {obsSource.label}, one observation per station every {Math.round(obsSource.cadence_s)} s{lastObs ? `; last processed ${formatAge(lastObs, now)}` : ''}.</>}
            {warmup?.state === 'RUNNING' && <> Start-up: {warmup.stations_ready} of {warmup.stations_total} simulated stations live with current telemetry; the {warmup.history_stations ?? ''} stations around the baseline station are being warmed with {warmup.cycles} cycles of simulated history. Other stations build history from live cycles.</>}
          </p>
        </div>
        <div className="lv-row">
          {obsSource?.simulated && <SourceBadge simulated />}
          {warmup?.demo_station_id && (
            <button className="lv-btn" title="Simulated station with the densest neighbourhood — the baseline for a normal-operation walkthrough"
              onClick={() => onOpenStation(warmup.demo_station_id)}>Baseline station</button>
          )}
          <button className="lv-btn" onClick={() => onNavigate('incidents')}><ShieldAlert size={14} />Incidents</button>
          <button className="lv-btn lv-btn-primary" onClick={() => onNavigate('map')}><MapPinned size={14} />Open live map</button>
        </div>
      </div>

      <div className="lv-stats" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
        <div className="lv-stat"><span className="lv-stat-lbl">Monitored live</span><span className="lv-stat-val">{c.live_stations ?? '—'}</span>
          <span className="lv-stat-sub">AWS stations in the network</span></div>
        <div className="lv-stat nominal"><span className="lv-stat-lbl">Nominal</span><span className="lv-stat-val">{c.nominal ?? '—'}</span><span className="lv-stat-sub">fresh, no anomalous evidence</span></div>
        <div className="lv-stat suspect"><span className="lv-stat-lbl">Warning</span><span className="lv-stat-val">{warning}</span><span className="lv-stat-sub">suspect evidence</span></div>
        <div className="lv-stat degraded"><span className="lv-stat-lbl">Degraded</span><span className="lv-stat-val">{degraded}</span><span className="lv-stat-sub">{c.stale ? `${c.stale} stale` : 'data quality'}</span></div>
        <div className="lv-stat anomaly"><span className="lv-stat-lbl">Anomalous</span><span className="lv-stat-val">{critical}</span><span className="lv-stat-sub">anomaly confirmed</span></div>
        <button className="lv-stat" onClick={() => onNavigate('incidents')}><span className="lv-stat-lbl">Active incidents</span><span className="lv-stat-val">{openInv}</span>
          <span className="lv-stat-sub">{incidentCounts ? `${incidentCounts.critical ?? 0} critical · ${incidentCounts.new ?? 0} new` : ' '}</span></button>
      </div>

      <div className="lv-grid-2" style={{ gridTemplateColumns: 'minmax(0, 1.25fr) minmax(0, 1fr)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card title="Active incidents" icon={<ShieldAlert size={14} />}
            right={<button className="lv-link" onClick={() => onNavigate('incidents')}>Open incident queue</button>}>
            {incidents === null ? <Empty>Loading…</Empty> : !incidents.length ? <Empty>No open incidents.</Empty> : (
              <table className="lv-table">
                <thead><tr><th>Incident</th><th>Station</th><th>Finding</th><th>Severity</th><th>Status</th></tr></thead>
                <tbody>
                  {incidents.slice(0, 6).map((i) => (
                    <tr key={i.incident_id} className="clickable" onClick={() => onOpenIncident(i.incident_id)}>
                      <td className="lv-mono" style={{ fontSize: '0.7rem' }}>{i.incident_id}</td>
                      <td>{i.station_name || i.station_id}</td>
                      <td>{i.parameter} · {i.context?.rca_label || human(i.root_cause)}</td>
                      <td><span className={`lv-pill lv-pill-sm ${i.severity === 'CRITICAL' ? 'lv-status-anomaly' : 'lv-status-suspect'}`}>{i.severity}</span></td>
                      <td className="lv-muted">{opsStatus(i).label}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card title="Stations needing attention" icon={<ShieldAlert size={14} />}
            right={<button className="lv-link" onClick={() => onNavigate('map')}>View on map</button>}>
            {!attention.length ? (
              <Empty>{connection === 'live' ? 'No station currently needs attention.' : 'Waiting for live data…'}</Empty>
            ) : (
              <div className="lv-table-wrap lv-scroll">
                <table className="lv-table">
                  <thead><tr><th>Station</th><th>Status</th><th>Finding</th><th>Layers</th><th>Observed</th></tr></thead>
                  <tbody>
                    {attention.slice(0, 12).map((s) => (
                      <tr key={s.station_id} className="clickable" onClick={() => onOpenStation(s.station_id)}>
                        <td><b>{s.name || s.station_id}</b><div className="lv-mono" style={{ fontSize: '0.66rem', color: 'var(--a-ink-3)' }}>{s.station_id} · {regionOf.get(s.station_id) || '—'}</div></td>
                        <td><StatusPill status={s.overall_status} small /></td>
                        <td>{s.freshness === 'STALE' ? 'No recent telemetry' : s.rca_label || INTERPRETATION_LABEL[s.interpretation || ''] || '—'}</td>
                        <td className="lv-mono" style={{ fontSize: '0.7rem' }}>{s.triggered_layers?.length ? s.triggered_layers.join(' ') : '—'}</td>
                        <td className="lv-muted">{formatAge(s.last_observed_at, now)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {attention.length > 12 && <p className="a-note" style={{ marginTop: 6 }}>+{attention.length - 12} more on the live map.</p>}
              </div>
            )}
          </Card>

          <Card title="Detection layers — current activity" icon={<Layers size={14} />}>
            <table className="lv-table">
              <thead><tr><th>Layer</th><th>What it looks for</th><th style={{ textAlign: 'right' }}>Stations flagged now</th></tr></thead>
              <tbody>
                {LAYERS.map(([code, name]) => (
                  <tr key={code}>
                    <td><span className="lv-mono" style={{ color: 'var(--a-ink-3)', marginRight: 6 }}>{code}</span><b>{name}</b></td>
                    <td className="lv-muted">{{
                      L1: 'Physically impossible values', L2: 'Abnormal change over time, stuck values',
                      L3: 'Implausible combinations of variables', L4: 'Disagreement with neighbouring stations', L5: 'Slow sensor drift',
                    }[code]}</td>
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>{layerHits[code] || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="a-note" style={{ marginTop: 8 }}>Count of live stations whose latest observation has evidence from each layer. Layers are independent; fusion combines them before any decision.</p>
          </Card>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card title="Recent anomaly events" icon={<Radio size={14} />}
            right={<button className="lv-link" onClick={() => onNavigate('incidents')}>All incidents</button>}>
            <div className="lv-scroll" style={{ maxHeight: 330 }}>
              <LiveEventFeed limit={12} onSelectStation={onOpenStation} onOpenIncident={onOpenIncident} />
            </div>
          </Card>

          <Card title="Network environment" icon={<Thermometer size={14} />} right={obsSource?.simulated ? <SourceBadge simulated /> : undefined}>
            {env.n === 0 ? <Empty>No live observations yet.</Empty> : (
              <>
                <div className="lv-stats">
                  <div className="lv-stat"><span className="lv-stat-lbl">Mean temperature</span><span className="lv-stat-val" style={{ fontSize: '1.2rem' }}>{fmt(env.t, 1, ' °C')}</span></div>
                  <div className="lv-stat"><span className="lv-stat-lbl">Mean humidity</span><span className="lv-stat-val" style={{ fontSize: '1.2rem' }}>{fmt(env.h, 0, ' %')}</span></div>
                  <div className="lv-stat"><span className="lv-stat-lbl">Mean pressure</span><span className="lv-stat-val" style={{ fontSize: '1.2rem' }}>{fmt(env.p, 0, ' hPa')}</span></div>
                  <div className="lv-stat weather"><span className="lv-stat-lbl">Weather events</span><span className="lv-stat-val" style={{ fontSize: '1.2rem' }}>{c.weather_events || 0}</span></div>
                </div>
                <p className="a-note" style={{ marginTop: 8 }}>Means of the latest observation from {env.n} stations. Weather events are changes corroborated by neighbours — SkyGuard AI does not treat them as sensor faults.</p>
              </>
            )}
          </Card>

          <Card title="By region" icon={<MapPinned size={14} />}>
            {!regions.length ? <Empty>No live stations.</Empty> : (
              <table className="lv-table">
                <thead><tr><th>Region</th><th style={{ textAlign: 'right' }}>Stations</th><th style={{ textAlign: 'right' }}>Need attention</th><th style={{ textAlign: 'right' }}>Anomalous</th></tr></thead>
                <tbody>
                  {regions.slice(0, 8).map(([r, e]) => (
                    <tr key={r}><td>{r}</td><td style={{ textAlign: 'right' }}>{e.total}</td>
                      <td style={{ textAlign: 'right', color: e.attention ? 'var(--s-warning-ink)' : undefined, fontWeight: e.attention ? 700 : 400 }}>{e.attention}</td>
                      <td style={{ textAlign: 'right', color: e.critical ? 'var(--s-critical-ink)' : undefined, fontWeight: e.critical ? 700 : 400 }}>{e.critical}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      </div>

    </div>
  );
};
