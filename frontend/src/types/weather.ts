export interface AnomalyInfo {
  parameter: string;
  observed: number;
  unit: string;
  expectedMin: number;
  expectedMax: number;
  severity: 'LOW' | 'WARNING' | 'HIGH';
  reason: string;
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
