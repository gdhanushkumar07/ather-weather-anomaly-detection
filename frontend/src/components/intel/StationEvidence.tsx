import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Compass, FileSearch, LineChart, Satellite, ShieldCheck } from 'lucide-react';
import {
  fetchStationDetections, fetchStationLive, fetchStationSpatial, fetchStationTimeseries,
} from '../../services/api';
import { INTERPRETATION_LABEL, formatAge, useLiveEvents } from '../../services/live';
import { Card, Empty, SourceBadge, StatusPill, fmt, fmtDateTime, fmtTime, pct } from '../live/LiveBits';
import { useNow } from '../live/LivePanels';

/**
 * Station evidence views: telemetry charts, detection status strip, layer
 * score history and the spatial (neighbour) analysis. Data is fetched on
 * demand for one station by the Station workspace.
 */

export const PARAMS: { key: string; label: string; unit: string; digits: number }[] = [
  { key: 'temperature', label: 'Temperature', unit: '°C', digits: 1 },
  { key: 'humidity', label: 'Relative humidity', unit: '%', digits: 1 },
  { key: 'pressure', label: 'Pressure', unit: 'hPa', digits: 2 },
  { key: 'dew_point', label: 'Dew point', unit: '°C', digits: 1 },
  { key: 'wind_speed', label: 'Wind speed', unit: 'km/h', digits: 1 },
  { key: 'rainfall', label: 'Rainfall', unit: 'mm', digits: 1 },
];

// ── single-series chart with crosshair tooltip ───────────────────────────
export const MiniChart: React.FC<{ points: any[]; param: typeof PARAMS[number]; markers?: number[] }> = ({ points, param, markers = [] }) => {
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
export const StatusStrip: React.FC<{ detections: any[] }> = ({ detections }) => {
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
export const LayerScoreTable: React.FC<{ detections: any[] }> = ({ detections }) => {
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
export const SpatialPanel: React.FC<{ stationId: string; refreshKey: number; onSelectStation?: (id: string) => void }> = ({ stationId, refreshKey, onSelectStation }) => {
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

