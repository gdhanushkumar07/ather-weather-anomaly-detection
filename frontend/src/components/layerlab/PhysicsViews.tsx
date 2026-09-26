import React from 'react';
import { CheckCircle2, XOctagon, AlertTriangle, MinusCircle } from 'lucide-react';
import { PhysicsCheck, PhysicsTrace } from '../../types/layerLab';
import { fmt, linear, useWidth } from './chartKit';

const STATUS: Record<string, { icon: React.ReactNode; label: string; cls: string }> = {
  pass: { icon: <CheckCircle2 size={14} />, label: 'PASS', cls: 'normal' },
  veto: { icon: <XOctagon size={14} />, label: 'VETO', cls: 'anomaly' },
  warn: { icon: <AlertTriangle size={14} />, label: 'WARNING', cls: 'warning' },
  skipped: { icon: <MinusCircle size={14} />, label: 'SKIPPED', cls: 'muted' },
};

export const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const s = STATUS[status] ?? STATUS.skipped;
  return <span className={`ll-status ll-status-${s.cls}`}>{s.icon} {s.label}</span>;
};

/** A value on a scale with its allowed zone shaded and limit(s) marked. */
export const LimitBar: React.FC<{ min: number; max: number; lo?: number; hi?: number; value: number; tick?: number; unit: string; flagged: boolean }> =
({ min, max, lo, hi, value, tick, unit, flagged }) => {
  const [ref, width] = useWidth<HTMLDivElement>(260);
  const W = width, L = 6, R = W - 6;
  const x = linear(min, max, L, R);
  const clamp = (v: number) => Math.min(R, Math.max(L, x(v)));
  return (
    <div ref={ref} className="ll-limitbar">
      <svg width={W} height={30} role="img" aria-label={`value ${fmt(value)} ${unit}`}>
        <line x1={L} x2={R} y1={12} y2={12} className="ll-baseline" />
        <rect x={clamp(lo ?? min)} y={7} width={Math.max(0, clamp(hi ?? max) - clamp(lo ?? min))} height={10} rx={2} className="ll-allowed-zone" />
        {lo !== undefined && <line x1={x(lo)} x2={x(lo)} y1={3} y2={21} className="ll-limit-line" />}
        {hi !== undefined && <line x1={x(hi)} x2={x(hi)} y1={3} y2={21} className="ll-limit-line" />}
        {tick !== undefined && <line x1={clamp(tick)} x2={clamp(tick)} y1={5} y2={19} className="ll-expected-tick" />}
        <circle cx={clamp(value)} cy={12} r={5.5} className={flagged ? 'll-p-dot ll-p-dot-flag' : 'll-reading-marker'} />
        <text x={L} y={29} className="ll-tick">{fmt(min, 0)}</text>
        <text x={R} y={29} className="ll-tick" textAnchor="end">{fmt(max, 0)} {unit}</text>
      </svg>
    </div>
  );
};

function checkVisual(c: PhysicsCheck) {
  const flagged = c.status === 'veto' || c.status === 'warn';
  if (c.value === undefined) return null;
  if (c.lower !== undefined && c.upper !== undefined) {
    const span = c.upper - c.lower;
    return { text: `${fmt(c.value)} ${c.unit} (allowed ${c.lower} to ${c.upper} ${c.unit})`,
             bar: <LimitBar min={c.lower - span * 0.08} max={c.upper + span * 0.08} lo={c.lower} hi={c.upper} value={c.value} unit={c.unit ?? ''} flagged={flagged} /> };
  }
  if (c.id === 'dew_point' && c.limit !== undefined) {
    return { text: `dew point ${fmt(c.value)} °C must not exceed air temperature (+0.5 margin) = ${fmt(c.limit)} °C`,
             bar: <LimitBar min={Math.min(c.value, c.limit) - 15} max={Math.max(c.value, c.limit) + 5} hi={c.limit} value={c.value} unit="°C" flagged={flagged} /> };
  }
  if (c.id === 'wet_bulb' && c.limit !== undefined) {
    return { text: `wet-bulb ${fmt(c.value)} °C vs survivability limit ${c.limit} °C`,
             bar: <LimitBar min={0} max={Math.max(40, c.value + 2)} hi={c.limit} value={c.value} unit="°C" flagged={flagged} /> };
  }
  if (c.id === 'hypsometric' && c.expected !== undefined && c.tolerance_pct !== undefined) {
    const tol = c.expected * c.tolerance_pct / 100;
    return { text: `${fmt(c.value)} hPa vs ${fmt(c.expected)} hPa expected at ${fmt(c.elevation_m, 0)} m (deviation ${fmt(c.deviation_pct, 1)}%, tolerance ${c.tolerance_pct}%)`,
             bar: <LimitBar min={c.expected - tol * 1.6} max={c.expected + tol * 1.6} lo={c.expected - tol} hi={c.expected + tol} tick={c.expected} value={c.value} unit="hPa" flagged={flagged} /> };
  }
  if (c.id === 'pinn') return { text: `soft PINN score ${fmt(c.value, 2)} (0 = consistent)`, bar: null };
  return { text: `${fmt(c.value)} ${c.unit ?? ''}`, bar: null };
}

export const PhysicsChecklist: React.FC<{ trace: PhysicsTrace }> = ({ trace }) => (
  <div className="ll-checks">
    {trace.checks.map((c) => {
      const v = checkVisual(c);
      return (
        <div key={c.id} className={`ll-check ll-check-${c.status}`}>
          <div className="ll-check-head">
            <div>
              <div className="ll-check-name">{c.name}</div>
              <div className="ll-check-principle">{c.principle}</div>
            </div>
            <StatusBadge status={c.status} />
          </div>
          {v?.bar}
          <div className="ll-check-detail">{v ? v.text : c.note}</div>
        </div>
      );
    })}
  </div>
);

const CH_LABEL: Record<string, [string, string]> = {
  temperature_c: ['Temperature', '°C'], pressure_hpa: ['Pressure', 'hPa'], humidity_pct: ['Relative humidity', '%'],
};

/** PINN reconstruction vs observation per channel, with the tolerance where scoring starts. */
export const PinnPanel: React.FC<{ trace: PhysicsTrace }> = ({ trace }) => {
  const p = trace.pinn;
  if (!p.available) return <div className="ll-note">The PINN is not trained on this server (run <code>python -m engine.train_pinn</code>).</div>;
  if (!p.channels?.length) return <div className="ll-note">The PINN only runs after every hard physics rule has passed.</div>;
  const start = p.flag_starts_at_z ?? 2;
  return (
    <div className="ll-pinn">
      {p.channels.map((c) => {
        const [label, unit] = CH_LABEL[c.channel];
        const band = c.tolerance * start;
        const flagged = c.z > start;
        return (
          <div key={c.channel} className="ll-pinn-row">
            <div className="ll-check-head">
              <span className="ll-check-name">{label}</span>
              <span className={`ll-status ll-status-${flagged ? 'warning' : 'normal'}`}>
                {flagged ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />} {fmt(c.z, 2)}× tolerance
              </span>
            </div>
            <LimitBar min={c.expected - band * 1.8} max={c.expected + band * 1.8} lo={c.expected - band} hi={c.expected + band}
                      tick={c.expected} value={c.observed} unit={unit} flagged={flagged} />
            <div className="ll-check-detail">observed {fmt(c.observed, 1)} {unit} · physics-consistent reconstruction {fmt(c.expected, 1)} {unit} · residual {c.residual >= 0 ? '+' : ''}{fmt(c.residual, 2)}</div>
          </div>
        );
      })}
      <div className="ll-note">The shaded zone is the reconstruction ± {start}× tolerance; beyond it the PINN adds a soft score (capped at {p.max_score}), never a veto.</div>
    </div>
  );
};
