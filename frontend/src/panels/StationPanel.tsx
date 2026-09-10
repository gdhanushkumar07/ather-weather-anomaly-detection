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
import {
  fetchStationObservations, fetchCurrentWeather, fetchStationAnomaly,
  fetchStationIncidents, acknowledgeIncident, investigateIncident, resolveIncident, dismissIncident
} from '../services/api';
import { EscalationPreviewModal } from '../components/EscalationPreviewModal';
import { ResolveIncidentModal } from '../components/ResolveIncidentModal';
import { DismissIncidentModal } from '../components/DismissIncidentModal';
import { StationHistoricalGraphs } from '../components/StationHistoricalGraphs';
import { ShieldAlert as IncidentIcon, UserCheck, Search as InvestigateIcon, Siren, ArrowLeft, XCircle } from 'lucide-react';

// Mirrors app/incidents/service.py::VALID_TRANSITIONS — used only to decide
// which action buttons are enabled; the backend is the actual authority
// and will reject anything invalid regardless (Phase 34/44).
const INCIDENT_VALID_TRANSITIONS: Record<string, string[]> = {
  NEW: ['ACKNOWLEDGED', 'DISMISSED'],
  ACKNOWLEDGED: ['INVESTIGATING', 'DISMISSED'],
  INVESTIGATING: ['ESCALATED', 'RESOLVED', 'DISMISSED'],
  ESCALATED: ['RESOLVED', 'DISMISSED'],
  RESOLVED: [],
  DISMISSED: [],
};

interface StationPanelProps {
  station: Station | null;
  onClose: () => void;
  /** 'drawer' (default) = existing fixed sliding overlay, unchanged.
   *  'page' = dedicated full-workspace rendering for the Station
   *  Intelligence workspace (ATHER UI architecture restructure) — same
   *  component, same data, only the outer chrome differs. */
  variant?: 'drawer' | 'page';
}

export const StationPanel: React.FC<StationPanelProps> = ({ station, onClose, variant = 'drawer' }) => {
  const [history, setHistory] = useState<ObservationHistory | null>(null);
  const [historyHours, setHistoryHours] = useState<number>(24);
  const [isHistoryLoading, setIsHistoryLoading] = useState<boolean>(false);
  const [cachedStation, setCachedStation] = useState<Station | null>(station);

  const [currentWeather, setCurrentWeather] = useState<OpenMeteoWeather | null>(null);
  const [isLoadingWeather, setIsLoadingWeather] = useState<boolean>(false);
  const [weatherError, setWeatherError] = useState<string | null>(null);

  const [anomalyAssessment, setAnomalyAssessment] = useState<StationAnomalyAssessment | null>(null);
  const [isLoadingAnomaly, setIsLoadingAnomaly] = useState<boolean>(false);

  // Toggle for Open-Meteo comparison view
  const [showModelComparison, setShowModelComparison] = useState<boolean>(false);

  // ATHER Incident workflow — persistent, incident-ID keyed (production-grade)
  const [incident, setIncident] = useState<any | null>(null);
  const [isIncidentBusy, setIsIncidentBusy] = useState(false);
  const [showEscalationPreview, setShowEscalationPreview] = useState(false);
  const [showResolveModal, setShowResolveModal] = useState(false);
  const [showDismissModal, setShowDismissModal] = useState(false);

  // 5-Layer accordion progressive disclosure (Phase 12)
  const [expandedLayers, setExpandedLayers] = useState<Record<string, boolean>>({});
  const toggleLayerExpand = (key: string) => {
    setExpandedLayers((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleHoursChange = (hours: number) => {
    const targetStn = station || cachedStation;
    if (!targetStn) return;
    setHistoryHours(hours);
    setIsHistoryLoading(true);
    fetchStationObservations(targetStn.id, hours)
      .then((h) => {
        setHistory(h);
        setIsHistoryLoading(false);
      })
      .catch((err) => {
        console.error('Failed to load observations for range', err);
        setIsHistoryLoading(false);
      });
  };

  useEffect(() => {
    if (station) {
      setCachedStation(station);
      setWeatherError(null);
      setIsLoadingWeather(true);
      setIsLoadingAnomaly(true);
      setHistoryHours(24);
      setIsHistoryLoading(true);

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

      // 2. Fetch observations history for charts (24 hours default)
      fetchStationObservations(station.id, 24)
        .then((h) => {
          setHistory(h);
          setIsHistoryLoading(false);
        })
        .catch((err) => {
          console.error('Failed to load observations history', err);
          setIsHistoryLoading(false);
        });

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

      // 4. Fetch persisted incident history for this station (Phase 21-23):
      // incidents are created automatically by the backend pipeline, never
      // by the frontend — this only reads state. An incident stays visible
      // here even after the station's CURRENT observation returns to
      // NORMAL (Phase 22/23: current station state and incident state are
      // never conflated). We surface the most recently updated OPEN
      // incident if one exists, otherwise the most recent incident overall
      // so history remains visible.
      setIncident(null);
      fetchStationIncidents(station.id)
        .then(({ incidents }) => {
          if (!incidents || incidents.length === 0) return;
          const open = incidents.find((i: any) => i.status !== 'RESOLVED' && i.status !== 'DISMISSED');
          setIncident(open || incidents[0]);
        })
        .catch((err) => console.error('Failed to fetch station incidents', err));
    }
  }, [station?.id, station?.latitude, station?.longitude, station?.status]);

  const refreshIncident = (stationId: string) => {
    fetchStationIncidents(stationId)
      .then(({ incidents }) => {
        if (!incidents || incidents.length === 0) return;
        const open = incidents.find((i: any) => i.status !== 'RESOLVED' && i.status !== 'DISMISSED');
        setIncident(open || incidents[0]);
      })
      .catch((err) => console.error('Failed to refresh incident', err));
  };

  const handleIncidentAction = async (action: 'acknowledge' | 'investigate') => {
    if (!incident) return;
    setIsIncidentBusy(true);
    try {
      const fn = { acknowledge: acknowledgeIncident, investigate: investigateIncident }[action];
      const updated = await fn(incident.incident_id);
      setIncident(updated);
    } catch (err: any) {
      console.error(`Incident action '${action}' failed`, err);
      alert(err.message || `Failed to ${action} incident.`);
    } finally {
      setIsIncidentBusy(false);
    }
  };

  const handleResolveIncident = async (notes: string, resolutionType: string) => {
    if (!incident) return;
    const updated = await resolveIncident(incident.incident_id, notes, resolutionType);
    setIncident(updated);
  };

  const handleDismissIncident = async (reason: string) => {
    if (!incident) return;
    const updated = await dismissIncident(incident.incident_id, reason);
    setIncident(updated);
  };

  const incidentAllowedNext = (target: string): boolean => {
    if (!incident) return false;
    return INCIDENT_VALID_TRANSITIONS[incident.status]?.includes(target) ?? false;
  };

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

  // Verified data provenance (Phase 1-4, 20, 27): never assume AWS in-situ.
  // 'AWS_IN_SITU' | 'NWP_MODEL_REFERENCE' | 'MISSING' | 'UNKNOWN'
  const obsSource: string = canonicalObs?.source || 'UNKNOWN';
  const obsFreshness: string = canonicalObs?.freshness || 'UNKNOWN';
  const isAwsInSitu = obsSource === 'AWS_IN_SITU';
  const isNwpReference = obsSource === 'NWP_MODEL_REFERENCE';
  const awsTelemetryStatus: string = canonical?.aws_telemetry_status || (isAwsInSitu ? 'TELEMETRY_AVAILABLE' : 'TELEMETRY_UNAVAILABLE');

  const provenanceLabel = isAwsInSitu
    ? 'AWS IN-SITU TELEMETRY'
    : isNwpReference
      ? 'NWP MODEL REFERENCE — NOT MEASURED'
      : obsSource === 'MISSING'
        ? 'NO TELEMETRY AVAILABLE'
        : 'PROVENANCE UNVERIFIED';
  const provenanceDotClass = isAwsInSitu ? '' : isNwpReference ? 'nwp' : 'unknown';

  const observationSourcePillLabel = isAwsInSitu
    ? 'AWS Station Data'
    : isNwpReference
      ? 'NWP Model Reference'
      : obsSource === 'MISSING'
        ? 'No Data'
        : 'Unverified Source';
  const observationSourcePillClass = isAwsInSitu ? 'in-situ' : isNwpReference ? 'nwp-reference' : 'unavailable';

  const freshnessPillClass = obsFreshness === 'LIVE' ? 'live' : obsFreshness === 'STALE' ? 'stale' : obsFreshness === 'MISSING' ? 'missing' : 'unknown';

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

  // 5-Layer card definitions (Phase 12)
  const layerDefs = [
    { key: 'physics', num: '01', label: 'PHYSICS', full: 'Thermodynamic Boundary Validation' },
    { key: 'temporal', num: '02', label: 'TEMPORAL', full: 'Temporal Rate of Change & Persistence' },
    { key: 'multivariate', num: '03', label: 'MULTIVARIATE', full: 'Inter-Channel Correlation' },
    { key: 'spatial', num: '04', label: 'SPATIAL', full: 'Regional AWS Mesh Consensus' },
    { key: 'drift', num: '05', label: 'SENSOR HEALTH', full: 'Sensor Degradation & Drift' },
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

  // Phase 14: Evidence derivation from real engine output
  const flaggedEvidence: string[] = (() => {
    if (canonicalDiag?.evidence && canonicalDiag.evidence.length > 0) {
      return canonicalDiag.evidence;
    }
    if (incident?.latest_snapshot?.evidence && incident.latest_snapshot.evidence.length > 0) {
      return incident.latest_snapshot.evidence;
    }
    if (canonical?.reasons && canonical.reasons.length > 0) {
      return canonical.reasons;
    }
    const list: string[] = [];
    const l1 = getLayerData('physics');
    const l2 = getLayerData('temporal');
    const l3 = getLayerData('multivariate');
    const l4 = getLayerData('spatial');
    const l5 = getLayerData('drift');

    if (l1.status === 'ANOMALY' || l1.status === 'VETO') list.push('Physics deviation: ' + l1.reason);
    if (l2.status === 'ANOMALY') list.push('Temporal spike: ' + l2.reason);
    if (l4.status === 'ANOMALY' || l4.status === 'WARNING') list.push('Spatial outlier: ' + l4.reason);
    if (l3.status === 'ANOMALY') list.push('Multivariate inconsistency: ' + l3.reason);
    if (l5.status === 'ANOMALY' || l5.status === 'WARNING') list.push('Sensor drift: ' + l5.reason);
    return list;
  })();

  return (
    <div className={variant === 'page' ? 'station-intelligence-page' : `station-panel-wrapper ${station ? 'expanded' : 'collapsed'}`}>
      {variant === 'page' && (
        <div className="station-page-backbar">
          <button className="back-to-map-btn" onClick={onClose}>
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Map
          </button>
          <span className="station-page-backbar-label">STATION INTELLIGENCE</span>
        </div>
      )}
      {/* 1. Header (§19.1) */}
      <div className="station-panel-header">
        <div className="header-meta">
          <div className="station-badge-row">
            <span className="station-panel-tag" title={isNwpReference ? 'This value is a NWP model reference, not a measured AWS sensor reading.' : undefined}>
              <span className={`source-live-indicator ${provenanceDotClass}`} />
              {provenanceLabel}
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
              {canonicalObs?.observation_timestamp
                ? <>Observed: {new Date(canonicalObs.observation_timestamp).toUTCString()}</>
                : canonicalObs?.received_timestamp
                  ? <>Last checked: {new Date(canonicalObs.received_timestamp).toUTCString()} <span className="label-sub-alert">(observation time unverified)</span></>
                  : <>Observed: {currentStation.timestamp || 'Recent'}</>}
            </span>
            <span className={`freshness-pill ${freshnessPillClass}`} title="Freshness is derived from the real observation timestamp, never from request time.">
              {obsFreshness}
            </span>
          </div>
        </div>
        <button className="btn-close-panel" onClick={onClose} title="Close Station Panel">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="station-panel-body">
        {/* 2 & 3. Visual + Current Observations side by side (Phase 13/15) */}
        <div className="station-grid-row">
        <div className="station-visual-card">
          <div className="station-visual-header">
            <div className="station-visual-badge">
              <Radio className="w-3.5 h-3.5 text-cyan-400" />
              <span>AWS STATION ASSET</span>
            </div>
            <span className="station-visual-disclaimer">
              REPRESENTATIVE AWS IMAGE
            </span>
          </div>
          <div className="station-visual-image-wrapper">
            <img
              src="/representative_aws_station.jpg"
              alt="Representative Automatic Weather Station mast with meteorological sensors"
              className="station-visual-img"
            />
            <div className="station-visual-overlay">
              <div className="station-visual-meta">
                <span className="station-type-tag">Station type: Automatic Weather Station</span>
                <span className="station-id-tag">{currentStation.id}</span>
              </div>
            </div>
          </div>
          <div className="station-visual-caption">
            <Info className="w-3 h-3 text-slate-400 shrink-0" />
            <span>Standard meteorological mast (cup anemometer, solar radiation shield, data logger). Representative visual.</span>
          </div>
        </div>

        {/* 3. Live Observations (§19.2) - Explicitly Sourced AWS Telemetry */}
        <div className="section-card observation-card">
          <div className="card-header-flex">
            <div className="card-title-group">
              <Database className="w-3.5 h-3.5 text-cyan-400" />
              <span className="card-section-title">{isAwsInSitu ? 'CURRENT IN-SITU OBSERVATIONS' : 'CURRENT OBSERVATIONS'}</span>
            </div>
            <span
              className={`source-tag-pill ${observationSourcePillClass}`}
              title={isAwsInSitu ? 'Ground truth physical sensor reading' : isNwpReference ? 'Numerical weather model output — not a measured sensor reading' : 'Provenance could not be verified'}
            >
              {observationSourcePillLabel}
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

          {/* Model Forecast Comparison Drawer */}
          {isNwpReference ? (
            <div className="model-comparison-container">
              <div className="nwp-self-source-disclosure">
                <CloudSun className="w-3.5 h-3.5 text-amber-400" />
                <span>
                  No AWS in-situ sensor feed is connected for this station. The reading above
                  is itself the Open-Meteo NWP model reference — it is not an independent
                  comparison and should not be read as validated sensor telemetry.
                </span>
              </div>
            </div>
          ) : (
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
                        * NWP reference is generated from Open-Meteo ECMWF/GFS global models at 0.1° resolution.
                      </div>
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          )}
        </div>
        </div>

        {/* 2. Station Health Section (Phase 11) */}
        <div className="section-card station-health-card">
          <div className="card-header-flex">
            <div className="card-title-group">
              <Activity className="w-3.5 h-3.5 text-emerald-400" />
              <span className="card-section-title">STATION HEALTH & TELEMETRY</span>
            </div>
            <div className={`status-pill ${status}`}>
              <span className="status-pill-dot" />
              <span className="status-pill-text">{status}</span>
            </div>
          </div>

          <div className="station-health-grid">
            <div className="health-grid-col">
              <span className="health-grid-lbl">Health Score</span>
              <span className="health-grid-val">
                {canonical?.sensor_health_index !== undefined ? `${canonical.sensor_health_index.toFixed(0)}%` : '100%'}
              </span>
            </div>
            <div className="health-grid-col">
              <span className="health-grid-lbl">Telemetry State</span>
              <span className="health-grid-val">
                {awsTelemetryStatus === 'TELEMETRY_AVAILABLE' ? 'ONLINE / CONNECTED' : 'UNAVAILABLE'}
              </span>
            </div>
            <div className="health-grid-col">
              <span className="health-grid-lbl">Anomaly Score</span>
              <span className={`health-grid-val ${isAnomaly ? 'alert' : isWarning ? 'warn' : 'normal'}`}>
                {(anomalyScore * 100).toFixed(0)}%
              </span>
            </div>
            <div className="health-grid-col">
              <span className="health-grid-lbl">Confidence</span>
              <span className="health-grid-val">
                {(confidenceScore * 100).toFixed(0)}% ({confidenceLevel})
              </span>
            </div>
          </div>

          {canonical?.sensor_health_index !== undefined && (
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
          )}

          {canonical?.estimated_days_to_failure && (
            <div className="days-failure-hint">
              <AlertTriangle className="w-3 h-3 text-amber-400" />
              <span>
                Projected out-of-tolerance drift in ~{canonical.estimated_days_to_failure.toFixed(1)} days based on CUSUM trajectory
              </span>
            </div>
          )}
        </div>

        {/* 5. Historical Readings & Analytical Graphs (Phase 9-14) */}
        <StationHistoricalGraphs
          station={currentStation}
          series={history?.series || []}
          hours={historyHours}
          onHoursChange={handleHoursChange}
          isLoading={isHistoryLoading}
          anomalyAssessment={canonical}
        />

        {/* 6. Anomaly Timeline (Phase 16 - when anomaly or warning is present) */}
        {(isAnomaly || isWarning) && (
          <div className="section-card anomaly-timeline-card">
            <div className="card-header-flex">
              <div className="card-title-group">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                <span className="card-section-title">ANOMALY TIMELINE</span>
              </div>
              <span className={`severity-tag ${severityLevel}`}>{severityLevel}</span>
            </div>
            <div className="anomaly-timeline-list">
              <div className="anomaly-timeline-item">
                <div className="timeline-time-col">
                  <span className="timeline-time-text">{currentStation.timestamp || 'Latest'}</span>
                  <span className="timeline-event-sub">In-Situ</span>
                </div>
                <div className="timeline-content-col">
                  <div className="timeline-event-title">
                    {canonicalDiag?.primary || currentStation.anomaly?.parameter || 'Telemetry Outlier'}
                  </div>
                  <div className="timeline-event-sub">
                    {canonical?.root_cause || currentStation.anomaly?.rootCause || 'Divergence from mesh consensus'}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 7 & 8. Diagnostics + Root Cause/Action side by side when there is
            something to explain (Phase 20/21/42) — a single plain wrapper
            (no grid class) when the station is normal, so the diagnostics
            card alone still renders full width unchanged. */}
        <div className={isAnomaly || isWarning ? 'station-grid-row' : undefined}>
        {/* 7. Phase 15, 28: 5-Layer Diagnostic Evaluation (Vertical Accordion) */}
        <div className="section-card layers-card">
          <div className="card-header-flex">
            <div className="card-title-group">
              <Layers className="w-3.5 h-3.5 text-emerald-400" />
              <span className="card-section-title">5-LAYER DIAGNOSTIC EVALUATION</span>
            </div>
            <span className="layers-count-badge">5 Screening Layers</span>
          </div>

          <div className="layer-accordion-list">
            {layerDefs.map(({ key, num, label, full }) => {
              const layerData = getLayerData(key);
              const isExpanded = Boolean(expandedLayers[key]);
              const statusClass = layerData.status.toLowerCase();

              return (
                <div key={key} className={`layer-accordion-item ${statusClass}`}>
                  <div
                    className="layer-accordion-header"
                    onClick={() => toggleLayerExpand(key)}
                    title="Click to toggle layer diagnostic details"
                  >
                    <div className="layer-header-left">
                      <span className="layer-num-badge">{num}</span>
                      <span className="layer-name-title">{label}</span>
                      <span className="layer-full-desc">{full}</span>
                    </div>

                    <div className="layer-header-right">
                      <span className={`layer-status-pill ${statusClass}`}>
                        ● {layerData.status}
                      </span>
                      <span className="layer-score-pill">
                        {(layerData.score * 100).toFixed(0)}%
                      </span>
                      {isExpanded ? (
                        <ChevronUp className="w-3.5 h-3.5 text-slate-400" />
                      ) : (
                        <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
                      )}
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="layer-accordion-body">
                      <div className="layer-expanded-grid">
                        <div>
                          <span className="layer-meta-lbl">Layer Score:</span>
                          <span className="layer-meta-val">{(layerData.score * 100).toFixed(1)}%</span>
                        </div>
                        <div>
                          <span className="layer-meta-lbl">Evidence Quality:</span>
                          <span className={`layer-quality-tag ${layerData.evidence_quality || 'MEDIUM'}`}>
                            {layerData.evidence_quality || 'MEDIUM'}
                          </span>
                        </div>
                      </div>
                      <div className="layer-reason-text">
                        <span className="layer-reason-lbl">Reason: </span>
                        {layerData.reason}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* 8. Phase 18-20: Anomaly Intelligence & Incident Workflow (When Anomaly/Warning exists) */}
        {(isAnomaly || isWarning) && (
          <div className="section-card anomaly-intelligence-card">
            <div className="card-header-flex">
              <div className="card-title-group">
                <AlertOctagon className="w-3.5 h-3.5 text-red-400" />
                <span className="card-section-title">ANOMALY INTELLIGENCE</span>
              </div>
              <span className={`anomaly-severity-banner-pill ${severityLevel}`}>
                {severityLevel}
              </span>
            </div>

            <div className="anomaly-intelligence-details">
              <div className="anomaly-headline">
                <span className="anomaly-param-tag">
                  {currentStation.anomaly?.parameter || 'Temperature'} Anomaly
                </span>
                <span className="anomaly-stn-tag">Station ID: {currentStation.id}</span>
              </div>

              <div className="anomaly-metrics-grid">
                <div className="anomaly-metric-box">
                  <span className="anomaly-box-lbl">Observed:</span>
                  <span className="anomaly-box-val alert">
                    {obsTemp !== null && obsTemp !== undefined ? `${obsTemp.toFixed(1)} °C` : '--'}
                  </span>
                </div>
                <div className="anomaly-metric-box">
                  <span className="anomaly-box-lbl">Expected:</span>
                  <span className="anomaly-box-val">
                    {currentWeather ? `${currentWeather.temperature.toFixed(1)} °C (NWP)` : 'Mesh Baseline'}
                  </span>
                </div>
                <div className="anomaly-metric-box">
                  <span className="anomaly-box-lbl">Anomaly Score:</span>
                  <span className="anomaly-box-val alert">{(anomalyScore * 100).toFixed(0)}%</span>
                </div>
                <div className="anomaly-metric-box">
                  <span className="anomaly-box-lbl">Confidence:</span>
                  <span className="anomaly-box-val">{confidenceLevel}</span>
                </div>
              </div>

              <div className="anomaly-root-cause-row">
                <span className="root-cause-lbl">Root Cause:</span>
                <strong className="root-cause-val">
                  {String(canonicalDiag?.primary || canonical?.root_cause || 'Likely Sensor Fault').replace(/_/g, ' ')}
                </strong>
              </div>
            </div>

            {/* Phase 14: WHY WAS THIS FLAGGED */}
            {flaggedEvidence.length > 0 && (
              <div className="why-flagged-section">
                <div className="why-flagged-header">
                  <span>WHY THIS WAS FLAGGED</span>
                </div>
                <ul className="why-flagged-list">
                  {flaggedEvidence.map((item, idx) => (
                    <li key={idx} className="why-flagged-item">
                      <Check className="w-3.5 h-3.5 text-red-400 shrink-0" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Phase 15: WHAT SHOULD HAPPEN NEXT? */}
            <div className="action-workflow-section">
              <div className="action-header">
                <span>RECOMMENDED ACTION</span>
              </div>
              <p className="action-text">
                {canonicalDiag?.operator_action ||
                  (isAnomaly
                    ? 'Inspect temperature sensor calibration and cross-check neighboring stations.'
                    : 'Continue routine telemetry monitoring.')}
              </p>
            </div>
          </div>
        )}
        </div>

        {/* ATHER INCIDENT — a persistent record, independent of the CURRENT
            live station status above (Phase 22/23): a station can be back
            to NORMAL right now while its incident is still open. */}
        {incident && (
          <div className="section-card incident-workflow-card">
            <div className="card-header-flex">
              <div className="card-title-group">
                <IncidentIcon className="w-3.5 h-3.5 text-red-400" />
                <span className="card-section-title">INCIDENT · {incident.incident_id}</span>
              </div>
              <span className={`incident-state-pill ${incident.status}`}>{incident.status}</span>
            </div>

            <div className="anomaly-metrics-grid">
              <div className="anomaly-metric-box">
                <span className="anomaly-box-lbl">Parameter:</span>
                <span className="anomaly-box-val">{incident.parameter}</span>
              </div>
              <div className="anomaly-metric-box">
                <span className="anomaly-box-lbl">Observed:</span>
                <span className="anomaly-box-val alert">{incident.observed_value} {incident.unit}</span>
              </div>
              <div className="anomaly-metric-box">
                <span className="anomaly-box-lbl">Expected:</span>
                <span className="anomaly-box-val">
                  {incident.expected_min !== null && incident.expected_min !== undefined
                    ? `${incident.expected_min}–${incident.expected_max} ${incident.unit || ''}` : 'N/A'}
                </span>
              </div>
              <div className="anomaly-metric-box">
                <span className="anomaly-box-lbl">Confidence:</span>
                <span className="anomaly-box-val">{Math.round((incident.confidence || 0) * 100)}%</span>
              </div>
            </div>

            <div className="anomaly-root-cause-row">
              <span className="root-cause-lbl">Root Cause:</span>
              <strong className="root-cause-val">{String(incident.root_cause || '').replace(/_/g, ' ')}</strong>
            </div>

            {incident.evidence?.length > 0 && (
              <ul className="why-flagged-list" style={{ marginTop: 6 }}>
                {incident.evidence.slice(0, 4).map((e: string, i: number) => (
                  <li key={i} className="why-flagged-item"><Check className="w-3.5 h-3.5 text-red-400 shrink-0" /><span>{e}</span></li>
                ))}
              </ul>
            )}

            <div className="action-header" style={{ marginTop: 10 }}><span>RECOMMENDED ACTION</span></div>
            <p className="action-text">{incident.recommended_action}</p>

            {/* Phase 14: Incident Timeline */}
            {incident.timeline?.length > 0 && (
              <div className="incident-timeline">
                {incident.timeline.map((ev: any, i: number) => (
                  <div key={i} className="incident-timeline-row">
                    <span className="incident-timeline-time">{new Date(ev.at).toLocaleString()}</span>
                    <span className="incident-timeline-event">{ev.event.replace(/_/g, ' ')}</span>
                  </div>
                ))}
              </div>
            )}

            {incident.status !== 'RESOLVED' && incident.status !== 'DISMISSED' && (
              <div className="incident-actions-row">
                <button
                  className="incident-action-btn"
                  disabled={isIncidentBusy || !incidentAllowedNext('ACKNOWLEDGED')}
                  onClick={() => handleIncidentAction('acknowledge')}
                >
                  <UserCheck className="w-3 h-3" /> ACKNOWLEDGE
                </button>
                <button
                  className="incident-action-btn"
                  disabled={isIncidentBusy || !incidentAllowedNext('INVESTIGATING')}
                  onClick={() => handleIncidentAction('investigate')}
                >
                  <InvestigateIcon className="w-3 h-3" /> INVESTIGATE
                </button>
                <button
                  className="incident-action-btn escalate"
                  disabled={isIncidentBusy || !incidentAllowedNext('ESCALATED')}
                  onClick={() => setShowEscalationPreview(true)}
                >
                  <Siren className="w-3 h-3" /> ESCALATE
                </button>
                <button
                  className="incident-action-btn resolve"
                  disabled={isIncidentBusy || !incidentAllowedNext('RESOLVED')}
                  onClick={() => setShowResolveModal(true)}
                >
                  RESOLVE
                </button>
                <button
                  className="incident-action-btn"
                  disabled={isIncidentBusy || !incidentAllowedNext('DISMISSED')}
                  onClick={() => setShowDismissModal(true)}
                >
                  <XCircle className="w-3 h-3" /> DISMISS
                </button>
              </div>
            )}
          </div>
        )}

        {showEscalationPreview && incident && (
          <EscalationPreviewModal
            incidentId={incident.incident_id}
            onClose={() => setShowEscalationPreview(false)}
            onEscalated={() => cachedStation && refreshIncident(cachedStation.id)}
          />
        )}

        {showResolveModal && incident && (
          <ResolveIncidentModal
            incidentId={incident.incident_id}
            onClose={() => setShowResolveModal(false)}
            onResolve={handleResolveIncident}
          />
        )}

        {showDismissModal && incident && (
          <DismissIncidentModal
            incidentId={incident.incident_id}
            onClose={() => setShowDismissModal(false)}
            onDismiss={handleDismissIncident}
          />
        )}

        {/* 9. ATHER Station Summary (Phase 17) */}
        <div className="section-card station-summary-card">
          <div className="card-header-flex">
            <div className="card-title-group">
              <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" />
              <span className="card-section-title">ATHER STATION SUMMARY</span>
            </div>
            <span className={`summary-status-tag ${status}`}>
              {status}
            </span>
          </div>
          <div className="station-summary-grid">
            <div className="summary-metric">
              <span className="summary-key">Current State</span>
              <span className="summary-val font-mono">{status}</span>
            </div>
            <div className="summary-metric">
              <span className="summary-key">Data Quality</span>
              <span className="summary-val">{canonicalQuality?.status || 'GOOD'}</span>
            </div>
            <div className="summary-metric">
              <span className="summary-key">Telemetry</span>
              <span className="summary-val">{isAwsInSitu ? 'LIVE (IN-SITU)' : 'ACTIVE'}</span>
            </div>
            <div className="summary-metric">
              <span className="summary-key">Historical Coverage</span>
              <span className="summary-val">{historyHours === 168 ? '7 Days' : '24 Hours'}</span>
            </div>
            <div className="summary-metric">
              <span className="summary-key">Anomalies</span>
              <span className="summary-val">{isAnomaly ? '1 Active' : '0'}</span>
            </div>
            <div className="summary-metric">
              <span className="summary-key">Sensor Health</span>
              <span className="summary-val">{canonical?.sensor_health_index !== undefined ? `${canonical.sensor_health_index.toFixed(0)}%` : '100%'}</span>
            </div>
            <div className="summary-metric">
              <span className="summary-key">Spatial Consistency</span>
              <span className="summary-val">{canonicalLayers?.layer4_spatial?.status || 'NORMAL'}</span>
            </div>
            <div className="summary-metric">
              <span className="summary-key">Overall Assessment</span>
              <span className="summary-val text-xs leading-tight">
                {canonicalWeather?.summary || (isAnomaly ? 'Local sensor outlier detected' : 'Operating normally')}
              </span>
            </div>
          </div>
        </div>

        {/* 5. ATHER Insight & Meteorological Analysis (§19.8, §19.9) */}
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

        {/* Operator Insights List */}
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


        {/* 10. Data Quality & Provenance Strip (§19.10) */}
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
