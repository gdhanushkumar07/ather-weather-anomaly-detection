export interface AnomalyInfo {
  parameter: string;
  observed: number;
  unit: string;
  expectedMin: number;
  expectedMax: number;
  severity: 'LOW' | 'WARNING' | 'HIGH';
  reason: string;
  score?: number;
  confidence?: number;
  rootCause?: string;
  layerScores?: Record<string, number>;
  healthIndex?: number;
  daysToFailure?: number | null;
  explanation?: string;
}

export interface CanonicalLayerCard {
  name: string;
  status: 'PASS' | 'WARNING' | 'ANOMALY' | 'VETO' | 'LIMITED' | 'INSUFFICIENT_DATA' | string;
  score: number;
  evidence_quality?: string;
  reason: string;
  details?: Record<string, any>;
}

// ── Temporal layer (layers.temporal) — mirrors backend engine/layer2_temporal.py
// and lstm_temporal.py output. Fields the backend omits or sets to null are
// typed optional / nullable: null means "no value", never zero.

export type TemporalChannel = 'temperature_c' | 'pressure_hpa' | 'humidity_pct';

export interface TemporalLSTMDetails {
  lstm_available: boolean;
  /** Why the LSTM did not run for this reading, e.g. 'insufficient_valid_history',
   *  'current_observation_incomplete', 'inference_error', or a model load error. */
  lstm_skip_reason?: string | null;
  lstm_predicted_temperature_c?: number | null;
  lstm_predicted_pressure_hpa?: number | null;
  lstm_predicted_humidity_pct?: number | null;
  temperature_residual?: number | null;
  pressure_residual?: number | null;
  humidity_residual?: number | null;
  temperature_abs_residual?: number | null;
  pressure_abs_residual?: number | null;
  humidity_abs_residual?: number | null;
  /** Anomaly-evidence scores in [0,1] — NOT probabilities. */
  temperature_lstm_score?: number | null;
  pressure_lstm_score?: number | null;
  humidity_lstm_score?: number | null;
  temperature_lstm_raw_score?: number | null;
  pressure_lstm_raw_score?: number | null;
  humidity_lstm_raw_score?: number | null;
  lstm_residual_score?: number | null;
  recent_lstm_peak?: number | null;
  recent_lstm_peak_by_channel?: Partial<Record<TemporalChannel, number>>;
  note?: string;
}

/** Present in TemporalDetails only when that rule actually triggered. */
export interface TemporalSpikeEvidence {
  current: number;
  previous: number;
  delta_c?: number;
  delta_hpa?: number;
  interval_s: number;
  max_allowed_c?: number;
  score: number;
}

export interface TemporalFrozenEvidence {
  stuck_value: number;
  window_size: number;
  variance: number;
  score: number;
}

export interface TemporalZScoreEvidence {
  current: number;
  median: number;
  mad: number;
  modified_z: number;
  sample_count: number;
  score: number;
}

export interface TemporalDetails {
  /** 'EVALUATED' | 'INSUFFICIENT_DATA' */
  status?: string;
  note?: string;
  historical_points?: Partial<Record<TemporalChannel, number>>;
  /** Deepest rule-based per-channel history. */
  history_points?: number;
  /** Contiguous jointly-valid observations currently buffered for the LSTM. */
  lstm_history_points?: number;
  lstm_required_history_points?: number;
  lstm?: TemporalLSTMDetails;
  temp_spike?: TemporalSpikeEvidence;
  press_spike?: TemporalSpikeEvidence;
  frozen_temp?: TemporalFrozenEvidence;
  zscore_temperature_c?: TemporalZScoreEvidence;
  zscore_pressure_hpa?: TemporalZScoreEvidence;
  zscore_humidity_pct?: TemporalZScoreEvidence;
}

export interface EvidenceAvailabilityEntry {
  available: boolean;
  reason: string | null;
}

/** Top-level `evidence_availability`: whether each layer could actually
 *  assess this observation (distinct from "assessed and normal"). */
export interface EvidenceAvailability {
  physics?: EvidenceAvailabilityEntry;
  temporal?: EvidenceAvailabilityEntry;
  multivariate?: EvidenceAvailabilityEntry;
  spatial?: EvidenceAvailabilityEntry;
  /** Canonical key for the Sensor Health layer (matches `layers.sensor_health`). */
  sensor_health?: EvidenceAvailabilityEntry;
  /** @deprecated Legacy key used by older backends; read `sensor_health` instead. */
  drift?: EvidenceAvailabilityEntry;
}

export type TemporalLayerCard = Omit<CanonicalLayerCard, 'details'> & {
  details?: TemporalDetails;
};

export interface CanonicalDiagnosis {
  primary: string;
  confidence: 'HIGH' | 'MEDIUM' | 'LOW' | 'INSUFFICIENT_EVIDENCE' | string;
  confidence_level?: string;
  evidence: string[];
  alternatives: string[];
  affected_channels?: string[];
  operator_action?: string;
}

export interface CanonicalWeatherAnalysis {
  summary: string;
  meteorological_context?: string;
  likely_phenomenon?: string;
  confidence?: string;
  evidence?: string[];
}

export interface CanonicalInsight {
  what: string;
  why: string;
  evidence: string;
  action: string;
}

export interface CanonicalDataQuality {
  status: 'VALID' | 'DEGRADED' | 'INSUFFICIENT_DATA' | string;
  valid_fields: string[];
  missing_fields: string[];
  zero_substituted_fields?: string[];
  historical_points: number;
  nearby_stations: number;
  limitations: string[];
}

export interface CanonicalObservation {
  timestamp: string;
  temperature: number | null;
  pressure: number | null;
  relative_humidity: number | null;
  dew_point?: number | null;
  wind_speed: number | null;
  wind_direction?: string | null;
  condition?: string | null;
  /** Verified provenance — 'AWS_IN_SITU' | 'NWP_MODEL_REFERENCE' | 'MISSING' | 'UNKNOWN'.
   *  NEVER assume this is measured AWS telemetry; render conditionally. */
  source: string;
  /** 'LIVE' | 'STALE' | 'UNKNOWN' | 'MISSING' — derived from the real observation
   *  timestamp, never from request time. */
  freshness?: string;
  observation_timestamp?: string | null;
  received_timestamp?: string | null;
}

export interface CanonicalOverall {
  status: 'NORMAL' | 'WARNING' | 'ANOMALY';
  score: number;
  anomaly_score?: number;
  confidence: number;
  threshold?: number;
  severity: 'NONE' | 'LOW' | 'WARNING' | 'HIGH';
}

export interface CanonicalAnalysisResult {
  station: {
    id: string;
    name: string;
    town?: string;
    country?: string;
    region?: string;
    latitude: number;
    longitude: number;
    elevation?: number | null;
  };
  observation: CanonicalObservation;
  overall: CanonicalOverall;
  layers: Record<string, CanonicalLayerCard>;
  diagnosis: CanonicalDiagnosis;
  weather_analysis: CanonicalWeatherAnalysis;
  insights: CanonicalInsight[];
  data_quality: CanonicalDataQuality;
}

export interface StationAnomalyAssessment {
  station_id: string;
  timestamp?: string;
  status: 'NORMAL' | 'WARNING' | 'ANOMALY';
  is_anomaly: boolean;
  anomaly_score: number;
  confidence: number;
  veto_fired?: boolean;
  root_cause: string;
  affected_channels: string[];
  layers: Record<string, any>;
  /** Which layers could actually assess this observation. */
  evidence_availability?: EvidenceAvailability;
  reasons: string[];
  explanation: string;
  sensor_health_index: number;
  estimated_days_to_failure: number | null;
  raw_values?: Record<string, number | null>;
  corrected_values?: Record<string, number | null>;
  operator_action?: string;
  /** 'TELEMETRY_AVAILABLE' | 'TELEMETRY_UNAVAILABLE' — whether a real AWS
   *  sensor feed (not a model reference) is connected for this station. */
  aws_telemetry_status?: string;

  // Canonical Section 16 elements
  station?: {
    id: string;
    name: string;
    town?: string;
    country?: string;
    region?: string;
    latitude: number;
    longitude: number;
    elevation?: number | null;
  };
  observation?: CanonicalObservation;
  overall?: CanonicalOverall;
  diagnosis?: CanonicalDiagnosis;
  weather_analysis?: CanonicalWeatherAnalysis;
  insights?: CanonicalInsight[];
  data_quality?: CanonicalDataQuality;
}

export interface OpenMeteoWeather {
  latitude: number;
  longitude: number;
  temperature: number;
  apparentTemperature?: number;
  humidity: number;
  pressure: number;
  surfacePressure?: number;
  windSpeed: number;
  windGusts?: number;
  windDirectionDeg?: number;
  windDirection: string;
  precipitation: number;
  weatherCode: number;
  condition: string;
  timestamp: string;
  source: string;
}

export interface Station {
  id: string;
  name: string;
  town: string;
  latitude: number;
  longitude: number;
  country: string;
  region: string;
  temperature?: number | null;
  pressure?: number | null;
  humidity?: number | null;
  windSpeed?: number | null;
  windDirection?: string | null;
  condition?: string;
  timestamp: string;
  status: 'NORMAL' | 'WARNING' | 'ANOMALY' | 'OFFLINE';
  anomaly?: AnomalyInfo | null;
}

export interface ObservationPoint {
  timestamp: number;
  timeLabel: string;
  temperature: number;
  pressure: number;
  humidity: number;
  windSpeed: number;
}

export interface ObservationHistory {
  station_id: string;
  hours: number;
  series: ObservationPoint[];
}

export interface AnomaliesSummary {
  totalStations: number;
  normalCount: number;
  warningCount: number;
  anomalyCount: number;
  offlineCount?: number;
  activeAnomalies: Station[];
  activeWarnings: Station[];
}

export type WeatherLayerType = 'stations' | 'temperature' | 'wind' | 'pressure' | 'humidity';

export interface LocationCoords {
  lat: number;
  lon: number;
  name?: string;
  country?: string;
  admin1?: string;
  elevation?: number;
}

export interface AtherStationData {
  station_id: string;
  id?: string;
  name: string;
  town?: string;
  country?: string;
  region?: string;
  lat: number;
  lon: number;
  latitude?: number;
  longitude?: number;
  weather: {
    temperature_c: number;
    humidity_pct?: number;
    pressure_hpa?: number;
    wind_kph?: number;
    condition?: string;
  };
  temperature?: number | null;
  pressure?: number | null;
  humidity?: number | null;
  windSpeed?: number | null;
  windDirection?: string | null;
  condition?: string;
  status: 'NORMAL' | 'WARNING' | 'ANOMALY' | 'OFFLINE';
  anomaly: {
    is_anomaly: boolean;
    severity_score: number;
    severity_label?: string;
    root_cause?: string;
    explanation?: string;
  };
  [key: string]: any;
}

export interface AIAnomalyItem {
  id: string;
  station_id?: string;
  title?: string;
  name?: string;
  level?: 'D0' | 'D1' | 'D2' | 'D3' | 'D4' | 'D5';
  lat: number;
  lon: number;
  riskScore: number;
  category: string;
  desc: string;
  atherData?: AtherStationData;
  [key: string]: any;
}

