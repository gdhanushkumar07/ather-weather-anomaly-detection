import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Compass, FileSearch, LineChart, Satellite, ShieldCheck } from 'lucide-react';
import {
  fetchStationDetections, fetchStationLive, fetchStationSpatial, fetchStationTimeseries,
} from '../../services/api';
import { INTERPRETATION_LABEL, formatAge, useLiveEvents } from '../../services/live';
import { Card, Empty, SourceBadge, StatusPill, fmt, fmtDateTime, fmtTime, pct } from './LiveBits';
import { useNow } from './LivePanels';

/**
 * Live sections of the Station workspace (spec §10/§12/§13/§16).
 * Everything is fetched on demand for THIS station only (time-window
 * queries), then kept current by STATION_UPDATED events for this station.
 */

const PARAMS: { key: string; label: string; unit: string; digits: number }[] = [
  { key: 'temperature', label: 'Temperature', unit: '°C', digits: 1 },
  { key: 'humidity', label: 'Relative humidity', unit: '%', digits: 1 },
  { key: 'pressure', label: 'Pressure', unit: 'hPa', digits: 2 },
  { key: 'dew_point', label: 'Dew point', unit: '°C', digits: 1 },
  { key: 'wind_speed', label: 'Wind speed', unit: 'km/h', digits: 1 },
  { key: 'rainfall', label: 'Rainfall', unit: 'mm', digits: 1 },
];

// ── single-series chart with crosshair tooltip ───────────────────────────
const MiniChart: React.FC<{ points: any[]; param: typeof PARAMS[number]; markers?: number[] }> = ({ points, param, markers = [] }) => {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const W = 520, H = 120, PL = 44, PR = 8, PT = 8, PB = 18;
  const data = points.filter((p) => typeof p[param.key] === 'number');
  if (data.length < 2) {
    return <div className="lv-muted" style={{ padding: '24px 0', textAlign: 'center' }}>No {param.label.toLowerCase()} data in window</div>;
  }
  const xs = data.map((p) => p.epoch);
  const ys = data.map((p) => p[param.key]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (y1 - y0 < 1e-6) { y0 -= 1; y1 += 1; }
  const pad = (y1 - y0) * 0.1; y0 -= pad; y1 += pad;
  const sx = (x: number) => PL + ((x - x0) / Math.max(1, x1 - x0)) * (W - PL - PR);
  const sy = (y: number) => PT + (1 - (y - y0) / (y1 - y0)) * (H - PT - PB);
  const path = data.map((p, i) => `${i ? 'L' : 'M'}${sx(p.epoch).toFixed(1)},${sy(p[param.key]).toFixed(1)}`).join('');
  const ticks = [y0 + pad, (y0 + y1) / 2, y1 - pad];

  const onMove = (e: React.MouseEvent) => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r) return;
    const x = ((e.clientX - r.left) / r.width) * W;
    let best = 0, bd = Infinity;
    data.forEach((p, i) => { const d = Math.abs(sx(p.epoch) - x); if (d < bd) { bd = d; best = i; } });
    setHover(best);
  };
  const h = hover !== null ? data[hover] : null;

  return (
    <div style={{ position: 'relative' }}>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="lv-spark" preserveAspectRatio="none"
        onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label={`${param.label} time series`}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={PL} x2={W - PR} y1={sy(t)} y2={sy(t)} stroke="#eef2f7" strokeWidth={1} />
            <text x={PL - 6} y={sy(t) + 3} fontSize={9} textAnchor="end" fill="#64748b">{t.toFixed(param.digits)}</text>
          </g>
        ))}
        {markers.filter((m) => m >= x0 && m <= x1).map((m, i) => (
          <line key={i} x1={sx(m)} x2={sx(m)} y1={PT} y2={H - PB} stroke="#dc2626" strokeWidth={1} strokeDasharray="3 3" opacity={0.6} />
        ))}
        <path d={path} fill="none" stroke="#2563eb" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        <text x={PL} y={H - 4} fontSize={9} fill="#64748b">{fmtTime(new Date(x0 * 1000).toISOString())}</text>
        <text x={W - PR} y={H - 4} fontSize={9} fill="#64748b" textAnchor="end">{fmtTime(new Date(x1 * 1000).toISOString())}</text>
        {h && (
          <g>
            <line x1={sx(h.epoch)} x2={sx(h.epoch)} y1={PT} y2={H - PB} stroke="#94a3b8" strokeWidth={1} />
            <circle cx={sx(h.epoch)} cy={sy(h[param.key])} r={4} fill="#2563eb" stroke="#fff" strokeWidth={2} />
          </g>
        )}
      </svg>
      {h && (
        <div style={{
          position: 'absolute', top: 0, left: `${(sx(h.epoch) / W) * 100}%`, transform: 'translateX(-50%)',
          background: '#0f172a', color: '#fff', fontSize: 11, padding: '3px 7px', borderRadius: 6, pointerEvents: 'none', whiteSpace: 'nowrap',
        }}>
          {fmtTime(h.t)} · <b>{h[param.key].toFixed(param.digits)} {param.unit}</b>
          {param.key === 'dew_point' && h.dew_point_derived ? ' (derived)' : ''}{h.samples > 1 ? ` · mean of ${h.samples}` : ''}
        </div>
      )}
    </div>
  );
};

// ── detection status strip ───────────────────────────────────────────────
const StatusStrip: React.FC<{ detections: any[] }> = ({ detections }) => {
  const [hover, setHover] = useState<any | null>(null);
  if (!detections.length) return <Empty>No detections recorded in this window.</Empty>;
  const step = Math.max(1, Math.ceil(detections.length / 240));
  const cells = detections.filter((_, i) => i % step === 0);
  return (
    <>
      <div className="lv-strip" onMouseLeave={() => setHover(null)}>
        {cells.map((d) => (
          <span key={d.detection_id} className={d.overall_status} onMouseEnter={() => setHover(d)}
            title={`${fmtTime(d.t)} · ${d.overall_status} · ${pct(d.confidence)} · ${d.root_cause}`} />
        ))}
      </div>
      <div className="lv-spread" style={{ marginTop: 6 }}>
        <div className="lv-legend">
          <span><i style={{ background: '#a7f3d0' }} />Nominal</span>
          <span><i style={{ background: '#fcd34d' }} />Suspect</span>
          <span><i style={{ background: '#c4b5fd' }} />Degraded</span>
          <span><i style={{ background: '#f87171' }} />Anomaly</span>
        </div>
        <span className="lv-muted">{hover ? `${fmtTime(hover.t)} — ${hover.overall_status}, ${pct(hover.confidence)}, ${hover.root_cause}` : `${detections.length} detections`}</span>
      </div>
    </>
  );
};

// ── L5 drift / layer score timeline ──────────────────────────────────────
const LayerScoreTable: React.FC<{ detections: any[] }> = ({ detections }) => {
  const flagged = detections.filter((d) => d.overall_status !== 'nominal').slice(-12).reverse();
  if (!flagged.length) return <p className="lv-muted">No suspect, degraded or anomalous detections in this window.</p>;
  return (
    <div className="lv-table-wrap lv-scroll">
      <table className="lv-table">
        <thead><tr><th>Time</th><th>Status</th><th>Conf.</th><th>L1</th><th>L2</th><th>L3</th><th>L4</th><th>L5</th><th>Root cause</th></tr></thead>
        <tbody>
          {flagged.map((d) => (
            <tr key={d.detection_id}>
              <td>{fmtTime(d.t)}</td>
              <td><StatusPill status={d.overall_status} small /></td>
              <td>{pct(d.confidence)}</td>
              {['L1', 'L2', 'L3', 'L4', 'L5'].map((c) => (
                <td key={c} style={{ fontWeight: d.triggered_layers?.includes(c) ? 800 : 400, color: d.triggered_layers?.includes(c) ? 'var(--lv-anomaly)' : undefined }}>
                  {fmt(d.layer_scores?.[c], 2)}
                </td>
              ))}
              <td>{String(d.root_cause || '').replace(/_/g, ' ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

// ── spatial event analysis ───────────────────────────────────────────────
const SpatialPanel: React.FC<{ stationId: string; refreshKey: number; onSelectStation?: (id: string) => void }> = ({ stationId, refreshKey, onSelectStation }) => {
  const [param, setParam] = useState('temperature');
  const [data, setData] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    fetchStationSpatial(stationId, param, 60, 60).then((d) => { setData(d); setErr(null); }).catch((e) => setErr(e.message));
  }, [stationId, param, refreshKey]);

  const unit = param === 'temperature' ? '°C' : param === 'humidity' ? '%' : 'hPa';
  const verdictCls = data?.verdict === 'isolated' ? 'danger' : data?.verdict === 'regional_event' ? 'weather' : data?.verdict === 'consistent' ? 'ok' : 'info';

  // Local plot: neighbours positioned by bearing/distance, coloured by status.
  const plot = useMemo(() => {
    if (!data) return null;
    const R = 90, cx = 110, cy = 100, maxD = Math.max(5, ...data.neighbours.map((n: any) => n.distance_km));
    const pts = data.neighbours.map((n: any) => {
      const dy = (n.latitude - data.station.latitude) * 111;
      const dx = (n.longitude - data.station.longitude) * 111 * Math.cos((data.station.latitude * Math.PI) / 180);
      return { ...n, x: cx + (dx / maxD) * R, y: cy - (dy / maxD) * R };
    });
    return { pts, R, cx, cy, maxD };
  }, [data]);
  const colour = (s?: string, i?: string) => (i === 'likely_weather_event' ? '#0284c7' : s === 'anomaly' ? '#dc2626' : s === 'suspect' ? '#d97706' : s === 'degraded' ? '#7c3aed' : '#059669');

  return (
    <Card title="Spatial event analysis" icon={<Compass size={14} />}
      right={<select value={param} onChange={(e) => setParam(e.target.value)} className="lv-field" style={{ padding: 4 }}>
        <option value="temperature">Temperature</option><option value="humidity">Humidity</option><option value="pressure">Pressure</option>
      </select>}>
      {err ? <Empty>{err}</Empty> : !data ? <Empty>Loading neighbourhood…</Empty> : (
        <>
          <div className={`lv-callout ${verdictCls}`} style={{ marginBottom: 10 }}>
            <b>{data.verdict.replace(/_/g, ' ').toUpperCase()}.</b> {data.explanation}
          </div>
          <div className="lv-grid-2" style={{ gap: 12 }}>
            <div>
              {plot && (
                <svg viewBox="0 0 220 200" style={{ width: '100%', maxWidth: 260 }} role="img" aria-label="Neighbour map">
                  <circle cx={plot.cx} cy={plot.cy} r={plot.R} fill="#f8fafc" stroke="#e2e8f0" />
                  <circle cx={plot.cx} cy={plot.cy} r={plot.R / 2} fill="none" stroke="#e2e8f0" strokeDasharray="3 3" />
                  <text x={plot.cx + plot.R - 2} y={plot.cy - 4} fontSize={8} fill="#94a3b8" textAnchor="end">{plot.maxD.toFixed(0)} km</text>
                  {plot.pts.map((n: any) => (
                    <circle key={n.station_id} cx={n.x} cy={n.y} r={6} fill={colour(n.overall_status, n.interpretation)} stroke="#fff" strokeWidth={2}
                      style={{ cursor: 'pointer' }} onClick={() => onSelectStation?.(n.station_id)}>
                      <title>{`${n.station_id} · ${n.distance_km} km · ${fmt(n.value, 1, unit)} · Δ ${fmt(n.change_over_window, 1)} · ${n.overall_status}`}</title>
                    </circle>
                  ))}
                  <rect x={plot.cx - 7} y={plot.cy - 7} width={14} height={14} rx={3}
                    fill={colour(data.station.overall_status, data.station.interpretation)} stroke="#0f172a" strokeWidth={2} />
                </svg>
              )}
              <div className="lv-legend">
                <span><i style={{ background: '#0f172a' }} />This station</span>
                <span><i style={{ background: '#059669' }} />Nominal</span>
                <span><i style={{ background: '#d97706' }} />Suspect</span>
                <span><i style={{ background: '#dc2626' }} />Anomaly</span>
                <span><i style={{ background: '#0284c7' }} />Weather</span>
              </div>
            </div>
            <dl className="lv-kv">
              <dt>This station Δ (60 min)</dt><dd>{fmt(data.station.change_over_window, 2, ` ${unit}`)}</dd>
              <dt>Neighbours in {data.radius_km} km</dt><dd>{data.footprint.neighbours_in_radius}</dd>
              <dt>Abnormal neighbours</dt><dd>{data.footprint.abnormal} {data.footprint.abnormal_fraction != null && `(${pct(data.footprint.abnormal_fraction)})`}</dd>
              <dt>Weather-classified</dt><dd>{data.footprint.weather_classified}</dd>
              <dt>L4 consensus (latest)</dt><dd>{data.l4 ? `${data.l4.status} — ${data.l4.reason}` : '—'}</dd>
            </dl>
          </div>
          <div className="lv-table-wrap lv-scroll" style={{ marginTop: 10, maxHeight: 220 }}>
            <table className="lv-table">
              <thead><tr><th>Neighbour</th><th>Dist.</th><th>Now</th><th>Δ 60 min</th><th>Corr.</th><th>Status</th></tr></thead>
              <tbody>
                {data.neighbours.map((n: any) => (
                  <tr key={n.station_id} className="clickable" onClick={() => onSelectStation?.(n.station_id)}>
                    <td><b>{n.station_id}</b> <span className="lv-muted">{n.name}</span></td>
                    <td>{fmt(n.distance_km, 1, ' km')}</td>
                    <td>{fmt(n.value, 1, ` ${unit}`)}</td>
                    <td>{fmt(n.change_over_window, 2)}</td>
                    <td>{n.correlation == null ? '—' : n.correlation.toFixed(2)}</td>
                    <td>{n.interpretation === 'likely_weather_event' ? <span className="lv-pill lv-pill-sm lv-status-weather">weather</span> : <StatusPill status={n.overall_status} small />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
};

// ── main ─────────────────────────────────────────────────────────────────
export const StationLiveSections: React.FC<{
  stationId: string;
  onOpenIncident?: (id: string) => void;
  onSelectStation?: (id: string) => void;
}> = ({ stationId, onOpenIncident, onSelectStation }) => {
  const [live, setLive] = useState<any | null>(null);
  const [series, setSeries] = useState<any | null>(null);
  const [detections, setDetections] = useState<any[]>([]);
  const [hours, setHours] = useState(6);
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const now = useNow();
  const lastFetch = useRef(0);

  const loadLive = useCallback(() => fetchStationLive(stationId).then(setLive).catch((e) => setError(e.message)), [stationId]);
  const loadHistory = useCallback(() => {
    fetchStationTimeseries(stationId, hours, 360).then(setSeries).catch(() => {});
    fetchStationDetections(stationId, hours).then((d) => setDetections(d.detections || [])).catch(() => {});
  }, [stationId, hours]);

  useEffect(() => { setLive(null); setError(null); loadLive(); }, [loadLive]);
  useEffect(() => { loadHistory(); }, [loadHistory]);

  // New observation for THIS station -> refresh its live card at once and its
  // history at most every 10 s (the rest of the network is ignored here).
  useLiveEvents(['STATION_UPDATED'], (e) => {
    if (e.data?.station_id !== stationId) return;
    loadLive();
    if (Date.now() - lastFetch.current > 10000) {
      lastFetch.current = Date.now();
      loadHistory();
      setRefreshKey((k) => k + 1);
    }
  });

  if (error) return <Card title="Live pipeline" icon={<Activity size={14} />}><Empty>{error}</Empty></Card>;
  if (!live) return <Card title="Live pipeline" icon={<Activity size={14} />}><Empty>Loading live state…</Empty></Card>;

  const det = live.latest_detection;
  const h = live.health;
  if (!live.live_feed || !det) {
    return (
      <Card title="Live pipeline" icon={<Activity size={14} />}>
        <div className="lv-callout info">
          This station is in the catalogue but has <b>no live observation feed</b>, so ATHER is not processing it continuously.
          Values shown elsewhere on this page come from the static catalogue snapshot or the NWP reference, and are labelled as such.
        </div>
      </Card>
    );
  }

  const markers = detections.filter((d) => d.overall_status === 'anomaly').map((d) => d.observed_at);
  const available = new Set(series?.parameters_available || []);
  const ref = live.reference_comparison;

  return (
    <>
      {/* 1. Current diagnosis */}
      <Card
        title="Live detection"
        icon={<Activity size={14} />}
        right={<span className="lv-row"><SourceBadge source={h?.source} simulated={h?.simulated} /><span className="lv-muted">observed {formatAge(h?.last_observed_at, now)}</span></span>}
      >
        <div className="lv-row" style={{ marginBottom: 8 }}>
          <StatusPill status={det.overall_status} watch={det.watch} />
          <span className="lv-pill lv-status-unknown">{pct(det.confidence)} confidence</span>
          <span className={`lv-pill ${det.interpretation === 'likely_weather_event' ? 'lv-status-weather' : det.interpretation === 'likely_sensor_fault' ? 'lv-status-anomaly' : 'lv-status-unknown'}`}>
            {INTERPRETATION_LABEL[det.interpretation] || det.interpretation}
          </span>
          {h?.active_incident_id && (
            <button className="lv-btn lv-btn-danger" onClick={() => onOpenIncident?.(h.active_incident_id)}>Open incident {h.active_incident_id}</button>
          )}
        </div>
        <p style={{ fontSize: '0.84rem', margin: '0 0 10px', lineHeight: 1.5 }}>{det.summary}</p>
        <div className="lv-table-wrap">
          <table className="lv-table">
            <thead><tr><th>Layer</th><th>Status</th><th>Score</th><th>Evidence quality</th><th>Why</th></tr></thead>
            <tbody>
              {['L1', 'L2', 'L3', 'L4', 'L5'].map((c) => {
                const r = det.layer_results[c];
                return (
                  <tr key={c}>
                    <td><b>{c}</b> {r.name}</td>
                    <td><span className={`lv-pill lv-pill-sm ${r.triggered ? (r.status === 'WARNING' ? 'lv-status-suspect' : 'lv-status-anomaly') : /INSUFF|LIMITED|NOT_APP/.test(r.status) ? 'lv-status-unknown' : 'lv-status-nominal'}`}>{r.status}</span></td>
                    <td>{fmt(r.score, 2)}</td>
                    <td className="lv-muted">{r.evidence_quality}</td>
                    <td style={{ maxWidth: 460 }}>{r.reason}</td>
                  </tr>
                );
              })}
              <tr>
                <td><b>Fusion</b> Conformal</td>
                <td><span className={`lv-pill lv-pill-sm ${det.engine_status === 'ANOMALY' ? 'lv-status-anomaly' : det.engine_status === 'WARNING' ? 'lv-status-suspect' : 'lv-status-nominal'}`}>{det.engine_status}</span></td>
                <td>{fmt(det.anomaly_score, 2)}</td>
                <td className="lv-muted">p = {fmt(det.layer_results.fusion?.p_value, 3)}</td>
                <td>Nonconformity {fmt(det.layer_results.fusion?.nonconformity_score, 3)} · {det.layer_results.fusion?.meaningful_layer_count ?? 0} layer(s) with evidence{det.layer_results.fusion?.veto ? ' · physics veto' : ''}</td>
              </tr>
            </tbody>
          </table>
        </div>
        {det.overall_status !== 'nominal' && (
          <div className="lv-callout info" style={{ marginTop: 10 }}>
            <b>Diagnosis:</b> {det.diagnosis.rca_label} ({det.diagnosis.confidence}). <b>Action — {det.recommended_action.label}:</b> {det.recommended_action.detail}
          </div>
        )}
      </Card>

      {/* 2. Telemetry history */}
      <Card
        title="Telemetry history"
        icon={<LineChart size={14} />}
        right={<div className="lv-tabs">{[1, 6, 24].map((hh) => <button key={hh} className={`lv-tab ${hours === hh ? 'active' : ''}`} onClick={() => setHours(hh)}>{hh}h</button>)}</div>}
      >
        {!series?.points?.length ? <Empty>No telemetry recorded in the last {hours} h.</Empty> : (
          <>
            <div className="lv-grid-2" style={{ gap: 12 }}>
              {PARAMS.filter((p) => available.has(p.key)).map((p) => (
                <div key={p.key}>
                  <div className="lv-spread"><span className="lv-card-title" style={{ fontSize: '0.66rem' }}>{p.label} ({p.unit}){p.key === 'dew_point' && series.points.some((x: any) => x.dew_point_derived) ? ' · derived' : ''}</span></div>
                  <MiniChart points={series.points} param={p} markers={markers} />
                </div>
              ))}
            </div>
            <p className="lv-muted" style={{ marginTop: 6 }}>
              {series.points.length} points{series.downsampled ? ' (time-bucket means)' : ''} · dashed red lines mark anomaly detections ·
              <SourceBadge source={series.source} simulated={series.source === 'SIMULATED_AWS'} />
            </p>
          </>
        )}
      </Card>

      {/* 3. Detection timeline */}
      <Card title="Detection timeline & drift" icon={<ShieldCheck size={14} />}>
        <StatusStrip detections={detections} />
        <div style={{ marginTop: 12 }}><LayerScoreTable detections={detections} /></div>
        {det.layer_results.L5?.details?.channel_drift && (
          <div className="lv-table-wrap" style={{ marginTop: 12 }}>
            <table className="lv-table">
              <thead><tr><th>Channel</th><th>Drift reference</th><th>CUSUM tier</th><th>Est. bias</th><th>Rate / day</th><th>Mann-Kendall</th><th>Samples</th></tr></thead>
              <tbody>
                {Object.entries(det.layer_results.L5.details.channel_drift).map(([ch, d]: [string, any]) => (
                  <tr key={ch}>
                    <td>{ch.replace('_c', '').replace('_hpa', '').replace('_pct', '')}</td>
                    <td>{d.reference_mode === 'SPATIAL' ? 'vs neighbour consensus' : d.reference_mode === 'BACKGROUND' ? 'vs NWP background' : 'own history (no reference)'}</td>
                    <td>{d.drift_tier}</td>
                    <td>{fmt(d.estimated_bias, 2)}</td>
                    <td>{fmt(d.drift_rate_per_day, 2)}</td>
                    <td>{d.mann_kendall?.tau != null ? `τ ${d.mann_kendall.tau.toFixed(2)} · p ${d.mann_kendall.p_value}` : '—'}</td>
                    <td>{d.samples_tracked}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* 4. Spatial event analysis */}
      <SpatialPanel stationId={stationId} refreshKey={refreshKey} onSelectStation={onSelectStation} />

      {/* 5. NWP reference + provenance */}
      <div className="lv-grid-2">
        <Card title="Observed vs NWP reference" icon={<Satellite size={14} />} right={<span className="lv-badge lv-badge-nwp">MODEL / REFERENCE DATA</span>}>
          {!ref?.available ? <Empty>{ref?.reason || 'Reference source unavailable'}</Empty> : (
            <>
              <table className="lv-table">
                <thead><tr><th>Parameter</th><th>Observed</th><th>NWP reference</th><th>Difference</th></tr></thead>
                <tbody>
                  {Object.entries(ref.parameters || {}).map(([k, v]: [string, any]) => (
                    <tr key={k}><td>{k.replace('_', ' ')}</td><td>{fmt(v.observed, 1, ` ${v.unit}`)}</td><td>{fmt(v.reference, 1, ` ${v.unit}`)}</td>
                      <td style={{ fontWeight: 700 }}>{v.difference == null ? '—' : `${v.difference > 0 ? '+' : ''}${v.difference.toFixed(1)} ${v.unit}`}</td></tr>
                  ))}
                </tbody>
              </table>
              <p className="lv-muted" style={{ marginTop: 6 }}>
                Model time {ref.model_time || '—'} · fetched {formatAge(ref.fetched_at, now)}{ref.stale ? ' (stale)' : ''}. {ref.note}
              </p>
            </>
          )}
        </Card>

        <Card title="Provenance" icon={<FileSearch size={14} />}>
          <dl className="lv-kv">
            <dt>Data source</dt><dd className="lv-row"><SourceBadge source={det.provenance.data_source} simulated={det.provenance.simulated} /> via {det.provenance.adapter}</dd>
            <dt>Observation time</dt><dd>{fmtDateTime(det.provenance.observation_timestamp)}</dd>
            <dt>Received</dt><dd>{fmtDateTime(det.provenance.received_timestamp)}</dd>
            <dt>Processed</dt><dd>{fmtDateTime(det.provenance.processing_timestamp)} ({fmt(det.provenance.processing_ms, 1)} ms)</dd>
            <dt>Freshness</dt><dd>{det.provenance.freshness}</dd>
            <dt>Detector</dt><dd>{det.provenance.detector_version} · {det.provenance.pipeline_version}</dd>
            <dt>Reference model</dt><dd>{det.provenance.reference_model || '—'}</dd>
            <dt>Input parameters</dt><dd className="lv-mono" style={{ fontSize: '0.7rem' }}>{Object.entries(det.provenance.input_parameters || {}).map(([k, v]) => `${k}=${v}`).join(' · ')}</dd>
            <dt>Neighbours used</dt><dd>{det.provenance.neighbor_count}</dd>
            <dt>Triggered rules</dt><dd>{det.provenance.triggered_rules?.length ? det.provenance.triggered_rules.join('; ') : 'none'}</dd>
            <dt>Detection id</dt><dd className="lv-mono">{det.detection_id}</dd>
            {det.provenance.injected_fault && (<><dt>Injected fault</dt><dd>{det.provenance.injected_fault.label} ({det.provenance.injected_fault.severity})</dd></>)}
          </dl>
        </Card>
      </div>
      {live.active_faults?.length > 0 && (
        <div className="lv-callout warn">Test Lab fault active on this station: {live.active_faults.map((f: any) => `${f.label} (${f.parameter || 'station'}, ${f.severity})`).join(', ')}.</div>
      )}
    </>
  );
};
