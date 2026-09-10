import { AtherStationData, AIAnomalyItem } from '../types/weather';

export function getSeverityStyle(station: any): {
  color: string;
  statusText: string;
  bg: string;
  ringColor: string;
} {
  const isAnomaly = station.anomaly?.is_anomaly || station.status === 'ANOMALY';
  const severityScore = station.anomaly?.severity_score ?? (isAnomaly ? 0.85 : 0.0);
  const isWarning = station.status === 'WARNING' || (severityScore > 0.3 && !isAnomaly);
  const isOffline = station.status === 'OFFLINE';

  if (isOffline) {
    return {
      color: '#64748b',
      statusText: 'OFFLINE',
      bg: 'rgba(100, 116, 139, 0.2)',
      ringColor: 'rgba(100, 116, 139, 0.4)',
    };
  }

  if (isAnomaly || severityScore >= 0.7) {
    return {
      color: '#ef4444',
      statusText: 'ANOMALY (High Risk)',
      bg: 'rgba(239, 68, 68, 0.2)',
      ringColor: 'rgba(239, 68, 68, 0.6)',
    };
  }

  if (isWarning || severityScore >= 0.3) {
    return {
      color: '#f59e0b',
      statusText: 'WARNING (Elevated)',
      bg: 'rgba(245, 158, 11, 0.2)',
      ringColor: 'rgba(245, 158, 11, 0.6)',
    };
  }

  return {
    color: '#00e5ff',
    statusText: 'NORMAL (Optimal)',
    bg: 'rgba(0, 229, 255, 0.2)',
    ringColor: 'rgba(0, 229, 255, 0.5)',
  };
}

export function toAnomalyItem(station: any): AIAnomalyItem & { atherData: AtherStationData } {
  const isAnomaly = station.anomaly?.is_anomaly || station.status === 'ANOMALY';
  const severityScore = station.anomaly?.severity_score ?? (isAnomaly ? 0.85 : 0.1);
  const stationId = station.station_id || station.id || 'station';

  const normalizedStation: AtherStationData = {
    station_id: stationId,
    id: stationId,
    name: station.name || `Station ${stationId}`,
    town: station.town || '',
    country: station.country || '',
    region: station.region || '',
    lat: station.lat ?? station.latitude ?? 0,
    lon: station.lon ?? station.longitude ?? 0,
    latitude: station.lat ?? station.latitude ?? 0,
    longitude: station.lon ?? station.longitude ?? 0,
    weather: {
      temperature_c: station.weather?.temperature_c ?? station.temperature ?? 25.0,
      humidity_pct: station.weather?.humidity_pct ?? station.humidity ?? 60,
      pressure_hpa: station.weather?.pressure_hpa ?? station.pressure ?? 1013.2,
      wind_kph: station.weather?.wind_kph ?? station.windSpeed ?? 10.0,
      condition: station.weather?.condition ?? station.condition ?? 'Normal',
    },
    temperature: station.weather?.temperature_c ?? station.temperature ?? 25.0,
    pressure: station.weather?.pressure_hpa ?? station.pressure ?? 1013.2,
    humidity: station.weather?.humidity_pct ?? station.humidity ?? 60,
    windSpeed: station.weather?.wind_kph ?? station.windSpeed ?? 10.0,
    windDirection: station.windDirection ?? 'N',
    condition: station.condition ?? 'Normal',
    status: station.status ?? (isAnomaly ? 'ANOMALY' : 'NORMAL'),
    anomaly: {
      is_anomaly: isAnomaly,
      severity_score: severityScore,
      severity_label: station.anomaly?.severity_label || (isAnomaly ? 'HIGH' : 'NORMAL'),
      root_cause: station.anomaly?.root_cause || (isAnomaly ? 'Sensor Anomaly' : 'None'),
      explanation: station.anomaly?.explanation || 'Telemetry stream analyzed by 5-Layer conformal detector.',
    },
  };

  return {
    id: stationId,
    station_id: stationId,
    name: normalizedStation.name,
    title: normalizedStation.name,
    level: isAnomaly ? 'D3' : 'D0',
    lat: normalizedStation.lat,
    lon: normalizedStation.lon,
    riskScore: Math.round(severityScore * 100),
    category: 'temperature',
    desc: normalizedStation.anomaly.explanation || 'Observation within nominal range',
    atherData: normalizedStation,
  };
}
