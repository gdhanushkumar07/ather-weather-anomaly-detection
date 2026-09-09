import { Station, ObservationHistory, AnomaliesSummary, OpenMeteoWeather } from '../types/weather';

const API_BASE = '/api';

export async function fetchStationsGeoJSON(params?: {
  minLon?: number;
  minLat?: number;
  maxLon?: number;
  maxLat?: number;
  limit?: number;
  status?: string;
}) {
  const query = new URLSearchParams();
  if (params?.minLon !== undefined) query.set('min_lon', params.minLon.toString());
  if (params?.minLat !== undefined) query.set('min_lat', params.minLat.toString());
  if (params?.maxLon !== undefined) query.set('max_lon', params.maxLon.toString());
  if (params?.maxLat !== undefined) query.set('max_lat', params.maxLat.toString());
  if (params?.limit !== undefined) query.set('limit', params.limit.toString());
  if (params?.status) query.set('status', params.status);

  const res = await fetch(`${API_BASE}/stations?${query.toString()}`);
  if (!res.ok) throw new Error(`Failed to fetch stations: ${res.statusText}`);
  return res.json();
}

export async function fetchStationDetails(id: string): Promise<Station> {
  const res = await fetch(`${API_BASE}/stations/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`Failed to fetch station ${id}: ${res.statusText}`);
  return res.json();
}

export async function fetchStationAnomaly(id: string) {
  const res = await fetch(`${API_BASE}/stations/${encodeURIComponent(id)}/anomaly`);
  if (!res.ok) throw new Error(`Failed to fetch anomaly assessment for ${id}: ${res.statusText}`);
  return res.json();
}

export async function fetchStationObservations(id: string, hours = 24): Promise<ObservationHistory> {
  const res = await fetch(`${API_BASE}/stations/${encodeURIComponent(id)}/observations?hours=${hours}`);
  if (!res.ok) throw new Error(`Failed to fetch observations for ${id}: ${res.statusText}`);
  return res.json();
}

export async function fetchCurrentWeather(lat: number, lon: number): Promise<OpenMeteoWeather> {
  const res = await fetch(`${API_BASE}/weather/current?lat=${lat}&lon=${lon}`);
  if (!res.ok) throw new Error(`Failed to fetch current weather: ${res.statusText}`);
  return res.json();
}

export async function fetchAnomaliesSummary(): Promise<AnomaliesSummary> {
  const res = await fetch(`${API_BASE}/anomalies`);
  if (!res.ok) throw new Error(`Failed to fetch anomalies summary: ${res.statusText}`);
  return res.json();
}

export async function searchStations(query: string): Promise<Station[]> {
  if (!query.trim()) return [];
  const res = await fetch(`${API_BASE}/stations/search?q=${encodeURIComponent(query)}`);
  if (!res.ok) throw new Error(`Search failed: ${res.statusText}`);
  return res.json();
}

export async function fetchWeatherGrid(variable: 'temperature' | 'wind' | 'pressure_msl') {
  const res = await fetch(`${API_BASE}/weather/grid?variable=${variable}`);
  if (!res.ok) throw new Error(`Failed to fetch weather grid: ${res.statusText}`);
  return res.json();
}

export async function ingestObservation(payload: any) {
  const res = await fetch(`${API_BASE}/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error(`Ingest failed: ${res.statusText}`);
  return res.json();
}
