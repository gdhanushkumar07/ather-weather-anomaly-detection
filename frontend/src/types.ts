export type WeatherLayer = 
  | 'none'
  | 'temperature' 
  | 'pressure' 
  | 'humidity' 
  | 'wind' 
  | 'rain' 
  | 'radar'
  | 'satellite'
  | 'clouds'
  | 'thunderstorms'
  | 'waves'
  | 'hurricane'
  | 'rain_accum'
  | 'gusts' 
  | 'air_quality' 
  | 'anomaly';

export type AtherSeverity = 'Normal' | 'Watch' | 'Warning' | 'Critical';

export type AnomalyRootCause = 
  | 'None'
  | 'Temperature Sensor Spike'
  | 'Frozen Sensor'
  | 'Sensor Drift'
  | 'Pressure Discontinuity'
  | 'Humidity Inconsistency'
  | 'Missing Data'
  | 'Communication Error'
  | 'Multivariate Inconsistency'
  | 'Spatial Inconsistency'
  | 'Physical Law Violation'
  | 'Genuine Meteorological Event'
  | 'Sensor Fault';

export interface AtherObservation {
  stationId: string;
  timestamp: number;
  isoTime: string;
  temperature: number; // °C
  pressure: number; // hPa
  humidity: number; // % (0-100)
  dewPoint?: number; // °C calculated
  wetBulb?: number; // °C calculated
  seaLevelPressure?: number; // hPa calculated
  windSpeed?: number; // kt (contextual)
  isValid: boolean;
  validationErrors?: string[];
}

export interface AtherLayerScores {
  physicsScore: number;       // 0-100 (0=sound, 100=unphysical)
  temporalScore: number;      // 0-100 (0=normal, 100=spiked/frozen)
  multivariateScore: number;  // 0-100 (0=coupled, 100=inconsistent)
  spatialScore: number;       // 0-100 (0=matches neighbors, 100=isolated)
  sensorHealthScore: number;  // 0-100 (0=pristine, 100=degraded/failing)
}

export interface AtherAnalysisResult {
  stationId: string;
  stationName: string;
  timestamp: number;
  rawObservation: AtherObservation;
  validatedObservation: AtherObservation;
  layerScores: AtherLayerScores;
  anomalyScore: number;       // 0-100 (Fused overall)
  confidence: number;         // 0-100%
  severity: AtherSeverity;
  anomalyType: AnomalyRootCause;
  isGenuineEvent: boolean;    // When neighbors agree with extreme reading
  reasons: string[];          // Transparent explainability bullet points
  evidenceDetails: {
    physicsNote?: string;
    temporalNote?: string;
    multivariateNote?: string;
    spatialNote?: string;
    healthNote?: string;
  };
  correctedEstimate: {
    temperature: number;
    pressure: number;
    humidity: number;
    imputationMethod: string;
  };
  rawPreserved: boolean;
}

export interface AwsStation {
  id: string;
  name: string;
  state: string;
  lat: number;
  lon: number;
  altitude: number; // elevation in meters
  healthPercent: number; // 0-100
  healthStatus: 'healthy' | 'warning' | 'critical' | 'offline';
  healthTrend: 'stable' | 'degrading' | 'recovering';
  maintenanceRisk: 'LOW' | 'MEDIUM' | 'HIGH';
  consecutiveAnomalies: number;
  driftRateDegPerHour: number;
  temp: number; // compatibility alias
  pressure: number; // compatibility alias
  windSpeed: number; // compatibility alias
  humidity: number; // compatibility alias
  status: 'online' | 'degraded' | 'offline';
  currentObs: AtherObservation;
  history: AtherObservation[];
  latestAnalysis?: AtherAnalysisResult;
}

export type AtherMapMode = 'monitoring' | 'anomalies' | 'health';

export type AtherDemoScenario = 
  | 'normal'
  | 'hyd_spike'
  | 'genuine_heatwave'
  | 'frozen_sensor'
  | 'sensor_drift'
  | 'unphysical_combo';

export interface AnomalyMarker {
  id: string;
  title: string;
  level: 'D0' | 'D1' | 'D2' | 'D3' | 'D4' | 'D5';
  lat: number;
  lon: number;
  riskScore: number;
  category: 'temperature' | 'pressure' | 'wind' | 'precipitation';
  desc: string;
}

export type AltitudeLevel = 'surface' | '100m' | '900m' | '3000m' | '5500m' | '9000m' | 'jetstream';

export type StationType = 'airp' | 'wmo' | 'pws' | 'buoy';

export type WeatherModel = 'ecmwf' | 'gfs' | 'icon' | 'meteoblue';

export type MapBasemap = 'dark' | 'satellite' | 'voyager' | 'osm';

export type WindSpeedUnit = 'kt' | 'kmh' | 'ms' | 'mph';
export type TempUnit = 'c' | 'f';
export type PressureUnit = 'hpa' | 'inhg' | 'mmhg';
export type RainUnit = 'mm' | 'in';

export interface LocationCoords {
  lat: number;
  lon: number;
  name?: string;
  country?: string;
  admin1?: string;
  elevation?: number;
}

export interface HourlyForecast {
  time: string; // ISO string
  timestamp: number;
  temp: number; // in Celsius
  feelsLike: number;
  dewPoint: number;
  humidity: number; // percentage
  precipitation: number; // mm
  precipitationProb: number; // percentage
  pressure: number; // hPa
  windSpeed: number; // km/h
  windDirection: number; // degrees 0-360
  windGusts: number; // km/h
  cloudCover: number; // percentage
  uvIndex: number;
  weatherCode: number;
  condition: string;
}

export interface DailyForecast {
  date: string;
  dayName: string;
  tempMax: number;
  tempMin: number;
  precipitationSum: number;
  windSpeedMax: number;
  windDirectionDominant: number;
  weatherCode: number;
  condition: string;
  sunrise: string;
  sunset: string;
}

export interface PointForecastData {
  location: LocationCoords;
  current: HourlyForecast;
  hourly: HourlyForecast[];
  daily: DailyForecast[];
  model: WeatherModel;
  source: 'open-meteo' | 'noaa-isd';
}

export interface GlobalWeatherStation {
  id: string; // e.g. "008268-99999" (USAF-WBAN)
  name: string;
  lat: number;
  lon: number;
  country: string;
  state?: string;
  icao?: string;
  usaf: string;
  wban: string;
  elev?: number;
}

export interface StationLiveWeather {
  stationId: string;
  temperature: number; // °C
  humidity: number; // %
  windSpeed: number; // km/h
  pressure: number; // hPa
  fetchedAt: string; // ISO string
  raw?: any;
}

export interface WebcamItem {
  id: string;
  title: string;
  lat: number;
  lon: number;
  city: string;
  country: string;
  thumbnailUrl: string;
  previewUrl: string;
  status: 'active' | 'offline';
  updatedAt: string;
}

export interface AIAnomalyData {
  level: 'D0' | 'D1' | 'D2' | 'D3' | 'D4' | 'D5';
  title: string;
  description: string;
  riskScore: number; // 0 - 100
  factors: {
    name: string;
    value: string;
    severity: 'normal' | 'moderate' | 'high' | 'critical';
  }[];
  alertMessage?: string;
  timestamp: string;
}

export interface ColorStop {
  value: number;
  color: string;
  label?: string;
}
