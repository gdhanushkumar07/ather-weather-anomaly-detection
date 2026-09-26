import React from 'react';
import { FlaskConical, Radio, Satellite, CircleDashed } from 'lucide-react';
import { STATUS_LABEL } from '../../services/live';

/** Small shared pieces for the real-time views. */

export const StatusPill: React.FC<{ status?: string; watch?: boolean; small?: boolean }> = ({ status, watch, small }) => {
  const s = status || 'unknown';
  return (
    <span className={`lv-pill lv-status-${s} ${small ? 'lv-pill-sm' : ''}`} title={watch ? 'Watch: a single undiagnosed excursion, held by alarm hysteresis' : undefined}>
      <span className="lv-dot" />
      {STATUS_LABEL[s] || s}
      {watch ? ' · watch' : ''}
    </span>
  );
};

/** Every value that is not a real measurement is labelled at the point of display. */
export const SourceBadge: React.FC<{ source?: string; simulated?: boolean }> = ({ source, simulated }) => {
  if (simulated || source === 'SIMULATED_AWS') {
    return <span className="lv-badge lv-badge-sim" title="Simulated AWS telemetry for demonstration — not a physical measurement"><FlaskConical size={11} />SIMULATED</span>;
  }
  if (source === 'AWS_IN_SITU') {
    return <span className="lv-badge lv-badge-real" title="Measured by a physical AWS sensor"><Radio size={11} />MEASURED</span>;
  }
  if (source === 'NWP_MODEL_REFERENCE') {
    return <span className="lv-badge lv-badge-nwp" title="Numerical weather model output — reference only"><Satellite size={11} />MODEL REFERENCE</span>;
  }
  return <span className="lv-badge lv-badge-unknown"><CircleDashed size={11} />{source || 'NO LIVE FEED'}</span>;
};

export const LAYER_NAMES: Record<string, string> = {
  L1: 'Physics', L2: 'Temporal', L3: 'Multivariate', L4: 'Spatial', L5: 'Drift',
};

/** L1–L5 chips; triggered layers are highlighted. */
export const LayerStrip: React.FC<{ triggered?: string[]; results?: Record<string, any>; compact?: boolean }> = ({ triggered = [], results, compact }) => (
  <div className={`lv-layers ${compact ? 'lv-layers-compact' : ''}`}>
    {['L1', 'L2', 'L3', 'L4', 'L5'].map((code) => {
      const r = results?.[code];
      const status: string = r?.status || (triggered.includes(code) ? 'ANOMALY' : 'PASS');
      const on = triggered.includes(code) || r?.triggered;
      const cls = on ? (status === 'WARNING' ? 'warn' : 'hit') : /INSUFFICIENT|LIMITED|NOT_APPLICABLE/.test(status) ? 'na' : 'ok';
      return (
        <span key={code} className={`lv-layer lv-layer-${cls}`} title={r?.reason || `${code} ${LAYER_NAMES[code]}: ${status}`}>
          <b>{code}</b>{!compact && <span>{LAYER_NAMES[code]}</span>}
        </span>
      );
    })}
  </div>
);

export const pct = (v?: number | null) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);

export const fmt = (v?: number | null, digits = 1, unit = '') =>
  v === null || v === undefined || Number.isNaN(v) ? '—' : `${v.toFixed(digits)}${unit}`;

export const fmtTime = (iso?: string | null) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

export const fmtDateTime = (iso?: string | null) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

export const Card: React.FC<{ title: React.ReactNode; icon?: React.ReactNode; right?: React.ReactNode; children: React.ReactNode; className?: string }> = ({ title, icon, right, children, className }) => (
  <section className={`lv-card ${className || ''}`}>
    <header className="lv-card-head">
      <span className="lv-card-title">{icon}{title}</span>
      {right}
    </header>
    <div className="lv-card-body">{children}</div>
  </section>
);

export const Empty: React.FC<{ children: React.ReactNode }> = ({ children }) => <div className="lv-empty">{children}</div>;
