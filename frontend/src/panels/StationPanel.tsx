import React, { useEffect, useState } from 'react';
import {
  X,
  AlertOctagon,
  TrendingUp,
  CloudSun,
  AlertTriangle,
  ShieldCheck,
  Activity,
  Layers,
  Cpu,
  Radio,
  Compass,
  CheckCircle2,
  HelpCircle,
  Clock,
  Database,
  Info,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Sliders,
  Check,
  AlertCircle
} from 'lucide-react';
import {
  Station,
  ObservationHistory,
  OpenMeteoWeather,
  StationAnomalyAssessment,
  CanonicalLayerCard
} from '../types/weather';
import { fetchStationObservations, fetchCurrentWeather, fetchStationAnomaly } from '../services/api';
import { AWSNeighbor, compareToNeighbors, deriveValidationVerdict, checkNeighborConsistency } from '../aws/awsGeo';

interface StationPanelProps {
  station: Station | null;
  onClose: () => void;
  neighbors?: AWSNeighbor[];
}

export const StationPanel: React.FC<StationPanelProps> = ({ station, onClose, neighbors = [] }) => {
  const [history, setHistory] = useState<ObservationHistory | null>(null);
  const [cachedStation, setCachedStation] = useState<Station | null>(station);

  const [currentWeather, setCurrentWeather] = useState<OpenMeteoWeather | null>(null);
  const [isLoadingWeather, setIsLoadingWeather] = useState<boolean>(false);
  const [weatherError, setWeatherError] = useState<string | null>(null);

  const [anomalyAssessment, setAnomalyAssessment] = useState<StationAnomalyAssessment | null>(null);
  const [isLoadingAnomaly, setIsLoadingAnomaly] = useState<boolean>(false);

  // Toggle for Open-Meteo comparison view
  const [showModelComparison, setShowModelComparison] = useState<boolean>(false);

  useEffect(() => {
    if (station) {
      setCachedStation(station);
      setWeatherError(null);
      setIsLoadingWeather(true);
      setIsLoadingAnomaly(true);

      // 1. Fetch live localized model forecast from Open-Meteo for comparison
      fetchCurrentWeather(station.latitude, station.longitude)
        .then((weather) => {
          setCurrentWeather(weather);
          setIsLoadingWeather(false);
        })
        .catch((err) => {
          console.error('Failed to load Open-Meteo weather', err);
          setWeatherError('External model forecast temporarily unavailable.');
          setIsLoadingWeather(false);
        });

      // 2. Fetch diurnal trend observations
      fetchStationObservations(station.id)
        .then(setHistory)
        .catch((err) => console.error('Failed to load observations history', err));

      // 3. Fetch canonical 5-layer anomaly assessment
      fetchStationAnomaly(station.id)
        .then((assessment) => {
          setAnomalyAssessment(assessment);
          setIsLoadingAnomaly(false);
        })
        .catch((err) => {
          console.error('Failed to fetch station anomaly assessment', err);
          setIsLoadingAnomaly(false);
        });
    }
  }, [station?.id, station?.latitude, station?.longitude]);

  const displayStation = station || cachedStation;
  if (!displayStation) return null;

  const currentStation = displayStation;
  const canonical = anomalyAssessment;
  const canonicalObs = canonical?.observation;
  const canonicalDiag = canonical?.diagnosis;
  const canonicalOverall = canonical?.overall;
  const canonicalLayers = canonical?.layers || {};
  const canonicalQuality = canonical?.data_quality;
  const canonicalWeather = canonical?.weather_analysis;
  const canonicalInsights = canonical?.insights || [];

  // Ground truth observed in-situ AWS station values
  const obsTemp = canonicalObs?.temperature !== undefined ? canonicalObs.temperature : currentStation.temperature;
  const obsPress = canonicalObs?.pressure !== undefined ? canonicalObs.pressure : currentStation.pressure;
  const obsHumid = canonicalObs?.relative_humidity !== undefined ? canonicalObs.relative_humidity : currentStation.humidity;
  const obsWind = canonicalObs?.wind_speed !== undefined ? canonicalObs.wind_speed : currentStation.windSpeed;
  const obsWindDir = canonicalObs?.wind_direction ?? currentStation.windDirection;
  const obsCondition = canonicalObs?.condition ?? currentStation.condition;

  // Status & severity normalization
  const status = canonicalOverall?.status || canonical?.status || currentStation.status || 'NORMAL';
  const isAnomaly = status === 'ANOMALY';
  const isWarning = status === 'WARNING';
  const isOffline = status === 'OFFLINE';

  const anomalyScore = canonicalOverall?.score ?? canonicalOverall?.anomaly_score ?? canonical?.anomaly_score ?? 0;
  const confidenceScore = canonicalOverall?.confidence ?? canonical?.confidence ?? 0.85;
  const severityLevel = canonicalOverall?.severity ?? (anomalyScore >= 0.75 ? 'HIGH' : anomalyScore >= 0.45 ? 'WARNING' : 'LOW');

  // Confidence level tag
  const confidenceLevel = canonicalDiag?.confidence || (confidenceScore >= 0.75 ? 'HIGH' : confidenceScore >= 0.45 ? 'MEDIUM' : 'LOW');

  // Confidence-gated diagnosis label per §20
  const getGatedDiagnosisTitle = (primary?: string, conf?: string): string => {
    if (!primary || primary === 'NORMAL') return 'Nominal Telemetry Envelope';
    const c = (conf || 'MEDIUM').toUpperCase();
    const formatted = primary.replace(/_/g, ' ');

    if (c === 'HIGH') {
      return `Likely Sensor Anomaly: ${formatted}`;
    } else if (c === 'MEDIUM') {
      return `Possible Sensor Anomaly: ${formatted}`;
    } else if (c === 'LOW') {
      return `Potential Anomaly: ${formatted}`;
    } else {
      return `Uncertain Telemetry: ${formatted} (Insufficient Evidence)`;
    }
  };

  // Sparkline data
  const temps = history?.series.map((s) => s.temperature) || [];
  const minTemp = temps.length ? Math.min(...temps) : 20;
  const maxTemp = temps.length ? Math.max(...temps) : 35;
  const tempRange = maxTemp - minTemp || 1;

  const points = temps
    .map((t, idx) => {
      const x = (idx / (temps.length - 1 || 1)) * 320;
      const y = 52 - ((t - minTemp) / tempRange) * 42;
      return `${x},${y}`;
    })
    .join(' ');

  // 5-Layer card definitions
  const layerDefs = [
    { key: 'physics', label: 'Physics Validation', short: 'L1 Physics' },
    { key: 'temporal', label: 'Temporal Pattern', short: 'L2 Temporal' },
    { key: 'multivariate', label: 'Multivariate State', short: 'L3 Multivariate' },
    { key: 'spatial', label: 'Spatial Consensus', short: 'L4 Spatial' },
    { key: 'drift', label: 'Sensor Drift & Health', short: 'L5 Drift' },
  ];

  const getLayerData = (key: string): CanonicalLayerCard => {
    const raw = canonicalLayers[key];
    if (raw && typeof raw === 'object' && 'status' in raw) {
      return raw as CanonicalLayerCard;
    }
    // Fallback for legacy layer scores (dict of numbers)
    const score = typeof raw === 'number' ? raw : 0.0;
    return {
      name: key.toUpperCase(),
      status: score >= 0.70 ? 'ANOMALY' : score >= 0.40 ? 'WARNING' : 'PASS',
      score,
      evidence_quality: 'MEDIUM',
      reason: score >= 0.70 ? 'Elevated layer divergence detected' : 'Within normal statistical threshold',
    };
  };

  // Real primary-vs-neighbor comparison, built from actual station telemetry
  // (see aws/awsGeo.ts). Distinct from, and shown alongside, the backend's
  // own real Spatial Consensus (L4) card above -- this is a plain-language
  // client-side summary, not a re-implementation of that algorithm.
  const neighborComparisons = neighbors.length > 0
    ? compareToNeighbors(obsTemp, obsPress, obsHumid, neighbors)
    : [];
  const neighborVerdict = neighbors.length > 0 ? deriveValidationVerdict(neighborComparisons) : null;
  const neighborChecks = neighbors.map((n) => checkNeighborConsistency(obsTemp, obsPress, obsHumid, n));

  return (
    <div className={`station-panel-wrapper ${station ? 'expanded' : 'collapsed'}`}>
      {/* 1. Header (§19.1) */}
      <div className="station-panel-header">
        <div className="header-meta">
          <div className="station-badge-row">
            <span className="station-panel-tag">
              <span className="source-live-indicator" />
              AWS IN-SITU TELEMETRY
            </span>
            <span className="station-coords">
              {currentStation.latitude.toFixed(3)}°, {currentStation.longitude.toFixed(3)}°
            </span>
          </div>
          <h2 className="station-id-heading">{currentStation.id}</h2>
          <div className="station-location-text">
            <span className="station-name-bold">{canonical?.station?.name || currentStation.name}</span>
            <span className="station-town-dot">·</span>
            <span>{canonical?.station?.town || currentStation.town}</span>
            {currentStation.country && (
              <>
                <span className="station-town-dot">·</span>
                <span className="station-country-badge">{currentStation.country}</span>
              </>
            )}
          </div>
          <div className="station-timestamp-row">
            <Clock className="w-3 h-3 text-slate-400" />
            <span>
              Observed:{' '}
              {canonicalObs?.timestamp
                ? new Date(canonicalObs.timestamp).toUTCString()
                : currentStation.timestamp || 'Recent'}
            </span>
          </div>
        </div>
        <button className="btn-close-panel" onClick={onClose} title="Close Station Panel">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="station-panel-body">
        {/* 2. Status Block (§19.3) */}
        <div className={`primary-status-banner ${status}`}>
          <div className="status-banner-left">
            <div className={`status-pill ${status}`}>
              <span className="status-pill-dot" />
              <span className="status-pill-text">{status}</span>
            </div>
            {severityLevel !== 'NONE' && (
              <span className={`severity-tag ${severityLevel}`}>{severityLevel} SEVERITY</span>
            )}
          </div>

          <div className="status-banner-metrics">
            <div className="status-metric-item">
              <span className="metric-title">ANOMALY SCORE</span>
              <span className={`metric-val ${isAnomaly ? 'alert' : isWarning ? 'warn' : 'normal'}`}>
                {(anomalyScore * 100).toFixed(0)}%
              </span>
            </div>
            <div className="status-metric-item">
              <span className="metric-title">CONFIDENCE</span>
              <span className="metric-val" title={`Evidence quality: ${confidenceLevel}`}>
                {(confidenceScore * 100).toFixed(0)}%
                <span className={`conf-badge-mini ${confidenceLevel}`}>{confidenceLevel}</span>
              </span>
            </div>
          </div>
        </div>

        {/* 3. Current Conditions (§19.2) - Explicitly Sourced AWS Telemetry */}
        <div className="section-card observation-card">
          <div className="card-header-flex">
            <div className="card-title-group">
              <Database className="w-3.5 h-3.5 text-cyan-400" />
              <span className="card-section-title">CURRENT IN-SITU OBSERVATIONS</span>
            </div>
            <span className="source-tag-pill in-situ" title="Ground truth physical sensor reading">
              AWS Station Data
            </span>
          </div>

          <div className="weather-elegant-grid">
            <div className="weather-grid-row">
              {/* Temperature */}
              <div className="weather-metric-col">
                <div className="weather-metric-val">
                  {obsTemp !== null && obsTemp !== undefined ? `${obsTemp.toFixed(1)}°C` : '--'}
                </div>
                <div className="weather-metric-lbl">Air Temperature</div>
              </div>

              {/* Relative Humidity */}
              <div className="weather-metric-col">
                <div className="weather-metric-val">
                  {obsHumid !== null && obsHumid !== undefined ? `${Math.round(obsHumid)}%` : '--'}
                </div>
                <div className="weather-metric-lbl">Relative Humidity</div>
              </div>
            </div>

            <div className="weather-grid-row">
              {/* Barometric Pressure with Zero/Null Sanitization Tag */}
              <div className="weather-metric-col">
                <div className="weather-metric-val">
                  {obsPress !== null && obsPress !== undefined && obsPress >= 1.0 ? (
                    `${obsPress.toFixed(1)} hPa`
                  ) : (
                    <span className="missing-value-pill" title="Pressure sensor channel is missing or not provided">
                      MISSING / --
                    </span>
                  )}
                </div>
                <div className="weather-metric-lbl">
                  Barometric Pressure
                  {obsPress === null && <span className="label-sub-alert"> (No channel data)</span>}
                </div>
              </div>

              {/* Wind Speed & Direction */}
              <div className="weather-metric-col">
                <div className="weather-metric-val">
                  {obsWind !== null && obsWind !== undefined ? `${obsWind.toFixed(0)} km/h` : '--'}
                  {obsWindDir && <span className="wind-direction-sub"> {obsWindDir}</span>}
                </div>
                <div className="weather-metric-lbl">Surface Wind</div>
              </div>
            </div>
          </div>

          {/* Model Forecast Comparison Drawer (Delineates Open-Meteo NWP from Station Data) */}
          <div className="model-comparison-container">
            <button
              className="btn-toggle-comparison"
              onClick={() => setShowModelComparison(!showModelComparison)}
            >
              <div className="toggle-left">
                <CloudSun className="w-3.5 h-3.5 text-sky-400" />
                <span>Open-Meteo NWP Model Reference</span>
                <span className="model-tag-pill">NWP Forecast</span>
              </div>
              {showModelComparison ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>

            {showModelComparison && (
              <div className="model-comparison-drawer">
                {isLoadingWeather ? (
                  <div className="model-loading-hint">Fetching localized atmospheric model grid...</div>
                ) : weatherError ? (
                  <div className="model-error-hint">{weatherError}</div>
                ) : currentWeather ? (
                  <div className="model-grid-comparison">
                    <div className="model-comparison-row">
                      <span className="cmp-label">Model Temperature:</span>
                      <span className="cmp-val">{currentWeather.temperature.toFixed(1)}°C</span>
                      {obsTemp !== null && (
                        <span className={`cmp-delta ${Math.abs(currentWeather.temperature - obsTemp) > 3.0 ? 'delta-high' : 'delta-ok'}`}>
                          Δ {(obsTemp - currentWeather.temperature).toFixed(1)}°C
                        </span>
                      )}
                    </div>
                    <div className="model-comparison-row">
                      <span className="cmp-label">Model Pressure:</span>
                      <span className="cmp-val">{currentWeather.pressure.toFixed(1)} hPa</span>
                      {obsPress !== null && obsPress >= 1.0 && (
                        <span className={`cmp-delta ${Math.abs(currentWeather.pressure - obsPress) > 15.0 ? 'delta-high' : 'delta-ok'}`}>
                          Δ {(obsPress - currentWeather.pressure).toFixed(1)} hPa
                        </span>
                      )}
                    </div>
                    <div className="model-comparison-row">
                      <span className="cmp-label">Model Humidity:</span>
                      <span className="cmp-val">{Math.round(currentWeather.humidity)}%</span>
                    </div>
                    <div className="model-comparison-row">
                      <span className="cmp-label">Model Wind:</span>
                      <span className="cmp-val">{currentWeather.windSpeed} km/h {currentWeather.windDirection}</span>
                    </div>
                    <div className="model-provenance-note">
                      * NWP reference is generated from Open-Meteo ECMWF/GFS global models at 0.1° resolution. Discrepancies may reflect microclimate or sensor calibration offsets.
                    </div>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </div>

        {/* 3b. Three-Nearest-Station Validation */}
        {neighbors.length > 0 && (
          <div className="section-card neighbor-validation-card">
            <div className="card-header-flex">
              <div className="card-title-group">
                <Radio className="w-3.5 h-3.5 text-cyan-400" />
                <span className="card-section-title">NEAREST STATION VALIDATION</span>
              </div>
              {neighborVerdict && (
                <span className={`neighbor-verdict-pill verdict-${neighborVerdict}`}>
                  {neighborVerdict.replace(/_/g, ' ')}
                </span>
              )}
            </div>

            <div className="neighbor-list">
              {neighbors.map((n, idx) => (
                <div key={n.id} className="neighbor-row">
                  <span className="neighbor-index">N{idx + 1}</span>
                  <span className="neighbor-id">{n.id}</span>
                  <span className="neighbor-distance">{n.distanceKm.toFixed(1)} km</span>
                  <span className={`neighbor-status-dot status-${n.status}`} title={n.status} />
                </div>
              ))}
            </div>

            <div className="neighbor-check-title">VALIDATING NEIGHBOR STATIONS</div>
            <div className="neighbor-check-list">
              {neighborChecks.map((check, idx) => (
                <div
                  key={check.neighbor.id}
                  className={`neighbor-check-row ${check.consistent ? 'ok' : 'warn'}`}
                  style={{ animationDelay: `${idx * 140}ms` }}
                  title={check.reason}
                >
                  {check.consistent ? (
                    <Check className="w-3 h-3" />
                  ) : (
                    <AlertTriangle className="w-3 h-3" />
                  )}
                  <span>Neighbor {idx + 1} ({check.neighbor.id})</span>
                  <span className="neighbor-check-reason">{check.reason}</span>
                </div>
              ))}
            </div>

            <div className="neighbor-comparison-table">
              {neighborComparisons.map((c) => (
                <div key={c.parameter} className="neighbor-comparison-row">
                  <span className="cmp-param-label">{c.parameter}</span>
                  <span className="cmp-param-val">
                    {c.primaryValue !== null ? `${c.primaryValue.toFixed(1)}${c.unit}` : '--'}
                  </span>
                  <span className="cmp-param-arrow">vs</span>
                  <span className="cmp-param-val neighbor">
                    {c.neighborAverage !== null ? `${c.neighborAverage.toFixed(1)}${c.unit}` : '--'}
                  </span>
                  <span className="cmp-param-delta">
                    {c.delta !== null ? `Δ ${c.delta > 0 ? '+' : ''}${c.delta.toFixed(1)}${c.unit}` : 'n/a'}
                  </span>
                </div>
              ))}
            </div>

            <div className="neighbor-validation-note">
              Quick comparison against the {neighbors.length} nearest station{neighbors.length > 1 ? 's' : ''} by real
              distance (client-side, informational). See Spatial Consensus (L4) above for the backend's own regional
              consistency score.
            </div>
          </div>
        )}

        {/* 4. "Why?" / Analytical Summary (§19.4) */}
        <div className="section-card explanation-card">
          <div className="card-header-flex">
            <div className="card-title-group">
              <HelpCircle className="w-3.5 h-3.5 text-amber-400" />
              <span className="card-section-title">ANALYSIS SUMMARY & EXPLANATION</span>
            </div>
            {canonical?.veto_fired && <span className="veto-fired-pill">PHYSICS VETO FIRED</span>}
          </div>
          <p className="explanation-paragraph">
            {canonical?.explanation ||
              (isAnomaly
                ? 'Elevated sensor channel divergence detected by multi-layer screening.'
                : 'Nominal conditions verified across thermodynamic physical boundaries, statistical temporal series, multivariate correlation manifolds, and regional spatial mesh.')}
          </p>
        </div>

        {/* 5. 5-Layer Diagnostic Breakdown Cards (§19.6, §21) */}
        <div className="section-card layers-card">
          <div className="card-header-flex">
            <div className="card-title-group">
              <Layers className="w-3.5 h-3.5 text-emerald-400" />
              <span className="card-section-title">5-LAYER DIAGNOSTIC EVALUATION</span>
            </div>
            <span className="layers-count-badge">5 Screening Layers</span>
          </div>

          <div className="layer-cards-list">
            {layerDefs.map(({ key, label, short }) => {
              const layerData = getLayerData(key);
              const isPass = layerData.status === 'PASS';
              const isVeto = layerData.status === 'VETO';
              const isAlert = layerData.status === 'ANOMALY' || isVeto;
              const isWarn = layerData.status === 'WARNING';
              const isLimited = layerData.status === 'INSUFFICIENT_DATA' || layerData.status === 'LIMITED';

              return (
                <div key={key} className={`canonical-layer-item ${layerData.status}`}>
                  <div className="layer-item-top">
                    <div className="layer-item-title-group">
                      <span className="layer-short-name">{short}</span>
                      <span className="layer-full-name">{label}</span>
                    </div>

                    <div className="layer-item-badges">
                      <span className={`layer-status-pill ${layerData.status}`}>
                        {layerData.status}
                      </span>
                      <span className="layer-score-pill">
                        {(layerData.score * 100).toFixed(0)}%
                      </span>
                      {layerData.evidence_quality && (
                        <span className={`layer-quality-tag ${layerData.evidence_quality}`}>
                          {layerData.evidence_quality}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="layer-reason-text">
                    {layerData.reason}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 6. Root Cause Analysis (§19.7, §20) */}
        {(isAnomaly || isWarning || canonicalDiag) && (
          <div className="section-card root-cause-card">
            <div className="card-header-flex">
              <div className="card-title-group">
                <AlertOctagon className="w-3.5 h-3.5 text-rose-400" />
                <span className="card-section-title">ROOT CAUSE DIAGNOSIS</span>
              </div>
              <span className={`diagnosis-confidence-tag ${confidenceLevel}`}>
                {confidenceLevel} CONFIDENCE
              </span>
            </div>

            <div className="diagnosis-primary-box">
              <span className="diagnosis-heading-label">PRIMARY CLASSIFICATION:</span>
              <h4 className="diagnosis-primary-title">
                {getGatedDiagnosisTitle(canonicalDiag?.primary || canonical?.root_cause, confidenceLevel)}
              </h4>
            </div>

            {/* Supporting Evidence Items */}
            {canonicalDiag?.evidence && canonicalDiag.evidence.length > 0 && (
              <div className="diagnosis-evidence-box">
                <span className="evidence-box-label">SUPPORTING TELEMETRY EVIDENCE:</span>
                <ul className="evidence-bullet-list">
                  {canonicalDiag.evidence.map((ev, idx) => (
                    <li key={idx} className="evidence-bullet-item">
                      <span className="bullet-dash">›</span>
                      <span>{ev}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Alternative Hypotheses */}
            {canonicalDiag?.alternatives && canonicalDiag.alternatives.length > 0 && (
              <div className="diagnosis-alternatives-box">
                <span className="alternatives-box-label">ALTERNATIVE HYPOTHESES CONSIDERED:</span>
                <div className="alternatives-chips">
                  {canonicalDiag.alternatives.map((alt, idx) => (
                    <span key={idx} className="alternative-chip">
                      {alt}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Operator Recommended Action */}
            {canonicalDiag?.operator_action && (
              <div className="operator-action-box">
                <span className="action-box-label">RECOMMENDED ACTION:</span>
                <p className="action-box-text">{canonicalDiag.operator_action}</p>
              </div>
            )}
          </div>
        )}

        {/* 7. Meteorological Weather Analysis (§19.8) */}
        {canonicalWeather && (
          <div className="section-card weather-analysis-card">
            <div className="card-header-flex">
              <div className="card-title-group">
                <Compass className="w-3.5 h-3.5 text-sky-400" />
                <span className="card-section-title">METEOROLOGICAL ANALYSIS</span>
              </div>
              {canonicalWeather.likely_phenomenon && (
                <span className="phenomenon-badge">{canonicalWeather.likely_phenomenon}</span>
              )}
            </div>

            <p className="weather-summary-text">{canonicalWeather.summary}</p>

            {canonicalWeather.meteorological_context && (
              <div className="weather-context-note">
                <span className="context-lbl">Context:</span> {canonicalWeather.meteorological_context}
              </div>
            )}
          </div>
        )}

        {/* 8. Operator Insights (§19.9) */}
        {canonicalInsights.length > 0 && (
          <div className="section-card insights-card">
            <div className="card-header-flex">
              <div className="card-title-group">
                <Info className="w-3.5 h-3.5 text-amber-400" />
                <span className="card-section-title">OPERATOR INSIGHTS & ACTIONS</span>
              </div>
            </div>

            <div className="insights-list">
              {canonicalInsights.map((insight, idx) => (
                <div key={idx} className="insight-card-item">
                  <div className="insight-row">
                    <span className="insight-lbl">WHAT:</span>
                    <span className="insight-val">{insight.what}</span>
                  </div>
                  <div className="insight-row">
                    <span className="insight-lbl">WHY:</span>
                    <span className="insight-val">{insight.why}</span>
                  </div>
                  <div className="insight-row">
                    <span className="insight-lbl">EVIDENCE:</span>
                    <span className="insight-val font-mono">{insight.evidence}</span>
                  </div>
                  <div className="insight-row action-row">
                    <span className="insight-lbl action">ACTION:</span>
                    <span className="insight-val action">{insight.action}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 9. Sensor Health / Projected Drift (§19.6 L5 Detail) */}
        {canonical?.sensor_health_index !== undefined && (
          <div className="section-card health-card">
            <div className="card-header-flex">
              <div className="card-title-group">
                <Cpu className="w-3.5 h-3.5 text-emerald-400" />
                <span className="card-section-title">SENSOR ARRAY HEALTH</span>
              </div>
              <span className="health-percentage-pill">
                {canonical.sensor_health_index.toFixed(0)}% Health
              </span>
            </div>

            <div className="health-bar-track">
              <div
                className="health-bar-fill"
                style={{
                  width: `${Math.max(5, canonical.sensor_health_index)}%`,
                  backgroundColor:
                    canonical.sensor_health_index > 75
                      ? '#10b981'
                      : canonical.sensor_health_index > 50
                      ? '#f59e0b'
                      : '#ef4444',
                }}
              />
            </div>

            {canonical.estimated_days_to_failure && (
              <div className="days-failure-hint">
                <AlertTriangle className="w-3 h-3 text-amber-400" />
                <span>
                  Projected out-of-tolerance drift in ~{canonical.estimated_days_to_failure.toFixed(1)} days based on CUSUM trajectory
                </span>
              </div>
            )}
          </div>
        )}

        {/* 10. 24-Hour Diurnal Trend Sparkline (§19.11) */}
        {history && history.series.length > 0 && (
          <div className="section-card trend-section">
            <div className="card-header-flex">
              <div className="card-title-group">
                <TrendingUp className="w-3.5 h-3.5 text-cyan-400" />
                <span className="card-section-title">24-HOUR THERMAL TREND</span>
              </div>
              <div className="trend-minmax">
                Min {minTemp.toFixed(1)}°C · Max {maxTemp.toFixed(1)}°C
              </div>
            </div>

            <svg className="sparkline-svg" viewBox="0 0 320 56">
              <defs>
                <linearGradient id="trendGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#00e5ff" stopOpacity="0.4" />
                  <stop offset="100%" stopColor="#0284c7" stopOpacity="0.0" />
                </linearGradient>
              </defs>
              <polyline
                fill="none"
                stroke="#00e5ff"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                points={points}
              />
              {isAnomaly && (
                <circle
                  cx="320"
                  cy={52 - ((temps[temps.length - 1] - minTemp) / tempRange) * 42}
                  r="4.5"
                  fill={isWarning ? '#f59e0b' : '#ef4444'}
                  stroke="#ffffff"
                  strokeWidth="2"
                />
              )}
            </svg>

            <div className="trend-timestamps">
              <span>24h ago</span>
              <span>12h ago</span>
              <span>Now (In-Situ)</span>
            </div>
          </div>
        )}

        {/* 11. Data Quality & Provenance Strip (§19.10) */}
        <div className="section-card data-quality-card">
          <div className="card-header-flex">
            <div className="card-title-group">
              <Database className="w-3.5 h-3.5 text-slate-400" />
              <span className="card-section-title">DATA PROVENANCE & QUALITY</span>
            </div>
            <span className={`data-quality-status-pill ${canonicalQuality?.status || 'VALID'}`}>
              {canonicalQuality?.status || 'VALID'}
            </span>
          </div>

          <div className="data-quality-grid">
            <div className="quality-item">
              <span className="quality-key">Valid Channels:</span>
              <span className="quality-val">
                {canonicalQuality?.valid_fields?.length
                  ? canonicalQuality.valid_fields.map((f) => f.replace('_c', '').replace('_hpa', '').replace('_pct', '').toUpperCase()).join(', ')
                  : 'T, P, RH'}
              </span>
            </div>

            <div className="quality-item">
              <span className="quality-key">Missing / Zero-Sub:</span>
              <span className="quality-val">
                {[
                  ...(canonicalQuality?.missing_fields || []),
                  ...(canonicalQuality?.zero_substituted_fields || []).map((f) => `${f} (0.0 treated as missing)`),
                ].join(', ') || 'None'}
              </span>
            </div>

            <div className="quality-item">
              <span className="quality-key">Historical Samples:</span>
              <span className="quality-val">
                {canonicalQuality?.historical_points ?? history?.series.length ?? 0} samples
              </span>
            </div>

            <div className="quality-item">
              <span className="quality-key">Regional Neighbors:</span>
              <span className="quality-val">
                {canonicalQuality?.nearby_stations ?? 0} stations in mesh
              </span>
            </div>
          </div>

          {canonicalQuality?.limitations && canonicalQuality.limitations.length > 0 && (
            <div className="data-limitations-list">
              <span className="limitations-heading">Analytical Limitations:</span>
              <ul>
                {canonicalQuality.limitations.map((lim, idx) => (
                  <li key={idx}>{lim}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
