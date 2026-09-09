import type { PointForecastData, AIAnomalyItem, WebcamItem, AtherStationsResponse, AtherHealthResponse } from '../types/weather';

const API_BASE = ''; // proxied via Vite to http://localhost:3001 in dev

export async function fetchPointForecast(lat: number, lon: number, name?: string, model: string = 'ecmwf'): Promise<PointForecastData> {
  const params = new URLSearchParams({
    lat: lat.toString(),
    lon: lon.toString(),
    model,
  });
  if (name) params.append('name', name);

  const res = await fetch(`${API_BASE}/api/forecast/point?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch point forecast: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchAnomalies(): Promise<{ summary: any; stations: AIAnomalyItem[] }> {
  const res = await fetch(`${API_BASE}/api/anomalies`);
  if (!res.ok) {
    throw new Error(`Failed to fetch anomalies: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchWebcams(lat: number, lon: number): Promise<WebcamItem[]> {
  const res = await fetch(`${API_BASE}/api/webcams?lat=${lat}&lon=${lon}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch webcams: ${res.statusText}`);
  }
  const data = await res.json();
  return data.webcams || [];
}

export async function fetchBackendStatus(): Promise<{
  status: string;
  hasPointForecastKey: boolean;
  hasMapForecastKey: boolean;
  hasWebcamsKey: boolean;
  mode: string;
}> {
  try {
    const res = await fetch(`${API_BASE}/api/status`);
    if (!res.ok) throw new Error('Status failed');
    return res.json();
  } catch {
    return {
      status: 'offline',
      hasPointForecastKey: false,
      hasMapForecastKey: false,
      hasWebcamsKey: false,
      mode: 'Client-Only Simulation',
    };
  }
}

export interface GeocodeResult {
  display_name: string;
  name: string;
  lat: string;
  lon: string;
  type?: string;
  address?: {
    city?: string;
    state?: string;
    country?: string;
  };
}

export async function searchLocations(query: string): Promise<GeocodeResult[]> {
  if (!query || query.trim().length < 2) return [];
  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=6&addressdetails=1`,
      { headers: { 'Accept-Language': 'en' } }
    );
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

// ────────────────────────────────────────────────────
// ATHER — Live Station & Anomaly Detection API
// ────────────────────────────────────────────────────

/**
 * Fetches all ATHER-monitored stations with real-time weather data
 * and 5-layer anomaly detection results from the Python backend.
 */
export async function fetchAtherStations(): Promise<AtherStationsResponse> {
  try {
    const res = await fetch(`${API_BASE}/api/ather/stations`);
    if (!res.ok) {
      throw new Error(`ATHER backend returned ${res.status}`);
    }
    return res.json();
  } catch {
    return {
      status: 'offline',
      timestamp: new Date().toISOString(),
      station_count: 0,
      anomaly_count: 0,
      healthy_count: 0,
      stations: [],
    };
  }
}

/**
 * Fetches ATHER system health status.
 */
export async function fetchAtherHealth(): Promise<AtherHealthResponse> {
  try {
    const res = await fetch(`${API_BASE}/api/ather/health`);
    if (!res.ok) throw new Error('Health check failed');
    return res.json();
  } catch {
    return {
      status: 'offline',
      pipeline_ready: false,
      adapter_ready: false,
      fusion_calibrated: false,
      multivariate_fitted: false,
      station_count: 0,
      data_source: 'unavailable',
      engine_layers: [],
      timestamp: new Date().toISOString(),
    };
  }
}

