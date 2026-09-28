import React from 'react';
import { Printer, X } from 'lucide-react';
import { fmtDateTime } from '../live/LiveBits';
import { INTERPRETATION_LABEL } from '../../services/live';
import { WO_LABEL, human, layerRows, lifecycleSteps, opsStatus, timeline } from './incidentModel';

const PARAM_KEY: Record<string, string> = { Temperature: 'temperature', Humidity: 'humidity', Pressure: 'pressure' };
const UNIT: Record<string, string> = { temperature: '°C', humidity: '%', pressure: 'hPa', wind_speed: 'km/h', wind_direction: '°', rainfall: 'mm', dew_point: '°C' };
// Only the reference values the backend used as expectations (not counts or z-scores).
const EXPECT_KEYS = ['rolling_median', 'spatial_consensus', 'reference', 'nwp', 'expected'];

/**
 * One-screen incident report. Every field is read from the incident record;
 * a field the record does not hold is shown as "not recorded", never guessed.
 * Print uses the browser's print / save-as-PDF.
 */
export const IncidentReport: React.FC<{ inc: any; onClose: () => void }> = ({ inc, onClose }) => {
  const ctx = inc.context || {};
  const param = PARAM_KEY[inc.parameter] || String(inc.parameter || '').toLowerCase();
  const obs = ctx.observed_values || {};
  const exp = Object.fromEntries(Object.entries(ctx.expected?.[param] || {})
    .filter(([k, v]) => typeof v === 'number' && EXPECT_KEYS.some((e) => k.startsWith(e))));
  const layers = layerRows(inc);
  const status = opsStatus(inc);
  const NR = <span className="sg-nr">not recorded</span>;

  return (
    <div className="sg-report-overlay" role="dialog" aria-label={`Incident report ${inc.incident_id}`}>
      <div className="sg-report-bar sg-noprint">
        <span className="a-eyebrow">Incident report</span>
        <span className="lv-row">
          <button className="lv-btn" onClick={() => window.print()}><Printer size={14} />Print / save PDF</button>
          <button className="lv-btn" onClick={onClose}><X size={14} />Close</button>
        </span>
      </div>
      <article className="sg-report">
        <header className="sg-report-head">
          <div>
            <div className="sg-report-brand">SkyGuard AI · AWS network operations</div>
            <h1>Incident report {inc.incident_id}</h1>
            <p>{ctx.rca_label || human(inc.root_cause)} — {inc.station_name || inc.station_id}</p>
          </div>
          <dl>
            <dt>Status</dt><dd>{status.label}</dd>
            <dt>Severity</dt><dd>{inc.severity}</dd>
            <dt>Source</dt><dd>{inc.source === 'SIMULATED_FEED' ? 'Simulated AWS feed' : human(inc.source)}</dd>
            <dt>Generated</dt><dd>{fmtDateTime(new Date().toISOString())}</dd>
          </dl>
        </header>

        <section>
          <h2>1 · Summary</h2>
          <table className="sg-kv">
            <tbody>
              <tr><th>Station</th><td>{inc.station_name || '—'} <span className="lv-mono">{inc.station_id}</span>{inc.region ? ` · ${inc.region}` : ''}</td></tr>
              <tr><th>First observed</th><td>{ctx.first_observation_at ? fmtDateTime(ctx.first_observation_at) : NR}</td></tr>
              <tr><th>Detected</th><td>{fmtDateTime(inc.detected_at)}</td></tr>
              <tr><th>Affected sensor</th><td>{inc.parameter || NR}</td></tr>
              <tr><th>Observed anomaly</th><td>{ctx.summary || (inc.evidence || [])[0] || NR}</td></tr>
              <tr><th>Interpretation</th><td>{INTERPRETATION_LABEL[ctx.interpretation] || (ctx.interpretation ? human(ctx.interpretation) : NR)}</td></tr>
            </tbody>
          </table>
        </section>

        <section>
          <h2>2 · Key readings at detection</h2>
          {Object.keys(obs).length ? (
            <table className="lv-table">
              <thead><tr><th>Variable</th><th>Observed</th>{param && exp && Object.keys(exp).length > 0 && <th>Expected ({param})</th>}</tr></thead>
              <tbody>
                {Object.entries(obs).filter(([, v]) => typeof v === 'number').map(([k, v]) => (
                  <tr key={k}><td>{human(k)}</td><td>{(v as number).toFixed(1)} {UNIT[k] || ''}</td>
                    {k === param && Object.keys(exp).length > 0 && <td>{Object.entries(exp).filter(([, x]) => typeof x === 'number').map(([n, x]) => `${human(n)} ${(x as number).toFixed(1)}`).join(' · ')}</td>}</tr>
                ))}
              </tbody>
            </table>
          ) : <p>{typeof inc.observed_value === 'number' ? `${inc.parameter}: ${inc.observed_value} ${inc.unit || ''}` : 'Readings were not captured with this incident.'}</p>}
        </section>

        <section>
          <h2>3 · Detection layers</h2>
          {layers.length ? (
            <table className="lv-table">
              <thead><tr><th>Layer</th><th>Result</th><th>Evidence</th></tr></thead>
              <tbody>
                {layers.map((l) => (
                  <tr key={l.code}><td>{l.code} {l.name}</td><td><b>{l.state}</b></td><td>{l.reason}{l.triggered && l.score !== null ? ` (evidence score ${l.score.toFixed(2)})` : ''}</td></tr>
                ))}
              </tbody>
            </table>
          ) : <p>Per-layer results were not captured with this incident.</p>}
          {(inc.evidence || []).length > 0 && (
            <ul className="sg-list">{inc.evidence.map((e: string, i: number) => <li key={i}>{e}</li>)}</ul>
          )}
        </section>

        <section>
          <h2>4 · Root cause, severity and recommended action</h2>
          <table className="sg-kv">
            <tbody>
              <tr><th>Root cause</th><td>{ctx.rca_label || human(inc.root_cause)}{inc.root_cause_confidence ? ` (diagnosis confidence ${human(inc.root_cause_confidence)})` : ''}</td></tr>
              <tr><th>Severity</th><td>{inc.severity}{typeof inc.confidence === 'number' ? ` · evidence-quality score ${Math.round(inc.confidence * 100)}% (heuristic, not a calibrated probability)` : ''}</td></tr>
              <tr><th>Recommended action</th><td>{ctx.action_label ? <b>{ctx.action_label}: </b> : null}{inc.recommended_action || NR}</td></tr>
            </tbody>
          </table>
        </section>

        <section>
          <h2>5 · Response</h2>
          <ol className="sg-steps">
            {lifecycleSteps(inc).map((s) => (
              <li key={s.key} className={s.done ? 'done' : ''}><b>{s.label}</b> {s.at ? fmtDateTime(s.at) : '—'}{s.note ? ` · ${s.note}` : ''}</li>
            ))}
          </ol>
          {(inc.work_orders || []).length > 0 && (
            <table className="lv-table" style={{ marginTop: 8 }}>
              <thead><tr><th>Work order</th><th>Issue</th><th>Priority</th><th>Team / assignee</th><th>Status</th><th>Completed</th></tr></thead>
              <tbody>
                {inc.work_orders.map((w: any) => (
                  <tr key={w.work_order_id}><td className="lv-mono">{w.work_order_id}</td><td>{w.issue}</td><td>{human(w.priority)}</td>
                    <td>{w.team}{w.assignee ? ` / ${w.assignee}` : ''}</td><td>{WO_LABEL[w.status]}</td><td>{w.completed_at ? fmtDateTime(w.completed_at) : '—'}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section>
          <h2>6 · Timeline</h2>
          <table className="lv-table">
            <tbody>
              {timeline(inc).map((t, i) => (
                <tr key={i}><td style={{ whiteSpace: 'nowrap' }}>{fmtDateTime(t.at)}</td><td><b>{human(t.stage)}</b>{t.actor ? ` · ${t.actor}` : ''}</td><td>{t.detail || ''}</td></tr>
              ))}
            </tbody>
          </table>
        </section>

        <section>
          <h2>7 · Resolution</h2>
          <p>
            {inc.status === 'RESOLVED' ? <>Resolved{inc.resolution_type ? ` (${human(inc.resolution_type)})` : ''}{inc.resolution_notes ? `: ${inc.resolution_notes}` : '.'}</>
              : inc.status === 'DISMISSED' ? <>Dismissed{inc.dismissal_reason ? `: ${inc.dismissal_reason}` : '.'}</>
              : <>Open — {status.label.toLowerCase()}. This report reflects the incident as of generation time.</>}
          </p>
        </section>
        <footer>Generated by SkyGuard AI from the stored incident record. {inc.source === 'SIMULATED_FEED' ? 'Source telemetry is SIMULATED.' : ''}</footer>
      </article>
    </div>
  );
};
