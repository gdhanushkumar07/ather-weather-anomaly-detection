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
  source: string;
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
  reasons: string[];
  explanation: string;
  sensor_health_index: number;
  estimated_days_to_failure: number | null;
  raw_values?: Record<string, number | null>;
  corrected_values?: Record<string, number | null>;
  operator_action?: string;

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

