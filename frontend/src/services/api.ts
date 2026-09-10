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

// ── ATHER Test Lab (isolated simulation engine) ─────────────────────────

export async function fetchSimulationScenarios(): Promise<{ scenarios: any[] }> {
  const res = await fetch(`${API_BASE}/simulation/scenarios`);
  if (!res.ok) throw new Error(`Failed to fetch simulation scenarios: ${res.statusText}`);
  return res.json();
}

export async function runSimulation(scenarioId: string, baseStationId?: string | null) {
  const res = await fetch(`${API_BASE}/simulation/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario_id: scenarioId, base_station_id: baseStationId || undefined })
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Simulation failed: ${res.statusText}`);
  }
  return res.json();
}

// ── ATHER Incident Workflow (persistent, incident-ID keyed) ──────────────
// Backend is authoritative for status/severity/confidence/evidence — these
// functions only render and request state changes (Phase 44).

export async function fetchIncidents(status?: string | null, stationId?: string): Promise<{ incidents: any[] }> {
  const query = new URLSearchParams();
  if (status) query.set('status', status);
  if (stationId) query.set('station_id', stationId);
  const qs = query.toString();
  const res = await fetch(`${API_BASE}/incidents${qs ? `?${qs}` : ''}`);
  if (!res.ok) throw new Error(`Failed to fetch incidents: ${res.statusText}`);
  return res.json();
}

export async function fetchActiveIncidentCounts(): Promise<Record<string, number>> {
  const res = await fetch(`${API_BASE}/incidents/active-counts`);
  if (!res.ok) throw new Error(`Failed to fetch active incident counts: ${res.statusText}`);
  return res.json();
}

export async function fetchIncidentDetail(incidentId: string) {
  const res = await fetch(`${API_BASE}/incidents/${encodeURIComponent(incidentId)}`);
  if (!res.ok) throw new Error(`Failed to fetch incident ${incidentId}: ${res.statusText}`);
  return res.json();
}

export async function fetchStationIncidents(stationId: string): Promise<{ incidents: any[] }> {
  const res = await fetch(`${API_BASE}/stations/${encodeURIComponent(stationId)}/incidents`);
  if (!res.ok) throw new Error(`Failed to fetch incidents for ${stationId}: ${res.statusText}`);
  return res.json();
}

async function postIncidentAction(incidentId: string, action: string, body?: Record<string, any>) {
  const res = await fetch(`${API_BASE}/incidents/${encodeURIComponent(incidentId)}/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Incident action '${action}' failed: ${res.statusText}`);
  }
  return res.json();
}

export const acknowledgeIncident = (incidentId: string, actor = 'operator') => postIncidentAction(incidentId, 'acknowledge', { actor });
export const investigateIncident = (incidentId: string, actor = 'operator') => postIncidentAction(incidentId, 'investigate', { actor });
export const escalateIncident = (incidentId: string, actor = 'operator') => postIncidentAction(incidentId, 'escalate', { actor });
export const resolveIncident = (incidentId: string, resolutionNotes: string, resolutionType: string, actor = 'operator') =>
  postIncidentAction(incidentId, 'resolve', { actor, resolution_notes: resolutionNotes, resolution_type: resolutionType });
export const dismissIncident = (incidentId: string, dismissalReason: string, actor = 'operator') =>
  postIncidentAction(incidentId, 'dismiss', { actor, dismissal_reason: dismissalReason });

export async function fetchEscalationPreview(incidentId: string) {
  const res = await fetch(`${API_BASE}/incidents/${encodeURIComponent(incidentId)}/escalation-preview`);
  if (!res.ok) throw new Error(`Failed to fetch escalation preview for ${incidentId}: ${res.statusText}`);
  return res.json();
}
