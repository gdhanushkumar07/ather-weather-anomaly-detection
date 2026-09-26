import React from 'react';
import {
  EvidenceAvailabilityEntry,
  TemporalChannel,
  TemporalDetails,
  TemporalLayerCard,
  TemporalLSTMDetails
} from '../types/weather';

// The backend does not return this number as a field (it only states it in
// `details.note` / `reason`); it mirrors _MIN_HISTORY_FOR_TEMPORAL in
// backend/engine/layer2_temporal.py and is used only for explanatory text.
// Everything else on this card comes from the API response.
const MIN_HISTORY_FOR_BASIC_TEMPORAL = 3;

export interface TemporalObservedValues {
  temperature_c: number | null | undefined;
  pressure_hpa: number | null | undefined;
  humidity_pct: number | null | undefined;
}

interface TemporalEvidenceProps {
  layer: TemporalLayerCard;
  /** evidence_availability.temporal from the API, when present. */
  availability?: EvidenceAvailabilityEntry;
  /** Current station observation (from the same API response) — the LSTM
   *  block does not echo the observed value, so it is taken from here. */
  observed: TemporalObservedValues;
  /** data_quality.historical_points from the API, used only when the
   *  temporal block itself does not report history_points. */
  dataQualityHistoricalPoints?: number | null;
}

const SKIP_REASON_TEXT: Record<string, string> = {
  insufficient_valid_history: 'Not enough valid, contiguous observations yet',
  current_observation_incomplete: 'The current observation is missing a channel the LSTM needs',
  inference_error: 'The LSTM failed while running on this reading',
  lstm_unavailable: 'The LSTM model is not loaded on the backend'
};

const CHANNELS: {
  key: TemporalChannel;
  label: string;
  short: string;
  unit: string;
  digits: number;
  predicted: keyof TemporalLSTMDetails;
  residual: keyof TemporalLSTMDetails;
  score: keyof TemporalLSTMDetails;
}[] = [
  { key: 'temperature_c', label: 'Temperature', short: 'T', unit: '°C', digits: 1, predicted: 'lstm_predicted_temperature_c', residual: 'temperature_residual', score: 'temperature_lstm_score' },
  { key: 'pressure_hpa', label: 'Pressure', short: 'P', unit: 'hPa', digits: 1, predicted: 'lstm_predicted_pressure_hpa', residual: 'pressure_residual', score: 'pressure_lstm_score' },
  { key: 'humidity_pct', label: 'Humidity', short: 'RH', unit: '%', digits: 1, predicted: 'lstm_predicted_humidity_pct', residual: 'humidity_residual', score: 'humidity_lstm_score' }
];

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** null/undefined render as an em dash — never as 0. */
const fmt = (v: number | null | undefined, digits: number, unit = ''): string =>
  isNum(v) ? `${v.toFixed(digits)}${unit ? ` ${unit}` : ''}` : '—';

const fmtSigned = (v: number | null | undefined, digits: number, unit = ''): string =>
  isNum(v) ? `${v > 0 ? '+' : ''}${v.toFixed(digits)}${unit ? ` ${unit}` : ''}` : '—';

const fmtScore = (v: number | null | undefined): string => (isNum(v) ? v.toFixed(2) : '—');

const humanize = (code: string): string => code.replace(/_/g, ' ');

export const TemporalEvidence: React.FC<TemporalEvidenceProps> = ({
  layer,
  availability,
  observed,
  dataQualityHistoricalPoints
}) => {
  const details: TemporalDetails = layer.details || {};
  const lstm = details.lstm;
  const status = String(layer.status || '').toUpperCase();

  // Unavailable = the backend could not assess this observation. Either
  // signal counts; a missing availability block falls back to the card status.
  const unavailable =
    availability?.available === false || status === 'INSUFFICIENT_DATA' || status === 'UNAVAILABLE';
  const unavailableReason = availability?.reason || layer.reason;

  const historyPoints: number | null = isNum(details.history_points)
    ? details.history_points
    : isNum(dataQualityHistoricalPoints)
      ? dataQualityHistoricalPoints
      : null;

  const lstmHistory = isNum(details.lstm_history_points) ? details.lstm_history_points : null;
  const lstmRequired = isNum(details.lstm_required_history_points) ? details.lstm_required_history_points : null;
  const lstmActive = lstm?.lstm_available === true;
  const lstmProgress =
    lstmHistory !== null && lstmRequired ? Math.min(100, Math.round((lstmHistory / lstmRequired) * 100)) : 0;
  const isWarmup = !lstmActive && lstmHistory !== null && lstmHistory > 1;

  const skipReason = lstm?.lstm_skip_reason || null;

  const ruleItems: { key: string; title: string; verdict: string; lines: string[] }[] = [];
  if (details.temp_spike) {
    const r = details.temp_spike;
    ruleItems.push({
      key: 'temp_spike',
      title: 'Temperature spike',
      verdict: 'Detected',
      lines: [
        `${fmt(r.previous, 1, '°C')} → ${fmt(r.current, 1, '°C')} (Δ ${fmt(r.delta_c, 1, '°C')} in ${r.interval_s}s)`,
        ...(isNum(r.max_allowed_c) ? [`Maximum expected change: ${fmt(r.max_allowed_c, 1, '°C')}`] : []),
        `Evidence score: ${fmtScore(r.score)}`
      ]
    });
  }
  if (details.press_spike) {
    const r = details.press_spike;
    ruleItems.push({
      key: 'press_spike',
      title: 'Pressure spike',
      verdict: 'Detected',
      lines: [
        `${fmt(r.previous, 1, 'hPa')} → ${fmt(r.current, 1, 'hPa')} (Δ ${fmt(r.delta_hpa, 1, 'hPa')} in ${r.interval_s}s)`,
        `Evidence score: ${fmtScore(r.score)}`
      ]
    });
  }
  if (details.frozen_temp) {
    const r = details.frozen_temp;
    ruleItems.push({
      key: 'frozen_temp',
      title: 'Frozen temperature sensor',
      verdict: 'Detected',
      lines: [
        `Constant ${fmt(r.stuck_value, 2, '°C')} across ${r.window_size} consecutive readings (range ${fmt(r.variance, 3)})`,
        `Evidence score: ${fmtScore(r.score)}`
      ]
    });
  }
  const zEntries: [string, string, string, number, keyof TemporalDetails][] = [
    ['zscore_temperature_c', 'Temperature statistical outlier', '°C', 2, 'zscore_temperature_c'],
    ['zscore_pressure_hpa', 'Pressure statistical outlier', 'hPa', 2, 'zscore_pressure_hpa'],
    ['zscore_humidity_pct', 'Humidity statistical outlier', '%', 2, 'zscore_humidity_pct']
  ];
  zEntries.forEach(([key, title, unit, digits, field]) => {
    const r = details[field] as TemporalDetails['zscore_temperature_c'];
    if (!r) return;
    ruleItems.push({
      key,
      title,
      verdict: 'Detected',
      lines: [
        `Current ${fmt(r.current, digits, unit)} vs rolling median ${fmt(r.median, digits, unit)} (modified Z ${fmt(r.modified_z, 1)}, ${r.sample_count} samples)`,
        `Evidence score: ${fmtScore(r.score)}`
      ]
    });
  });

  const stateClass = unavailable ? 'insufficient_data' : status.toLowerCase();

  return (
    <div className="temporal-evidence">
      {/* ── Status banner ───────────────────────────────────────────── */}
      <div className={`temporal-banner ${stateClass}`}>
        <div className="temporal-banner-top">
          <span className="temporal-banner-title">TEMPORAL INTELLIGENCE</span>
          <span className={`layer-status-pill ${stateClass}`}>
            ● {unavailable ? 'INSUFFICIENT DATA' : status || 'UNKNOWN'}
          </span>
        </div>

        {unavailable ? (
          <>
            <p className="temporal-banner-text">Temporal analysis is waiting for sufficient observation history.</p>
            <p className="temporal-banner-sub">
              This is not a normal score of zero, and it is not an anomaly — no temporal assessment has been made yet.
            </p>
            {unavailableReason && <p className="temporal-banner-sub temporal-backend-note">{unavailableReason}</p>}
          </>
        ) : (
          <p className="temporal-banner-sub">
            Temporal evidence score:{' '}
            <strong className="temporal-mono">{isNum(layer.score) ? layer.score.toFixed(2) : '—'}</strong> (0–1,
            anomaly evidence — not a probability)
            {layer.evidence_quality ? <> · Evidence quality: {humanize(layer.evidence_quality)}</> : null}
          </p>
        )}
      </div>

      {/* ── Observation history ─────────────────────────────────────── */}
      <div className="temporal-block">
        <div className="temporal-block-title">OBSERVATION HISTORY</div>
        <div className="temporal-kv">
          <span>Valid observations recorded</span>
          <strong className="temporal-mono">{historyPoints !== null ? historyPoints : 'Not reported'}</strong>
        </div>
        <div className="temporal-hint">
          Basic temporal checks (rate of change, frozen value, statistical outlier) need at least{' '}
          {MIN_HISTORY_FOR_BASIC_TEMPORAL} valid observations.
        </div>
        {details.historical_points && (
          <div className="temporal-kv temporal-kv-channels">
            <span>Per channel</span>
            <strong className="temporal-mono">
              {CHANNELS.map((c) =>
                isNum(details.historical_points?.[c.key])
                  ? `${c.short} ${details.historical_points![c.key]}`
                  : null
              )
                .filter(Boolean)
                .join(' · ')}
            </strong>
          </div>
        )}
      </div>

      {/* ── LSTM ────────────────────────────────────────────────────── */}
      {!lstm ? (
        <div className="temporal-block">
          <div className="temporal-block-title">LSTM PREDICTION EVIDENCE</div>
          <div className="temporal-hint">The backend did not report LSTM status for this evaluation.</div>
        </div>
      ) : !lstmActive ? (
        <div className="temporal-block">
          <div className="temporal-block-title">
            {isWarmup ? 'LSTM WARM-UP' : 'LSTM NOT ACTIVE'}
            <span className="temporal-inactive-tag">INACTIVE</span>
          </div>
          {lstmHistory !== null && lstmRequired !== null && (
            <>
              <div className="temporal-kv">
                <span>LSTM warm-up</span>
                <strong className="temporal-mono">
                  {lstmHistory} / {lstmRequired} valid observations
                </strong>
              </div>
              <div
                className="temporal-progress-track"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={lstmRequired}
                aria-valuenow={lstmHistory}
              >
                <div className="temporal-progress-fill" style={{ width: `${lstmProgress}%` }} />
              </div>
            </>
          )}
          <div className="temporal-hint">
            The LSTM needs {lstmRequired !== null ? lstmRequired : 'a full window of'} valid contiguous observations
            before it can predict. It is not making predictions yet, so no predicted values or residuals are shown.
          </div>
          {skipReason && (
            <div className="temporal-kv">
              <span>Reason</span>
              <strong>
                {SKIP_REASON_TEXT[skipReason] || humanize(skipReason)}{' '}
                <span className="temporal-mono temporal-raw-code">({skipReason})</span>
              </strong>
            </div>
          )}
        </div>
      ) : (
        <div className="temporal-block">
          <div className="temporal-block-title">
            LSTM PREDICTION
            <span className="temporal-active-tag">ACTIVE</span>
          </div>
          <div className="temporal-lstm-table" role="table">
            <div className="temporal-lstm-row head" role="row">
              <span>Channel</span>
              <span>Observed</span>
              <span>Predicted</span>
              <span>Residual</span>
              <span>Evidence score</span>
            </div>
            {CHANNELS.map((c) => (
              <div className="temporal-lstm-row" role="row" key={c.key}>
                <span>{c.label}</span>
                <span className="temporal-mono">{fmt(observed[c.key], c.digits, c.unit)}</span>
                <span className="temporal-mono">{fmt(lstm[c.predicted] as number | null | undefined, c.digits, c.unit)}</span>
                <span className="temporal-mono">{fmtSigned(lstm[c.residual] as number | null | undefined, c.digits, c.unit)}</span>
                <span className="temporal-mono">{fmtScore(lstm[c.score] as number | null | undefined)}</span>
              </div>
            ))}
          </div>
          <div className="temporal-kv">
            <span>LSTM residual score</span>
            <strong className="temporal-mono">{fmtScore(lstm.lstm_residual_score)}</strong>
          </div>
          <div className="temporal-kv">
            <span>Recent LSTM peak</span>
            <strong className="temporal-mono">
              {fmtScore(lstm.recent_lstm_peak)}
              {lstm.recent_lstm_peak_by_channel
                ? ` (${CHANNELS.filter((c) => isNum(lstm.recent_lstm_peak_by_channel?.[c.key]))
                    .map((c) => `${c.short} ${fmtScore(lstm.recent_lstm_peak_by_channel?.[c.key])}`)
                    .join(' · ')})`
                : ''}
            </strong>
          </div>
          <div className="temporal-hint">
            Scores are anomaly-evidence values from 0 to 1 — they are not probabilities or confidence percentages.
          </div>
          {lstm.note && <div className="temporal-hint temporal-backend-note">{lstm.note}</div>}
        </div>
      )}

      {/* ── Rule-based evidence: only rules that actually triggered ─── */}
      {ruleItems.length > 0 && (
        <div className="temporal-block">
          <div className="temporal-block-title">RULE EVIDENCE</div>
          {ruleItems.map((r) => (
            <div className="temporal-rule" key={r.key}>
              <div className="temporal-rule-head">
                <span>{r.title}</span>
                <span className="temporal-rule-verdict">{r.verdict}</span>
              </div>
              {r.lines.map((l, i) => (
                <div className="temporal-hint" key={i}>{l}</div>
              ))}
            </div>
          ))}
        </div>
      )}

      {/* Backend's own one-line reason, verbatim (already reported above
          for the unavailable state, so not repeated there). */}
      {!unavailable && layer.reason && (
        <div className="layer-reason-text">
          <span className="layer-reason-lbl">Reason: </span>
          {layer.reason}
        </div>
      )}
    </div>
  );
};
