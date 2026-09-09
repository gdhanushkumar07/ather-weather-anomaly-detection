export type WeatherLayerType = 
  | 'none'
  | 'radar'
  | 'satellite'
  | 'wind' 
  | 'rain' 
  | 'temp' 
  | 'clouds' 
  | 'waves'
  | 'rain_accu'
  | 'thunder'
  | 'humidity'
  | 'pressure'
  | 'anomalies';

export type ForecastModel = 'ECMWF' | 'GFS' | 'ICON';

export type AltitudeLevel = 'surface' | '100m' | '850hpa' | '700hpa' | '500hpa' | '300hpa';

export type BaseMapStyle = 'dark' | 'satellite' | 'street' | 'terrain';

export interface LocationCoords {
  lat: number;
  lon: number;
  name?: string;
  country?: string;
}

export interface HourlyForecast {
  time: string;
  hourLabel: string;
  temp: number;
  feelsLike: number;
  precipitation: number;
  rainProb: number;
  weatherCode: number;
  weatherDesc: string;
  windSpeed: number; // km/h
  windGust: number; // km/h
  windDeg: number;
  windDirection: string;
  pressure: number; // hPa
  humidity: number; // %
  dewPoint: number;
  cloudCover: number; // %
  uvIndex: number;
}

export interface DailyForecast {
  date: string;
  dayLabel: string;
  tempMax: number;
  tempMin: number;
  weatherCode: number;
  weatherDesc: string;
  precipitationSum: number;
  windSpeedMax: number;
}

export interface PointForecastData {
  location: {
    lat: number;
    lon: number;
    name: string;
    elevation?: number;
    country?: string;
    timezone?: string;
  };
  current: HourlyForecast;
  hourly: HourlyForecast[];
  daily: DailyForecast[];
  isWindyApi: boolean;
}

export interface AIAnomalyItem {
  id: string;
  stationName: string;
  state: string;
  lat: number;
  lon: number;
  severity: 'D0' | 'D1' | 'D2' | 'D3' | 'D4' | 'D5';
  severityLabel: string;
  status: 'Critical' | 'Severe' | 'Moderate' | 'Healthy';
  anomalyType: 'Drought Deficit' | 'Heatwave Spike' | 'Flash Flood Risk' | 'Cyclonic Inflow' | 'Atmospheric Inversion';
  confidenceScore: number;
  soilMoistureIndex: number; // 0 - 100
  heatAnomalyDelta: number; // °C deviation
  rainfallDeficitPercent: number; // % deviation
  aiRecommendation: string;
  lastUpdated: string;
}

export interface WebcamItem {
  id: string;
  title: string;
  lat: number;
  lon: number;
  thumbnail: string;
  city: string;
  status: 'active' | 'offline';
  updateTime: string;
}

// ────────────────────────────────────────────────────
// ATHER — 5-Layer Anomaly Detection Types
// ────────────────────────────────────────────────────

export interface AtherAnomalyResult {
  is_anomaly: boolean;
  severity_score: number;     // 0.0 – 1.0
  confidence_score: number;   // 0.0 – 1.0
  veto_fired: boolean;
  root_cause: string;         // FaultType enum value
  affected_channels: string[];
  layer_scores: {
    physics: number;
    temporal: number;
    multivariate: number;
    spatial: number;
    drift: number;
  };
  explanation: string;
  raw_values: Record<string, number>;
  corrected_values: Record<string, number>;
  sensor_health_index: number;  // 0 – 100
  estimated_days_to_failure: number | null;
}

export interface AtherWeatherData {
  temperature_c: number;
  pressure_hpa: number;
  humidity_pct: number;
  dew_point_c: number | null;
}

export interface AtherStationData {
  station_id: string;
  name: string;
  lat: number;
  lon: number;
  elevation_m: number;
  timestamp: string;
  weather: AtherWeatherData;
  anomaly: AtherAnomalyResult;
}

export interface AtherStationsResponse {
  status: string;
  timestamp: string;
  station_count: number;
  anomaly_count: number;
  healthy_count: number;
  stations: AtherStationData[];
}

export interface AtherHealthResponse {
  status: string;
  pipeline_ready: boolean;
  adapter_ready: boolean;
  fusion_calibrated: boolean;
  multivariate_fitted: boolean;
  station_count: number;
  data_source: string;
  engine_layers: string[];
  timestamp: string;
}

