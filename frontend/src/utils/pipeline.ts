/**
 * ATHER intelligence pipeline — one presentation model for the 10 stages
 *
 *   OBSERVE  1 Data quality
 *   DETECT   2 Physics · 3 Temporal · 4 Multivariate · 5 Spatial · 6 Sensor health
 *   FUSE     7 Evidence fusion · 8 Anomaly decision
 *   EXPLAIN  9 Root cause
 *   ACT      10 Operational insight
 *
 * built from EITHER backend shape:
 *   - the station assessment   GET /api/stations/{id}/anomaly   (fromAssessment)
 *   - a stored DetectionResult GET /api/detections/{id}         (fromDetection)
 *
 * Integrity rules (enforced here, not in the views):
 *   - every value comes from the response; nothing is estimated or defaulted
 *   - a layer that could not assess is "not evaluated" with the backend's
 *     reason — never PASS, never a 0 score (reuses utils/layerEvidence)
 *   - layer scores are evidence scores, not probabilities; confidence is the
 *     backend's heuristic evidence-quality score and is labelled as such
 */
import { deriveLayerEvidence, LayerEvidence, LayerKey, LAYER_KEYS, buildNormalStatusInsight, summarizeEvidence } from './layerEvidence';
import type { EvidenceAvailability } from '../types/weather';

export type StageTone = 'pass' | 'warning' | 'triggered' | 'unassessed' | 'decision' | 'neutral';

export interface Stage {
  n: number;
  key: string;
  name: string;
  checks: string;          // what this stage checks (static, architectural)
  tone: StageTone;
  state: string;           // short status label
  finding: string;         // what it found (from the backend)
  evidence: [string, string][];
  contribution: string;    // how it fed the decision
  notes: string[];
}

export interface Phase {
  id: 'OBSERVE' | 'DETECT' | 'FUSE' | 'EXPLAIN' | 'ACT';
  question: string;
  stages: Stage[];
}

export interface PipelineModel {
  phases: Phase[];
  headline: { status: string; tone: 'nominal' | 'suspect' | 'degraded' | 'anomaly' | 'weather'; confidence: number | null; summary: string };
}

export const CONFIDENCE_NOTE =
  'Heuristic evidence-quality score (strength, availability, corroboration, agreement) — not a calibrated probability.';

const LAYER_META: Record<LayerKey, { n: number; name: string; checks: string }> = {
  physics: { n: 2, name: 'Physics', checks: 'Physically possible values and thermodynamic consistency (WMO-No. 8 limits, dew point ≤ air temperature, wet-bulb)' },
  temporal: { n: 3, name: 'Temporal', checks: 'Behaviour over time: rate of change, stuck/frozen values, robust z-score, LSTM forecast residual' },
  multivariate: { n: 4, name: 'Multivariate', checks: 'Whether temperature, humidity and pressure are plausible together (ECOD / Isolation Forest, psychrometric rules)' },
  spatial: { n: 5, name: 'Spatial', checks: 'Agreement with neighbouring stations (IDW consensus, robust regional baseline)' },
  sensor_health: { n: 6, name: 'Sensor health', checks: 'Slow degradation: CUSUM drift against neighbour consensus, Mann-Kendall trend' },
};

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const f = (v: unknown, d = 2, unit = '') => (isNum(v) ? `${v.toFixed(d)}${unit}` : '—');
const signed = (v: unknown, d = 2, unit = '') => (isNum(v) ? `${v > 0 ? '+' : ''}${v.toFixed(d)}${unit}` : '—');
const human = (s: unknown) => String(s ?? '').replace(/_/g, ' ').toLowerCase();
const CH: Record<string, string> = { temperature_c: 'Temperature', pressure_hpa: 'Pressure', humidity_pct: 'Humidity', wind_speed_kmh: 'Wind' };
const UNIT: Record<string, string> = { temperature_c: ' °C', pressure_hpa: ' hPa', humidity_pct: ' %', wind_speed_kmh: ' km/h' };

// ── per-layer evidence extraction (only keys the backend actually emits) ───
function layerEvidence(key: LayerKey, d: any): { rows: [string, string][]; notes: string[] } {
  const rows: [string, string][] = [];
  const notes: string[] = [];
  if (!d || typeof d !== 'object') return { rows, notes };

  if (key === 'physics') {
    if (Array.isArray(d.channels_evaluated)) rows.push(['Channels checked', d.channels_evaluated.map((c: string) => CH[c] || c).join(', ') || 'none']);
    const ev = d.evidence || {};
    Object.entries(ev).forEach(([k, v]) => {
      if (k === 'note') notes.push(String(v));
      else if (isNum(v) || typeof v === 'string') rows.push([human(k), isNum(v) ? f(v, 2) : String(v)]);
    });
  }

  if (key === 'temporal') {
    if (isNum(d.history_points)) rows.push(['History points', String(d.history_points)]);
    const spikes: [string, any, string][] = [['Temperature step', d.temp_spike, ' °C'], ['Pressure step', d.press_spike, ' hPa']];
    spikes.forEach(([label, s, u]) => {
      if (!s) return;
      const delta = s.delta_c ?? s.delta_hpa;
      rows.push([label, `${signed(delta, 1, u)} in ${s.interval_s}s${isNum(s.max_allowed_c) ? ` (max ${f(s.max_allowed_c, 1, u)})` : ''}`]);
    });
    (['frozen_temp', 'frozen_press', 'frozen_rh'] as const).forEach((k) => {
      const z = d[k];
      if (z) rows.push([`Stuck ${k === 'frozen_temp' ? 'temperature' : k === 'frozen_press' ? 'pressure' : 'humidity'}`, `${f(z.stuck_value, 2)} for ${z.window_size} readings${isNum(z.span_minutes) ? ` (${z.span_minutes} min)` : ''}`]);
    });
    Object.keys(d).filter((k) => k.startsWith('zscore_')).forEach((k) => {
      const z = d[k];
      const ch = k.replace('zscore_', '');
      rows.push([`${CH[ch] || ch} robust z`, `${f(z.modified_z, 1)} (value ${f(z.current, 2)} vs median ${f(z.median, 2)})`]);
    });
    const l = d.lstm;
    if (l) {
      if (l.lstm_available) {
        rows.push(['LSTM forecast', 'active']);
        [['temperature', 'temperature_residual', ' °C'], ['pressure', 'pressure_residual', ' hPa'], ['humidity', 'humidity_residual', ' %']].forEach(([n, r, u]) => {
          if (isNum(l[r])) rows.push([`LSTM ${n} residual`, signed(l[r], 2, u)]);
        });
      } else {
        rows.push(['LSTM forecast', 'not run']);
        if (l.lstm_skip_reason) notes.push(`LSTM not run: ${human(l.lstm_skip_reason)}${isNum(d.lstm_history_points) && isNum(d.lstm_required_history_points) ? ` (${d.lstm_history_points}/${d.lstm_required_history_points} history points)` : ''}.`);
      }
    }
  }

  if (key === 'multivariate') {
    if (d.method_executed || d.method) rows.push(['Method', String(d.method_executed || d.method)]);
    if (isNum(d.valid_channel_count)) rows.push(['Valid channels', String(d.valid_channel_count)]);
    const det = d.detectors || {};
    Object.entries(det).forEach(([name, v]: [string, any]) => {
      if (!v) return;
      rows.push([name === 'isolation_forest' ? 'Isolation Forest' : name.toUpperCase(), v.executed ? `score ${f(v.evidence_score, 2)}${isNum(v.threshold) ? ` / threshold ${f(v.threshold, 2)}` : ''}` : 'not run']);
      if (!v.executed && v.skip_reason && !notes.includes(v.skip_reason)) notes.push(`${name === 'isolation_forest' ? 'Isolation Forest' : name.toUpperCase()} not run: ${v.skip_reason}`);
    });
    Object.entries(d.rules || {}).forEach(([name, v]: [string, any]) => {
      rows.push([human(name), v?.executed ? (v.triggered ? `triggered (${f(v.score, 2)})` : 'passed') : 'not run']);
    });
    if (d.baseline_scope) rows.push(['Baseline', `${human(d.baseline_scope)}${d.baseline_city ? ` · ${d.baseline_city}` : ''}`]);
    if (d.score_driver) rows.push(['Score driver', human(d.score_driver)]);
  }

  if (key === 'spatial') {
    if (isNum(d.neighbor_count)) rows.push(['Neighbours used', `${d.neighbor_count}${isNum(d.min_distance_km) ? ` (${f(d.min_distance_km, 0)}–${f(d.max_distance_km, 0)} km)` : ''}`]);
    Object.entries(d.channel_results || {}).forEach(([ch, r]: [string, any]) => {
      if (!r || !isNum(r.consensus_value)) return;
      rows.push([`${CH[ch] || ch} vs consensus`, `${f(r.target_value, 1)} vs ${f(r.consensus_value, 1)}${UNIT[ch] || ''} (${f(r.z_score, 1)}σ)`]);
    });
    const a = d.regional_attribution;
    if (a?.classification) {
      rows.push(['Regional attribution', human(a.classification)]);
      if (a.explanation) notes.push(a.explanation);
    }
    if (d.counterfactual_verification?.overall_status) rows.push(['Neighbour counter-check', human(d.counterfactual_verification.overall_status)]);
  }

  if (key === 'sensor_health') {
    Object.entries(d.channel_drift || {}).forEach(([ch, c]: [string, any]) => {
      const ref = c.reference_mode === 'SPATIAL' ? 'vs neighbours' : c.reference_mode === 'BACKGROUND' ? 'vs NWP' : c.reference_mode === 'SUSPENDED_SATURATION' ? 'suspended (saturation)' : 'own history';
      rows.push([`${CH[ch] || ch} drift`, `${human(c.drift_tier)} · bias ${signed(c.estimated_bias, 2)} ${ref}${c.mann_kendall?.significant ? ` · MK τ ${f(c.mann_kendall.tau, 2)}` : ''}`]);
    });
    if (isNum(d.health_score)) rows.push(['Sensor health index', `${f(d.health_score, 0)} / 100`]);
    if (d.note_non_physical_source) notes.push(d.note_non_physical_source);
  }
  return { rows, notes };
}

function layerStage(key: LayerKey, card: any, availability: EvidenceAvailability | undefined): Stage {
  const meta = LAYER_META[key];
  const ev: LayerEvidence = deriveLayerEvidence(key, card, availability);
  const { rows, notes } = layerEvidence(key, card?.details);
  const tone: StageTone = !ev.assessed ? 'unassessed' : ev.state === 'ANOMALY' ? 'triggered' : ev.state === 'WARNING' ? 'warning' : 'pass';
  const state = !ev.assessed
    ? (ev.state === 'NOT_APPLICABLE' ? 'Not applicable' : ev.state === 'UNAVAILABLE' ? 'Unavailable' : 'Not evaluated')
    : ev.state === 'ANOMALY' ? (String(card?.status).toUpperCase() === 'VETO' ? 'Anomalous (veto)' : 'Anomalous') : ev.state === 'WARNING' ? 'Warning' : 'Nominal';
  // A 0.00 evidence score from an assessed layer means "evaluated, found no
  // anomalous evidence" — say that, and keep the number in the details.
  const noEvidence = ev.assessed && tone === 'pass' && (ev.score === null || ev.score === 0);
  const contribution = !ev.assessed
    ? 'excluded from fusion'
    : noEvidence ? 'No anomalous evidence'
    : `evidence score ${ev.score !== null ? ev.score.toFixed(2) : '—'}${tone === 'triggered' || tone === 'warning' ? ' · supports anomaly' : ''}`;
  if (ev.assessed && ev.score !== null) rows.unshift(['Evidence score', `${ev.score.toFixed(2)}${noEvidence ? ' (evaluated — no anomalous evidence)' : ''}`]);
  if (card?.evidence_quality && ev.assessed) rows.unshift(['Evidence quality', human(card.evidence_quality)]);
  return { n: meta.n, key, name: meta.name, checks: meta.checks, tone, state, finding: ev.reason || '—', evidence: rows, contribution, notes };
}

// ── common input shape ───────────────────────────────────────────────────
interface Input {
  layers: Partial<Record<LayerKey, any>>;
  availability?: EvidenceAvailability;
  dataQuality?: any;
  freshness?: string;
  source?: string;
  flags?: string[];
  fusion: { status: string; confidence: number | null; pValue?: number | null; nonconformity?: number | null; meaningful?: number | null; agreement?: number | null; veto?: boolean; score?: number | null; sufficiency?: number | null; threshold?: number | null };
  overall?: string;
  severity?: string;
  watch?: boolean;
  diagnosis: { rootCause: string; label?: string; confidence?: string; primary?: string; alternatives?: string[]; affected?: string[] };
  interpretation?: string;
  actionLabel?: string;
  actionDetail?: string;
  summary?: string;
  incidentId?: string | null;
  isSimulated?: boolean;
  isNwp?: boolean;
}

const INTERP: Record<string, string> = {
  nominal: 'No fault indicated',
  likely_sensor_fault: 'Likely sensor fault',
  likely_weather_event: 'Likely genuine weather event — not a sensor fault',
  communication_issue: 'Communication issue',
  uncertain: 'Uncertain — evidence not conclusive',
};

function build(inp: Input): PipelineModel {
  // 1 — data quality
  const dq = inp.dataQuality || {};
  const missing: string[] = [...(dq.missing_fields || []), ...(dq.zero_substituted_fields || [])];
  const dqTone: StageTone = !dq.status ? 'unassessed' : dq.status === 'VALID' && !missing.length ? 'pass' : dq.status === 'INSUFFICIENT_DATA' ? 'triggered' : 'warning';
  const dqRows: [string, string][] = [];
  if (inp.source) dqRows.push(['Source', inp.isSimulated ? 'Simulated AWS feed' : inp.source === 'AWS_IN_SITU' ? 'Measured (AWS in-situ)' : human(inp.source)]);
  if (inp.freshness) dqRows.push(['Freshness', human(inp.freshness)]);
  if (dq.valid_fields) dqRows.push(['Valid channels', dq.valid_fields.map((c: string) => CH[c] || c).join(', ') || 'none']);
  if (missing.length) dqRows.push(['Missing / invalid', missing.map((c) => CH[c] || c).join(', ')]);
  if (isNum(dq.historical_points)) dqRows.push(['History available', `${dq.historical_points} points`]);
  if (isNum(dq.nearby_stations)) dqRows.push(['Neighbours in range', String(dq.nearby_stations)]);
  (inp.flags || []).forEach((fl) => dqRows.push(['Quality flag', human(fl)]));
  const dqStage: Stage = {
    n: 1, key: 'data_quality', name: 'Data quality', checks: 'Is the input usable? Channel validity, missing values, freshness, provenance',
    tone: dqTone, state: dq.status ? human(dq.status) : 'Not reported',
    finding: dq.status === 'VALID' && !missing.length ? 'All core channels valid.' : (dq.limitations || []).join('; ') || (missing.length ? `Missing: ${missing.map((c) => CH[c] || c).join(', ')}` : 'Not reported by the backend.'),
    evidence: dqRows, contribution: missing.length ? 'limits which layers can assess' : 'input accepted', notes: [],
  };
  if (inp.isNwp) dqStage.notes.push('The value is an NWP model reference, not a physical sensor reading — hardware-fault diagnoses are not applicable.');

  // 2–6 — independent layers
  const layers = LAYER_KEYS.map((k) => layerStage(k, inp.layers[k], inp.availability));
  const assessed = layers.filter((s) => s.tone !== 'unassessed');
  const supporting = layers.filter((s) => s.tone === 'triggered' || s.tone === 'warning');

  // 7 — fusion
  const fu = inp.fusion;
  const fuRows: [string, string][] = [['Method', 'Conformal p-value fusion of layer evidence']];
  fuRows.push(['Layers that assessed', `${assessed.length} of 5`]);
  fuRows.push(['Layers supporting an anomaly', supporting.length ? supporting.map((s) => s.name).join(', ') : 'none']);
  if (isNum(fu.score)) fuRows.push(['Fused anomaly score', f(fu.score, 2)]);
  if (isNum(fu.threshold)) fuRows.push(['Decision threshold', f(fu.threshold, 2)]);
  if (isNum(fu.pValue)) fuRows.push(['Conformal p-value', f(fu.pValue, 3)]);
  if (isNum(fu.nonconformity)) fuRows.push(['Nonconformity', f(fu.nonconformity, 3)]);
  if (isNum(fu.agreement)) fuRows.push(['Layer agreement', f(fu.agreement, 2)]);
  if (isNum(fu.sufficiency)) fuRows.push(['Evidence sufficiency', f(fu.sufficiency, 2)]);
  if (fu.veto) fuRows.push(['Physics veto', 'yes — overrides statistical fusion']);
  const fusion: Stage = {
    n: 7, key: 'fusion', name: 'Evidence fusion', checks: 'Combines independent layer evidence into one calibrated decision',
    tone: fu.veto || fu.status === 'ANOMALY' ? 'triggered' : fu.status === 'WARNING' ? 'warning' : 'pass',
    state: fu.status === 'ANOMALY' || fu.veto ? 'anomalous' : human(fu.status) || '—',
    finding: fu.veto
      ? 'A physical impossibility (L1 veto) decides the outcome regardless of other layers.'
      : supporting.length
        ? `${supporting.length} of ${assessed.length} assessed layer(s) contributed evidence.`
        : assessed.length ? `No assessed layer reported anomalous evidence (${assessed.length} of 5 assessed).` : 'No layer could assess this observation.',
    evidence: fuRows, contribution: isNum(fu.confidence) ? `confidence ${(fu.confidence * 100).toFixed(0)}%*` : 'confidence not reported', notes: [CONFIDENCE_NOTE],
  };

  // 8 — decision
  const overall = inp.overall;
  // Decision vocabulary: NOMINAL · WARNING · CRITICAL · DEGRADED (same as the network counts).
  const DECISION_LABEL: Record<string, string> = { nominal: 'nominal', suspect: 'warning', anomaly: 'critical', degraded: 'degraded' };
  const decisionState = overall ? (DECISION_LABEL[overall] || human(overall)) : human(fu.status);
  const decRows: [string, string][] = [['Sensor-trust status', decisionState || '—'], ['Engine status', human(fu.status) || '—']];
  if (inp.severity && inp.severity !== 'NONE') decRows.push(['Severity', human(inp.severity)]);
  const decision: Stage = {
    n: 8, key: 'decision', name: 'Anomaly decision', checks: 'Final state of this observation, after alarm hysteresis',
    tone: 'decision', state: decisionState || '—',
    finding: inp.watch
      ? 'Single undiagnosed excursion — held as WATCH for one observation before raising (alarm hysteresis).'
      : overall === 'anomaly' ? 'Anomaly confirmed.' : overall === 'suspect' ? 'Warning — evidence present but not conclusive.' : overall === 'degraded' ? 'Data degraded — station trusted with limitations.' : 'No anomaly.',
    evidence: decRows, contribution: overall === 'anomaly' || overall === 'suspect' ? 'drives root-cause analysis' : '—', notes: [],
  };

  // 9 — root cause
  const dg = inp.diagnosis;
  const rcRows: [string, string][] = [['Root cause', human(dg.rootCause) || '—']];
  if (dg.confidence) rcRows.push(['Diagnosis confidence', human(dg.confidence)]);
  if (dg.affected?.length) rcRows.push(['Affected channels', dg.affected.map((c) => CH[c] || c).join(', ')]);
  (dg.alternatives || []).forEach((a, i) => rcRows.push([i === 0 ? 'Alternatives considered' : '', a]));
  const noFault = !dg.rootCause || dg.rootCause === 'NORMAL';
  const rootCause: Stage = {
    n: 9, key: 'root_cause', name: 'Root cause', checks: 'What best explains the behaviour — sensor fault, weather, communications, or unknown',
    tone: noFault ? 'pass' : inp.interpretation === 'likely_weather_event' ? 'neutral' : 'triggered',
    state: noFault ? 'none' : (dg.label || human(dg.rootCause)),
    finding: noFault ? 'No fault signature.' : dg.primary || '—',
    evidence: rcRows, contribution: '', notes: [],
  };

  // 10 — operational insight
  let finding = inp.interpretation ? INTERP[inp.interpretation] || human(inp.interpretation) : '—';
  const insRows: [string, string][] = [];
  if (inp.actionLabel) insRows.push(['Recommended action', inp.actionLabel]);
  if (inp.incidentId) insRows.push(['Investigation', inp.incidentId]);
  const insNotes: string[] = [];
  if (inp.actionDetail) insNotes.push(inp.actionDetail);
  if (noFault && (overall === 'nominal' || !overall)) {
    const s = summarizeEvidence({ layers: inp.layers as any, availability: inp.availability, backendStatus: fu.status, diagnosisPrimary: dg.rootCause, isInSitu: !inp.isNwp });
    const di = buildNormalStatusInsight(s, inp.actionDetail, !!inp.isNwp);
    finding = di.what;
    insNotes.splice(0, insNotes.length, di.why, di.action);
  }
  const insight: Stage = {
    n: 10, key: 'insight', name: 'Operational insight', checks: 'What this means for operations and what to do next',
    tone: inp.interpretation === 'likely_sensor_fault' || inp.interpretation === 'communication_issue' ? 'triggered' : 'pass',
    state: inp.actionLabel || '—', finding, evidence: insRows, contribution: '', notes: insNotes.filter(Boolean),
  };

  const tone = inp.interpretation === 'likely_weather_event' ? 'weather' : ((overall || 'nominal') as any);
  return {
    phases: [
      { id: 'OBSERVE', question: 'Is the input usable?', stages: [dqStage] },
      { id: 'DETECT', question: 'Independent evidence — each layer looks for a different kind of problem', stages: layers },
      { id: 'FUSE', question: 'Evidence combined into one decision', stages: [fusion, decision] },
      { id: 'EXPLAIN', question: 'What best explains it', stages: [rootCause] },
      { id: 'ACT', question: 'What it means operationally', stages: [insight] },
    ],
    headline: { status: decisionState, tone, confidence: isNum(fu.confidence) ? fu.confidence : null, summary: inp.summary || '' },
  };
}

// ── adapters ─────────────────────────────────────────────────────────────
/** From GET /api/stations/{id}/anomaly (+ optional live health for sensor-trust status). */
export function fromAssessment(a: any, live?: any, action?: { label?: string; detail?: string }): PipelineModel {
  const overall = a?.overall || {};
  const src = a?.observation?.source;
  return build({
    layers: a?.layers || {},
    availability: a?.evidence_availability,
    dataQuality: a?.data_quality,
    freshness: a?.observation?.freshness,
    source: src,
    isSimulated: src === 'SIMULATED_AWS',
    isNwp: src === 'NWP_MODEL_REFERENCE',
    fusion: {
      status: String(a?.status || overall.status || ''),
      confidence: isNum(overall.confidence) ? overall.confidence : isNum(a?.confidence) ? a.confidence : null,
      score: isNum(overall.score) ? overall.score : null,
      threshold: isNum(overall.threshold) ? overall.threshold : null,
      sufficiency: isNum(overall.evidence_sufficiency) ? overall.evidence_sufficiency : null,
      veto: !!a?.veto_fired,
    },
    overall: live?.overall_status,
    severity: overall.severity,
    watch: live?.watch,
    diagnosis: {
      rootCause: a?.diagnosis?.primary || a?.root_cause || '',
      confidence: a?.diagnosis?.confidence,
      primary: (a?.diagnosis?.evidence || []).join('; ') || undefined,
      alternatives: a?.diagnosis?.alternatives || [],
      affected: a?.diagnosis?.affected_channels || a?.affected_channels || [],
      label: live?.rca_label,
    },
    interpretation: live?.interpretation,
    actionLabel: action?.label,
    actionDetail: action?.detail || a?.diagnosis?.operator_action || a?.operator_action,
    summary: live?.summary || a?.explanation,
    incidentId: live?.active_incident_id,
  });
}

/** From a stored DetectionResult (GET /api/detections/{id}, stations/{id}/live latest_detection). */
export function fromDetection(det: any): PipelineModel {
  const lr = det?.layer_results || {};
  const byKey: Partial<Record<LayerKey, any>> = {};
  ['L1', 'L2', 'L3', 'L4', 'L5'].forEach((c, i) => { byKey[LAYER_KEYS[i]] = lr[c]; });
  const fu = lr.fusion || {};
  const prov = det?.provenance || {};
  return build({
    layers: byKey,
    dataQuality: det?.data_quality,
    freshness: prov.freshness,
    source: prov.data_source,
    flags: prov.quality_flags,
    isSimulated: !!prov.simulated,
    isNwp: prov.data_source === 'NWP_MODEL_REFERENCE',
    fusion: {
      status: String(det?.engine_status || fu.status || ''),
      confidence: isNum(det?.confidence) ? det.confidence : null,
      pValue: fu.p_value, nonconformity: fu.nonconformity_score, meaningful: fu.meaningful_layer_count,
      agreement: fu.agreement_factor, veto: !!fu.veto, score: isNum(det?.anomaly_score) ? det.anomaly_score : null,
    },
    overall: det?.overall_status,
    severity: det?.severity,
    watch: det?.watch,
    diagnosis: {
      rootCause: det?.diagnosis?.root_cause || '', label: det?.diagnosis?.rca_label, confidence: det?.diagnosis?.confidence,
      primary: det?.diagnosis?.primary_signal, alternatives: det?.diagnosis?.alternatives || [], affected: det?.diagnosis?.affected_channels || [],
    },
    interpretation: det?.interpretation,
    actionLabel: det?.recommended_action?.label,
    actionDetail: det?.recommended_action?.detail,
    summary: det?.summary,
    incidentId: det?.incident_id,
  });
}
