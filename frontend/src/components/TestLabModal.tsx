import React, { useEffect, useState } from 'react';
import { FlaskConical, X, RotateCcw, Play, Radio, Beaker, AlertTriangle, CheckCircle2, Sliders, Clock, Activity } from 'lucide-react';
import { fetchSimulationScenarios, runSimulation, fetchStationAnomaly } from '../services/api';
import { PREDEFINED_SCENARIOS, PredefinedScenario } from '../data/predefinedScenarios';

interface TestLabModalProps {
  isOpen: boolean;
  onClose: () => void;
  stations: { id: string; name: string }[];
}

const LAYER_ORDER = [
  { key: 'physics', label: 'L1 Physics' },
  { key: 'temporal', label: 'L2 Temporal' },
  { key: 'multivariate', label: 'L3 Multivariate' },
  { key: 'spatial', label: 'L4 Spatial' },
  { key: 'sensor_health', label: 'L5 Sensor Health' },
];

export const TestLabModal: React.FC<TestLabModalProps> = ({ isOpen, onClose, stations }) => {
  const [mode, setMode] = useState<'LIVE' | 'SIMULATION'>('SIMULATION');
  const [scenarios, setScenarios] = useState<PredefinedScenario[]>(PREDEFINED_SCENARIOS);
  const [scenarioId, setScenarioId] = useState<string>(PREDEFINED_SCENARIOS[0].id);
  const [baseStationId, setBaseStationId] = useState<string>('');
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any | null>(null);
  const [liveResult, setLiveResult] = useState<any | null>(null);

  // Load scenarios from backend if available, merging with static definitions to guarantee instant display
  useEffect(() => {
    if (!isOpen) return;
    fetchSimulationScenarios()
      .then((res) => {
        if (res.scenarios && res.scenarios.length > 0) {
          const merged = PREDEFINED_SCENARIOS.map((local) => {
            const remote = res.scenarios.find((s: any) => s.id === local.id);
            return remote ? { ...local, ...remote } : local;
          });
          setScenarios(merged);
        }
      })
      .catch(() => {
        // Fallback to local definitions with zero 404/Not Found crash
        setScenarios(PREDEFINED_SCENARIOS);
      });
  }, [isOpen]);

  if (!isOpen) return null;

  const selectedScenario = scenarios.find((s) => s.id === scenarioId) || PREDEFINED_SCENARIOS[0];

  const handleRun = async () => {
    setError(null);
    setIsRunning(true);
    try {
      if (mode === 'SIMULATION') {
        const res = await runSimulation(scenarioId, baseStationId || undefined);
        setResult(res);
      } else {
        if (!baseStationId) {
          setError('Select a real AWS station to view its live diagnostics.');
          setIsRunning(false);
          return;
        }
        const res = await fetchStationAnomaly(baseStationId);
        setLiveResult(res);
      }
    } catch (e: any) {
      setError(e.message || 'Run failed.');
    } finally {
      setIsRunning(false);
    }
  };

  const handleReset = () => {
    setResult(null);
    setLiveResult(null);
    setError(null);
  };

  const activeResult = mode === 'SIMULATION' ? result : liveResult;
  const layers = mode === 'SIMULATION' ? (result?.diagnostics || {}) : (liveResult?.layers || liveResult?.diagnostics || {});
  const fusion = mode === 'SIMULATION' ? result?.fusion : (liveResult ? {
    status: liveResult.status, score: liveResult.anomaly_score, confidence: liveResult.confidence,
    interpretation: liveResult.explanation,
  } : null);
  const rootCause = mode === 'SIMULATION' ? result?.root_cause : (liveResult ? {
    category: liveResult.root_cause, confidence: liveResult.diagnosis?.confidence || liveResult.diagnosis_confidence,
    evidence: liveResult.reasons, primary_signal: liveResult.diagnosis?.primary,
  } : null);
  const recommendedAction = mode === 'SIMULATION' ? result?.recommended_action : liveResult?.operator_action;

  return (
    <div className="test-lab-overlay" role="dialog" aria-modal="true">
      <div className="test-lab-scrim" onClick={onClose} />
      <div className="test-lab-workspace">
        {/* Header */}
        <div className="test-lab-header">
          <div className="test-lab-title-group">
            <div className="test-lab-icon-badge">
              <FlaskConical className="w-4 h-4" />
            </div>
            <div>
              <div className="test-lab-title">ATHER TEST LAB</div>
              <div className="test-lab-subtitle">Diagnostic Simulation — validates the real 5-layer engine using controlled AWS fault scenarios</div>
            </div>
          </div>
          <div className="test-lab-header-right">
            <span className={`simulation-mode-badge ${mode === 'SIMULATION' ? 'active' : 'live'}`}>
              {mode === 'SIMULATION' ? 'SIMULATION MODE — no production data affected' : 'LIVE DATA — read only'}
            </span>
            <button className="btn-close-panel" onClick={onClose} title="Close Test Lab">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="test-lab-body">
          {/* Mode + Config */}
          <div className="section-card test-lab-config-card">
            <div className="card-header-flex">
              <div className="card-title-group">
                <Beaker className="w-3.5 h-3.5 text-cyan-400" />
                <span className="card-section-title">MODE</span>
              </div>
            </div>
            <div className="mode-toggle-row">
              <button className={`mode-toggle-btn ${mode === 'LIVE' ? 'active' : ''}`} onClick={() => setMode('LIVE')}>
                <Radio className="w-3 h-3" /> LIVE
              </button>
              <button className={`mode-toggle-btn ${mode === 'SIMULATION' ? 'active' : ''}`} onClick={() => setMode('SIMULATION')}>
                <FlaskConical className="w-3 h-3" /> SIMULATION
              </button>
            </div>

            <div className="test-lab-field-row">
              <label className="test-lab-field-label">
                {mode === 'SIMULATION' ? 'Inherit metadata from real station (optional)' : 'Select AWS Station'}
              </label>
              <select
                className="test-lab-select"
                value={baseStationId}
                onChange={(e) => setBaseStationId(e.target.value)}
              >
                <option value="">{mode === 'SIMULATION' ? 'Use default virtual location' : 'Select a station...'}</option>
                {stations.slice(0, 500).map((s) => (
                  <option key={s.id} value={s.id}>{s.name} ({s.id})</option>
                ))}
              </select>
            </div>

            {mode === 'SIMULATION' && (
              <>
                <div className="test-lab-field-row">
                  <label className="test-lab-field-label">Test Case</label>
                  <select className="test-lab-select" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
                    {scenarios.map((s) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </select>
                </div>
                {selectedScenario && (
                  <div className="test-lab-scenario-desc">
                    {selectedScenario.description}
                    <div className="test-lab-scenario-meta">
                      {selectedScenario.step_count} observation{selectedScenario.step_count > 1 ? 's' : ''} ·
                      Expected Diagnosis: <strong>{selectedScenario.expected_bucket.replace(/_/g, ' ')}</strong>
                      {selectedScenario.expected_root_cause_hint && ` (${selectedScenario.expected_root_cause_hint})`}
                    </div>
                  </div>
                )}
              </>
            )}

            {/* B2 / B10: FAULT PARAMETERS DISPLAY (Normal vs Injected) */}
            {mode === 'SIMULATION' && selectedScenario && (
              <div className="fault-params-container" style={{ marginTop: '14px', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  <Sliders className="w-3.5 h-3.5 text-cyan-400" />
                  <span style={{ fontSize: '0.72rem', fontWeight: 600, letterSpacing: '0.05em', color: '#94a3b8' }}>
                    FAULT PARAMETERS
                  </span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
                  <div style={{ background: 'rgba(15, 23, 42, 0.65)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '6px', padding: '8px' }}>
                    <div style={{ fontSize: '0.66rem', color: '#94a3b8', marginBottom: '4px', fontWeight: 600 }}>TEMPERATURE</div>
                    <div style={{ fontSize: '0.7rem', color: '#cbd5e1' }}>
                      Normal: <span style={{ color: '#10b981', fontFamily: 'var(--font-mono)' }}>{fmtVal(selectedScenario.baseline.temperature)} °C</span>
                    </div>
                    <div style={{ fontSize: '0.7rem', color: '#cbd5e1', marginTop: '2px' }}>
                      Injected: <span style={{ color: selectedScenario.injected.temperature !== selectedScenario.baseline.temperature ? '#f59e0b' : '#94a3b8', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                        {selectedScenario.injected.temperature !== null ? `${fmtVal(selectedScenario.injected.temperature)} °C` : 'null'}
                      </span>
                    </div>
                  </div>

                  <div style={{ background: 'rgba(15, 23, 42, 0.65)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '6px', padding: '8px' }}>
                    <div style={{ fontSize: '0.66rem', color: '#94a3b8', marginBottom: '4px', fontWeight: 600 }}>PRESSURE</div>
                    <div style={{ fontSize: '0.7rem', color: '#cbd5e1' }}>
                      Normal: <span style={{ color: '#10b981', fontFamily: 'var(--font-mono)' }}>{fmtVal(selectedScenario.baseline.pressure)} hPa</span>
                    </div>
                    <div style={{ fontSize: '0.7rem', color: '#cbd5e1', marginTop: '2px' }}>
                      Injected: <span style={{ color: selectedScenario.injected.pressure !== selectedScenario.baseline.pressure ? '#f59e0b' : '#94a3b8', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                        {selectedScenario.injected.pressure !== null ? `${fmtVal(selectedScenario.injected.pressure)} hPa` : 'null'}
                      </span>
                    </div>
                  </div>

                  <div style={{ background: 'rgba(15, 23, 42, 0.65)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '6px', padding: '8px' }}>
                    <div style={{ fontSize: '0.66rem', color: '#94a3b8', marginBottom: '4px', fontWeight: 600 }}>HUMIDITY</div>
                    <div style={{ fontSize: '0.7rem', color: '#cbd5e1' }}>
                      Normal: <span style={{ color: '#10b981', fontFamily: 'var(--font-mono)' }}>{fmtVal(selectedScenario.baseline.humidity)} %</span>
                    </div>
                    <div style={{ fontSize: '0.7rem', color: '#cbd5e1', marginTop: '2px' }}>
                      Injected: <span style={{ color: selectedScenario.injected.humidity !== selectedScenario.baseline.humidity ? '#f59e0b' : '#94a3b8', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                        {selectedScenario.injected.humidity !== null ? `${fmtVal(selectedScenario.injected.humidity)} %` : 'null'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Time Series Preview */}
                {selectedScenario.time_series_preview && selectedScenario.time_series_preview.length > 1 && (
                  <div style={{ marginTop: '10px', background: 'rgba(15, 23, 42, 0.45)', border: '1px solid rgba(255,255,255,0.05)', borderRadius: '6px', padding: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.66rem', color: '#94a3b8', marginBottom: '6px', fontWeight: 600 }}>
                      <Clock className="w-3 h-3 text-cyan-400" />
                      SYNTHETIC TIME SERIES ({selectedScenario.step_count} observations)
                    </div>
                    <div style={{ display: 'flex', gap: '6px', overflowX: 'auto', paddingBottom: '4px' }}>
                      {selectedScenario.time_series_preview.map((pt) => (
                        <div key={pt.step} style={{ background: 'rgba(30, 41, 59, 0.6)', padding: '4px 7px', borderRadius: '4px', fontSize: '0.65rem', whiteSpace: 'nowrap' }}>
                          <div style={{ color: '#64748b' }}>Step {pt.step}</div>
                          <div style={{ color: '#f8fafc', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                            {pt.temperature !== null ? `${pt.temperature}°C` : '--'}
                          </div>
                          <div style={{ color: '#94a3b8', fontSize: '0.6rem' }}>
                            {pt.pressure !== null ? `${pt.pressure}hPa` : '--'}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="test-lab-run-row" style={{ marginTop: '16px' }}>
              <button className="btn-run-simulation" onClick={handleRun} disabled={isRunning || (mode === 'SIMULATION' && !scenarioId)}>
                <Play className="w-3.5 h-3.5" />
                {isRunning ? 'RUNNING REAL ATHER ENGINE...' : mode === 'SIMULATION' ? 'RUN SIMULATION' : 'LOAD LIVE DIAGNOSTICS'}
              </button>
              <button className="btn-reset-simulation" onClick={handleReset}>
                <RotateCcw className="w-3.5 h-3.5" /> RESET
              </button>
            </div>
            {error && <div className="test-lab-error">{error}</div>}
          </div>

          {activeResult && (
            <>
              {/* Observation summary */}
              <div className="section-card">
                <div className="card-header-flex">
                  <div className="card-title-group">
                    <span className="card-section-title">{mode === 'SIMULATION' ? 'SIMULATION RESULT' : 'LIVE OBSERVATION'}</span>
                  </div>
                  {mode === 'SIMULATION' && (
                    <span className="source-tag-pill unavailable" title="Fabricated for testing only">SYNTHETIC TEST DATA</span>
                  )}
                </div>
                <div className="test-lab-obs-grid">
                  <div><span className="metric-title">STATION</span><div className="metric-val">{mode === 'SIMULATION' ? result.station.id : baseStationId}</div></div>
                  {mode === 'SIMULATION' && (
                    <div><span className="metric-title">SCENARIO</span><div className="metric-val">{result.scenario.name}</div></div>
                  )}
                  <div><span className="metric-title">TEMPERATURE</span><div className="metric-val">{fmtVal(mode === 'SIMULATION' ? result.final_observation.temperature : liveResult.raw_values?.temperature_c)}°C</div></div>
                  <div><span className="metric-title">PRESSURE</span><div className="metric-val">{fmtVal(mode === 'SIMULATION' ? result.final_observation.pressure : liveResult.raw_values?.pressure_hpa)} hPa</div></div>
                  <div><span className="metric-title">HUMIDITY</span><div className="metric-val">{fmtVal(mode === 'SIMULATION' ? result.final_observation.humidity : liveResult.raw_values?.humidity_pct)}%</div></div>
                </div>
              </div>

              {/* 5-Layer Diagnostics */}
              <div className="section-card">
                <div className="card-header-flex">
                  <span className="card-section-title">5-LAYER DIAGNOSTICS</span>
                </div>
                <div className="layer-cards-list">
                  {LAYER_ORDER.map(({ key, label }) => {
                    const layer = layers[key];
                    if (!layer) return null;
                    return (
                      <div key={key} className="layer-card-row">
                        <div className="layer-card-top">
                          <span className="layer-card-label">{label}</span>
                          <span className={`layer-status-pill ${layer.status}`}>{layer.status}</span>
                        </div>
                        <div className="layer-card-reason">{layer.reason}</div>
                        <div className="layer-card-meta">
                          Score: {typeof layer.score === 'number' ? layer.score.toFixed(2) : '--'} · Evidence quality: {layer.evidence_quality}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Fusion */}
              {fusion && (
                <div className="section-card">
                  <div className="card-header-flex"><span className="card-section-title">FUSION</span></div>
                  <div className={`primary-status-banner ${fusion.status}`}>
                    <div className="status-banner-left">
                      <div className={`status-pill ${fusion.status}`}>
                        <span className="status-pill-dot" /><span className="status-pill-text">{fusion.status}</span>
                      </div>
                    </div>
                    <div className="status-banner-metrics">
                      <div className="status-metric-item">
                        <span className="metric-title">CONFIDENCE</span>
                        <span className="metric-val">{Math.round((fusion.confidence || 0) * 100)}%</span>
                      </div>
                    </div>
                  </div>
                  <div className="test-lab-explanation">{fusion.interpretation}</div>
                </div>
              )}

              {/* Root Cause */}
              {rootCause && (
                <div className="section-card">
                  <div className="card-header-flex"><span className="card-section-title">ROOT CAUSE</span></div>
                  <div className="test-lab-root-cause-title">{String(rootCause.category).replace(/_/g, ' ')}</div>
                  {rootCause.evidence?.length > 0 && (
                    <ul className="test-lab-evidence-list">
                      {rootCause.evidence.slice(0, 4).map((ev: string, i: number) => <li key={i}>{ev}</li>)}
                    </ul>
                  )}
                </div>
              )}

              {/* Recommended Action */}
              {recommendedAction && (
                <div className="section-card">
                  <div className="card-header-flex"><span className="card-section-title">RECOMMENDED ACTION</span></div>
                  <div className="test-lab-explanation">{recommendedAction}</div>
                </div>
              )}

              {/* Expected vs Actual Test Result (simulation only) */}
              {mode === 'SIMULATION' && result?.test_result && (
                <div className={`section-card test-result-card ${result.test_result.passed ? 'passed' : 'different'}`}>
                  <div className="card-header-flex">
                    <span className="card-section-title">EXPECTED VS ACTUAL</span>
                    <span style={{ fontSize: '0.65rem', color: '#94a3b8' }}>
                      Layers agreeing: {result.test_result.layers_agreeing}/{result.test_result.layers_total}
                    </span>
                  </div>
                  <div className="test-lab-test-result-row">
                    {result.test_result.passed ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                    ) : (
                      <AlertTriangle className="w-5 h-5 text-amber-400" />
                    )}
                    <div>
                      <div className="test-result-headline" style={{ color: result.test_result.passed ? '#10b981' : '#f59e0b' }}>
                        {result.test_result.passed ? '✓ TEST PASSED' : 'NOT CONFIRMED / DIFFERENT FROM EXPECTED'}
                      </div>
                      <div className="test-result-detail">
                        Expected: <strong style={{ color: '#38bdf8' }}>{result.test_result.expected_bucket.replace(/_/g, ' ')}</strong> · Actual: <strong style={{ color: '#facc15' }}>{result.test_result.actual_bucket.replace(/_/g, ' ')}</strong>
                      </div>
                      <div className="test-result-note">{result.test_result.note}</div>
                    </div>
                  </div>
                  <div className="performance-label-note">{result.performance_label}</div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="test-lab-footer">
          <button className="btn-reset-simulation" onClick={handleReset}>RESET</button>
          <button className="btn-close-test-lab" onClick={onClose}>CLOSE TEST LAB</button>
        </div>
      </div>
    </div>
  );
};

function fmtVal(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--';
  return v.toFixed(1);
}
