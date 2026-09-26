import React from 'react';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { ModelFeature } from '../../types/layerLab';
import { fmt, linear, useWidth } from './chartKit';

const FEATURE_LABELS: Record<string, [string, string]> = {
  temperature_c: ['Temperature', '°C'],
  pressure_hpa: ['Pressure', 'hPa'],
  humidity_pct: ['Relative humidity', '%'],
  dew_point_c: ['Dew point (moisture)', '°C'],
  d_temperature_c_per_h: ['Temperature change', '°C/h'],
  d_pressure_hpa_per_h: ['Pressure change', 'hPa/h'],
  d_humidity_pct_per_h: ['Humidity change', '%/h'],
  rh_given_t_residual_z: ['Humidity given temperature', 'σ'],
  p_given_t_residual_z: ['Pressure given temperature', 'σ'],
};

export const featureLabel = (f: ModelFeature) => FEATURE_LABELS[f.base_feature]?.[0] ?? f.base_feature;

/** p-value on a log axis (1 -> 1e-4) against the model's alpha. */
export const ModelGauge: React.FC<{ name: string; blurb: string; p: number | null; score: number | null; alpha: number; minP?: number }> =
({ name, blurb, p, score, alpha, minP }) => {
  const [ref, width] = useWidth<HTMLDivElement>(300);
  const W = width, H = 46, L = 10, R = W - 10;
  const x = linear(0, 4, L, R);                      // -log10(p)
  const lp = (v: number) => Math.min(4, Math.max(0, -Math.log10(Math.max(v, 1e-6))));
  const flags = p !== null && p <= alpha;
  return (
    <div className="ll-gauge" ref={ref}>
      <div className="ll-gauge-head">
        <span className="ll-gauge-name">{name}</span>
        {p === null ? <span className="ll-status ll-status-muted">not run</span> : flags
          ? <span className="ll-status ll-status-anomaly"><AlertTriangle size={12} /> flags (p ≤ α)</span>
          : <span className="ll-status ll-status-normal"><CheckCircle2 size={12} /> no flag</span>}
      </div>
      <div className="ll-gauge-blurb">{blurb}</div>
      <svg width={W} height={H} role="img" aria-label={`${name} p-value ${p ?? 'n/a'} against alpha ${alpha}`}>
        <rect x={x(lp(alpha))} y={10} width={R - x(lp(alpha))} height={10} className="ll-gauge-zone" />
        <line x1={L} x2={R} y1={15} y2={15} className="ll-baseline" />
        {[0, 1, 2, 3, 4].map((d) => (
          <text key={d} x={x(d)} y={36} className="ll-tick" textAnchor="middle">{d === 0 ? '1' : `1e-${d}`}</text>
        ))}
        <line x1={x(lp(alpha))} x2={x(lp(alpha))} y1={4} y2={26} className="ll-alpha-line" />
        <text x={x(lp(alpha)) + 4} y={8} className="ll-tick">α = {alpha}</text>
        {minP && <line x1={x(lp(minP))} x2={x(lp(minP))} y1={9} y2={21} className="ll-floor-line" />}
        {p !== null && <circle cx={x(lp(p))} cy={15} r={6} className={flags ? 'll-p-dot ll-p-dot-flag' : 'll-p-dot'} />}
      </svg>
      <div className="ll-gauge-foot">
        p = {p === null ? '—' : p < 0.001 ? p.toExponential(1) : p.toFixed(4)} · raw score {fmt(score, 3)}
        {minP ? <> · smallest possible p here {minP.toExponential(1)}</> : null}
      </div>
    </div>
  );
};

/** Where each model input sits within this station/season's own history. */
export const FeatureEvidence: React.FC<{ features: ModelFeature[]; alpha: number }> = ({ features, alpha }) => (
  <div className="ll-features">
    {features.map((f) => {
      const [label, unit] = FEATURE_LABELS[f.base_feature] ?? [f.base_feature, ''];
      const extreme = f.tail_probability <= alpha;
      const pct = Math.min(100, Math.max(0, f.percentile));
      const kind = f.kind === 'relationship' ? 'relationship' : f.kind === 'rate_of_change' ? 'rate of change' : 'vs usual for this hour';
      const detail = f.kind === 'relationship'
        ? `${f.value >= 0 ? '+' : ''}${fmt(f.value, 2)} σ from what the other variable implies`
        : f.expected_for_hour !== null && f.observed !== null
          ? `${fmt(f.observed, 1)} ${unit} vs ${fmt(f.expected_for_hour, 1)} ${unit} usual (${f.value >= 0 ? '+' : ''}${fmt(f.value, 1)})`
          : `${fmt(f.value, 2)} ${unit}`;
      return (
        <div key={f.feature} className={`ll-feature ${extreme ? 'is-extreme' : ''}`}>
          <div className="ll-feature-head">
            <span className="ll-feature-name">{label}<span className="ll-feature-kind">{kind}</span></span>
            {extreme && <span className="ll-status ll-status-warning"><AlertTriangle size={11} /> in the extreme tail</span>}
          </div>
          <div className="ll-feature-track" title={`${pct.toFixed(1)}th percentile of this station's history`}>
            <div className="ll-feature-tail left" /><div className="ll-feature-tail right" />
            <div className="ll-feature-mid" />
            <div className="ll-feature-marker" style={{ left: `${pct}%` }} />
          </div>
          <div className="ll-feature-detail">{detail} · {pct.toFixed(1)}th percentile</div>
        </div>
      );
    })}
  </div>
);
