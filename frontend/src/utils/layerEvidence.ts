import { CanonicalLayerCard, EvidenceAvailability, EvidenceAvailabilityEntry } from '../types/weather';

/**
 * Evidence-aware view of the 5 ATHER layers, derived ONLY from the backend
 * response (layers.* cards + evidence_availability). The rule it enforces:
 *
 *     insufficient / unavailable / not applicable  !=  normal
 *
 * A layer that could not assess the observation is never counted as a PASS,
 * and a 0 score from such a layer is treated as "no assessment", not "0% risk".
 */

export type LayerKey = 'physics' | 'temporal' | 'multivariate' | 'spatial' | 'sensor_health';

export const LAYER_KEYS: LayerKey[] = ['physics', 'temporal', 'multivariate', 'spatial', 'sensor_health'];

export const LAYER_LABELS: Record<LayerKey, string> = {
  physics: 'Physics',
  temporal: 'Temporal',
  multivariate: 'Multivariate',
  spatial: 'Spatial',
  sensor_health: 'Sensor Health'
};

export type LayerEvidenceState =
  | 'PASS'
  | 'WARNING'
  | 'ANOMALY'
  | 'INSUFFICIENT'
  | 'NOT_APPLICABLE'
  | 'UNAVAILABLE';

export interface LayerEvidence {
  key: LayerKey;
  label: string;
  state: LayerEvidenceState;
  /** Raw backend card status, e.g. 'PASS', 'INSUFFICIENT_DATA'. */
  status: string;
  /** Backend layer score; null when the layer did not assess the observation. */
  score: number | null;
  reason: string;
  /** True only when the layer actually assessed the observation. */
  assessed: boolean;
}

/** The Sensor Health entry is keyed `sensor_health`; older backends used `drift`. */
export function availabilityFor(
  availability: EvidenceAvailability | undefined,
  key: LayerKey
): EvidenceAvailabilityEntry | undefined {
  if (!availability) return undefined;
  return key === 'sensor_health' ? availability.sensor_health ?? availability.drift : availability[key];
}

export function deriveLayerEvidence(
  key: LayerKey,
  card: CanonicalLayerCard | undefined,
  availability: EvidenceAvailability | undefined
): LayerEvidence {
  const label = LAYER_LABELS[key];
  const avail = availabilityFor(availability, key);

  if (!card || typeof card !== 'object' || !('status' in card)) {
    return {
      key, label, state: 'UNAVAILABLE', status: 'UNAVAILABLE', score: null, assessed: false,
      reason: avail?.reason || 'Not reported by the backend.'
    };
  }

  const status = String(card.status || '').toUpperCase();
  const reason = card.reason || avail?.reason || '';
  const unassessed = (state: LayerEvidenceState): LayerEvidence => ({
    key, label, state, status, score: null, assessed: false, reason: reason || avail?.reason || ''
  });

  if (status === 'NOT_APPLICABLE') return unassessed('NOT_APPLICABLE');
  if (status === 'UNAVAILABLE') return unassessed('UNAVAILABLE');
  if (status === 'INSUFFICIENT_DATA' || status === 'LIMITED') return unassessed('INSUFFICIENT');
  // The card claims an assessment, but the backend's availability report says the
  // layer could not assess: trust the more conservative signal.
  if (avail?.available === false) return unassessed('INSUFFICIENT');

  const stateByStatus: Record<string, LayerEvidenceState> = {
    PASS: 'PASS', WARNING: 'WARNING', ANOMALY: 'ANOMALY', VETO: 'ANOMALY'
  };
  const state = stateByStatus[status];
  if (!state) return unassessed('UNAVAILABLE');

  return { key, label, state, status, score: typeof card.score === 'number' ? card.score : null, assessed: true, reason };
}

export type DisplayStatus =
  | 'ANOMALY'
  | 'WARNING'
  | 'NORMAL'
  | 'NO_ANOMALY_CONFIRMED'
  | 'INSUFFICIENT_EVIDENCE'
  | 'OFFLINE';

export interface EvidenceSummary {
  layers: LayerEvidence[];
  assessed: LayerEvidence[];
  notAssessed: LayerEvidence[];
  displayStatus: DisplayStatus;
  /** Operator-facing label for displayStatus. */
  label: string;
  /** One factual sentence about how many layers assessed the observation. */
  detail: string;
}

const DISPLAY_LABELS: Record<DisplayStatus, string> = {
  ANOMALY: 'ANOMALY',
  WARNING: 'WARNING',
  NORMAL: 'NORMAL',
  NO_ANOMALY_CONFIRMED: 'NO ANOMALY CONFIRMED',
  INSUFFICIENT_EVIDENCE: 'INSUFFICIENT EVIDENCE',
  OFFLINE: 'OFFLINE'
};

const stripTrailingPeriod = (t: string) => t.replace(/[.\s]+$/, '');

const joinLabels = (ls: LayerEvidence[]) => ls.map((l) => l.label).join(', ');

export function summarizeEvidence(input: {
  layers: Record<string, any> | undefined;
  availability: EvidenceAvailability | undefined;
  /** Backend overall status: NORMAL | WARNING | ANOMALY | OFFLINE. */
  backendStatus: string;
  /** diagnosis.primary from the backend, if any. */
  diagnosisPrimary?: string;
  /** True only when the observation is a verified AWS in-situ reading. */
  isInSitu: boolean;
}): EvidenceSummary {
  const layers = LAYER_KEYS.map((k) => deriveLayerEvidence(k, input.layers?.[k], input.availability));
  const assessed = layers.filter((l) => l.assessed);
  const notAssessed = layers.filter((l) => !l.assessed);

  const backendStatus = String(input.backendStatus || '').toUpperCase();
  let displayStatus: DisplayStatus;
  if (backendStatus === 'OFFLINE') displayStatus = 'OFFLINE';
  else if (backendStatus === 'ANOMALY') displayStatus = 'ANOMALY';
  else if (backendStatus === 'WARNING') displayStatus = 'WARNING';
  else if (assessed.length === 0 || input.diagnosisPrimary === 'INSUFFICIENT_EVIDENCE') displayStatus = 'INSUFFICIENT_EVIDENCE';
  // Plain NORMAL only when a measured AWS reading was assessed by every layer.
  else if (!input.isInSitu || notAssessed.length > 0) displayStatus = 'NO_ANOMALY_CONFIRMED';
  else displayStatus = 'NORMAL';

  const detail = notAssessed.length === 0
    ? `All ${layers.length} layers assessed this observation.`
    : `Assessed by ${assessed.length} of ${layers.length} layers` +
      (assessed.length ? ` (${joinLabels(assessed)})` : '') +
      `. Not assessed: ${joinLabels(notAssessed)}.`;

  return { layers, assessed, notAssessed, displayStatus, label: DISPLAY_LABELS[displayStatus], detail };
}

export interface DerivedInsight {
  what: string;
  why: string;
  evidence: string;
  action: string;
}

const STATE_WORD: Record<LayerEvidenceState, string> = {
  PASS: 'pass', WARNING: 'warning', ANOMALY: 'anomaly',
  INSUFFICIENT: 'insufficient data', NOT_APPLICABLE: 'not applicable', UNAVAILABLE: 'unavailable'
};

/**
 * Insight for a station whose backend status is NORMAL. Built from the real
 * layer states/scores/reasons instead of a canned "all layers confirm" line.
 */
export function buildNormalStatusInsight(
  summary: EvidenceSummary,
  backendAction: string | undefined,
  isNwpReference: boolean
): DerivedInsight {
  const { assessed, notAssessed, displayStatus } = summary;

  const what =
    displayStatus === 'NORMAL'
      ? 'No anomaly detected; every layer assessed this observation.'
      : displayStatus === 'INSUFFICIENT_EVIDENCE'
        ? 'Evidence is insufficient for an assessment.'
        : 'No anomaly confirmed from the available evidence.';

  const whyParts: string[] = [];
  if (assessed.length) {
    whyParts.push(`Assessed: ${assessed.map((l) => `${l.label} (${STATE_WORD[l.state]})`).join(', ')}.`);
  }
  if (notAssessed.length) {
    whyParts.push(
      `Not assessed: ${notAssessed.map((l) => `${l.label} — ${stripTrailingPeriod(l.reason) || STATE_WORD[l.state]}`).join('; ')}.`
    );
  }
  if (isNwpReference) {
    whyParts.push('The observation is an NWP model reference, not a measured sensor reading.');
  }

  const evidence = assessed.length
    ? assessed.map((l) => `${l.label}: ${l.score !== null ? l.score.toFixed(2) : 'n/a'}`).join(' · ') +
      ' (backend evidence scores, not probabilities)'
    : 'No layer produced an assessment.';

  return {
    what,
    why: whyParts.join(' '),
    evidence,
    action: backendAction || 'Continue monitoring.'
  };
}
