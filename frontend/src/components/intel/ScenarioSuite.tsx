import React, { useEffect, useMemo, useState } from 'react';
import { Play, PlayCircle } from 'lucide-react';
import { fetchSimulationScenarios, runSimulation } from '../../services/api';
import { Card, Empty, fmt, pct } from '../live/LiveBits';
import { IntelligencePipeline } from './IntelligencePipeline';
import { fromAssessment } from '../../utils/pipeline';

const BUCKET: Record<string, string> = {
  LIKELY_SENSOR_ANOMALY: 'Sensor anomaly',
  DATA_QUALITY_VIOLATION: 'Physical / data-quality violation',
  POSSIBLE_WEATHER_EVENT: 'Weather event (not a fault)',
  INSUFFICIENT_EVIDENCE: 'Insufficient evidence',
  NORMAL: 'No anomaly',
  UNCLASSIFIED: 'Unclassified',
};
const LAYER_ORDER: [string, string][] = [['physics', 'L1'], ['temporal', 'L2'], ['multivariate', 'L3'], ['spatial', 'L4'], ['sensor_health', 'L5']];

/** Model for the shared pipeline view, built from a Test Lab run. */
function modelFor(r: any) {
  return fromAssessment({
    layers: r.diagnostics,
    status: r.fusion?.status,
    veto_fired: r.fusion?.veto_fired,
    overall: { confidence: r.fusion?.confidence, score: r.fusion?.score },
    diagnosis: { primary: r.root_cause?.category, confidence: r.root_cause?.confidence, evidence: r.root_cause?.evidence, alternatives: r.root_cause?.alternatives },
    operator_action: r.recommended_action,
    observation: { source: 'SYNTHETIC_TEST' },
  });
}

const layerTone = (st: string) => /ANOMALY|VETO/.test(st) ? 'lv-layer-hit' : st === 'WARNING' ? 'lv-layer-warn' : /INSUFF|LIMITED|NOT_APP|UNAVAIL/.test(st) ? 'lv-layer-na' : 'lv-layer-ok';

/**
 * Curated scenario suite: each case runs through a FRESH engine instance
 * (backend app/simulation) and is shown as
 *   INPUT → EXPECTED → LAYER RESPONSES → FUSION → FINAL DETECTION → ROOT CAUSE
 * "Differs" results are shown as they are — never forced to pass.
 */
export const ScenarioSuite: React.FC = () => {
  const [scenarios, setScenarios] = useState<any[]>([]);
  const [results, setResults] = useState<Record<string, any>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { fetchSimulationScenarios().then((r) => setScenarios(r.scenarios || [])).catch((e) => setError(e.message)); }, []);

  const run = async (id: string) => {
    setRunning(id); setError(null);
    try {
      const r = await runSimulation(id);
      setResults((m) => ({ ...m, [id]: r }));
      setSelected(id);
    } catch (e: any) { setError(e.message); } finally { setRunning(null); }
  };
  const runAll = async () => {
    for (const s of scenarios) {
      // sequential: each run is an isolated engine instance on the backend
      // eslint-disable-next-line no-await-in-loop
      await run(s.id);
    }
  };

  const r = selected ? results[selected] : null;
  const model = useMemo(() => (r ? modelFor(r) : null), [r]);
  const done = Object.keys(results).length;
  const passed = Object.values(results).filter((x: any) => x.test_result?.passed).length;
  const obsParams = r ? (['temperature', 'humidity', 'pressure'] as const).filter((p) => r.observations.some((o: any) => o[p] != null)) : [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card title="Validation matrix" icon={<PlayCircle size={14} />}
        right={<button className="lv-btn lv-btn-primary" onClick={runAll} disabled={!!running || !scenarios.length}><Play size={14} />Run all {scenarios.length} scenarios</button>}>
        {error && <div className="lv-callout danger" style={{ marginBottom: 10 }}>{error}</div>}
        {!scenarios.length ? <Empty>Loading scenarios…</Empty> : (
          <div className="lv-table-wrap">
            <table className="lv-table">
              <thead><tr><th>Scenario</th><th>Expected behaviour</th><th>ATHER's result</th><th>Layers with evidence</th><th>Outcome</th><th /></tr></thead>
              <tbody>
                {scenarios.map((s) => {
                  const x = results[s.id];
                  return (
                    <tr key={s.id} className={`clickable ${selected === s.id ? 'selected' : ''}`} onClick={() => (x ? setSelected(s.id) : run(s.id))}>
                      <td><b>{s.name}</b><div className="lv-muted" style={{ fontSize: '0.7rem' }}>{s.step_count} observations</div></td>
                      <td>{BUCKET[s.expected_bucket] || s.expected_bucket}</td>
                      <td>{x ? BUCKET[x.test_result.actual_bucket] || x.test_result.actual_bucket : <span className="lv-muted">not run</span>}</td>
                      <td>{x ? (
                        <span className="lv-layers lv-layers-compact">
                          {LAYER_ORDER.map(([k, c]) => <span key={k} className={`lv-layer ${layerTone(String(x.diagnostics?.[k]?.status || ''))}`}><b>{c}</b></span>)}
                        </span>) : '—'}</td>
                      <td>{x ? (x.test_result.passed
                        ? <span className="lv-pill lv-pill-sm lv-status-nominal"><span className="lv-dot" />Matches</span>
                        : <span className="lv-pill lv-pill-sm lv-status-suspect"><span className="lv-dot" />Differs</span>) : '—'}</td>
                      <td>{running === s.id ? <span className="lv-muted">running…</span> : <button className="lv-link" onClick={(e) => { e.stopPropagation(); run(s.id); }}>{x ? 'Re-run' : 'Run'}</button>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {done > 0 && (
          <p className="a-note" style={{ marginTop: 8 }}>
            {passed} of {done} run scenario(s) match their documented expectation. Synthetic test performance — not a measure of real-world operational accuracy.
          </p>
        )}
      </Card>

      {r && model && (
        <>
          <div className="a-flow">
            <div className="a-flow-cell"><span className="a-eyebrow">1 · Input</span>
              <b style={{ fontSize: '0.82rem' }}>{r.scenario.name}</b>
              <div className="lv-muted">{r.observations.length} observations · final T {fmt(r.final_observation.temperature, 1, ' °C')}, RH {fmt(r.final_observation.humidity, 0, ' %')}, P {fmt(r.final_observation.pressure, 1, ' hPa')}</div></div>
            <div className="a-flow-cell"><span className="a-eyebrow">2 · Expected</span>
              <b style={{ fontSize: '0.82rem' }}>{BUCKET[r.scenario.expected_bucket]}</b>
              <div className="lv-muted">{r.scenario.expected_root_cause_hint ? `hint: ${r.scenario.expected_root_cause_hint.replace(/_/g, ' ').toLowerCase()}` : ''}</div></div>
            <div className="a-flow-cell"><span className="a-eyebrow">3 · Layer responses</span>
              <span className="lv-layers lv-layers-compact">
                {LAYER_ORDER.map(([k, c]) => <span key={k} className={`lv-layer ${layerTone(String(r.diagnostics?.[k]?.status || ''))}`} title={r.diagnostics?.[k]?.reason}><b>{c}</b></span>)}
              </span></div>
            <div className="a-flow-cell"><span className="a-eyebrow">4 · Fusion</span>
              <b style={{ fontSize: '0.82rem' }}>{r.fusion.status.toLowerCase()}{r.fusion.veto_fired ? ' (physics veto)' : ''}</b>
              <div className="lv-muted">score {fmt(r.fusion.score, 2)} · confidence {pct(r.fusion.confidence)}*</div></div>
            <div className="a-flow-cell"><span className="a-eyebrow">5 · Final detection</span>
              <b style={{ fontSize: '0.82rem' }}>{BUCKET[r.test_result.actual_bucket]}</b>
              <div>{r.test_result.passed ? <span className="lv-pill lv-pill-sm lv-status-nominal">matches expectation</span> : <span className="lv-pill lv-pill-sm lv-status-suspect">differs from expectation</span>}</div></div>
            <div className="a-flow-cell"><span className="a-eyebrow">6 · Root cause / insight</span>
              <b style={{ fontSize: '0.82rem' }}>{String(r.root_cause.category).replace(/_/g, ' ').toLowerCase()}</b>
              <div className="lv-muted">{r.recommended_action}</div></div>
          </div>
          {!r.test_result.passed && <div className="lv-callout warn">{r.test_result.note}</div>}

          <div className="lv-grid-2" style={{ gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 2fr)' }}>
            <Card title="Input sequence">
              <p className="lv-muted" style={{ marginTop: 0 }}>{r.scenario.description}</p>
              <div className="lv-table-wrap lv-scroll">
                <table className="lv-table">
                  <thead><tr><th>#</th>{obsParams.map((p) => <th key={p}>{p === 'temperature' ? 'T °C' : p === 'humidity' ? 'RH %' : 'P hPa'}</th>)}<th>Engine</th></tr></thead>
                  <tbody>
                    {r.observations.map((o: any) => (
                      <tr key={o.step}><td className="lv-muted">{o.step}</td>
                        {obsParams.map((p) => <td key={p} className="a-num">{fmt(o[p], p === 'pressure' ? 1 : 1)}</td>)}
                        <td><span className={`lv-pill lv-pill-sm ${o.status === 'ANOMALY' ? 'lv-status-anomaly' : o.status === 'WARNING' ? 'lv-status-suspect' : 'lv-status-nominal'}`}>{o.status.toLowerCase()}</span></td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="Full engine trace — final observation">
              <IntelligencePipeline model={model} />
            </Card>
          </div>
        </>
      )}
    </div>
  );
};
