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

/** Incident sources shown operationally: real AWS telemetry and the clearly
 *  labelled simulated feed. Static-snapshot and Test Lab records are excluded. */
export const OPERATIONAL_INCIDENT_SOURCES = 'LIVE_AWS,SIMULATED_FEED';

export async function fetchIncidents(status?: string | null, stationId?: string, source: string = OPERATIONAL_INCIDENT_SOURCES): Promise<{ incidents: any[] }> {
  const query = new URLSearchParams();
  if (status) query.set('status', status);
  if (stationId) query.set('station_id', stationId);
  if (source) query.set('source', source);
  const qs = query.toString();
  const res = await fetch(`${API_BASE}/incidents${qs ? `?${qs}` : ''}`);
  if (!res.ok) throw new Error(`Failed to fetch incidents: ${res.statusText}`);
  return res.json();
}

export async function fetchActiveIncidentCounts(): Promise<Record<string, number>> {
  const res = await fetch(`${API_BASE}/incidents/active-counts?source=${OPERATIONAL_INCIDENT_SOURCES}`);
  if (!res.ok) throw new Error(`Failed to fetch active incident counts: ${res.statusText}`);
  return res.json();
}

export async function fetchIncidentDetail(incidentId: string) {
  const res = await fetch(`${API_BASE}/incidents/${encodeURIComponent(incidentId)}`);
  if (!res.ok) throw new Error(`Failed to fetch incident ${incidentId}: ${res.statusText}`);
  return res.json();
}

export async function fetchStationIncidents(stationId: string): Promise<{ incidents: any[] }> {
  const res = await fetch(`${API_BASE}/stations/${encodeURIComponent(stationId)}/incidents?source=${OPERATIONAL_INCIDENT_SOURCES}`);
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

// ── ATHER real-time pipeline ─────────────────────────────────────────────
// The dashboard loads /network/state once and then applies SSE events
// (services/live.tsx). Everything below is fetched on demand per view.

async function getJSON<T = any>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `${path}: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function sendJSON<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : `${method} ${path} failed (${res.status})`);
  }
  return res.json();
}

export const fetchNetworkState = () => getJSON('/network/state');
export const fetchSystemHealth = () => getJSON('/system/health');
export const fetchStationLive = (id: string) => getJSON(`/stations/${encodeURIComponent(id)}/live`);
export const fetchStationTimeseries = (id: string, hours = 6, maxPoints = 360) =>
  getJSON(`/stations/${encodeURIComponent(id)}/timeseries?hours=${hours}&max_points=${maxPoints}`);
export const fetchStationDetections = (id: string, hours = 6) =>
  getJSON(`/stations/${encodeURIComponent(id)}/detections?hours=${hours}`);
export const fetchStationSpatial = (id: string, parameter = 'temperature', minutes = 60, radiusKm = 60) =>
  getJSON(`/stations/${encodeURIComponent(id)}/spatial?parameter=${parameter}&minutes=${minutes}&radius_km=${radiusKm}`);
export const fetchDetection = (detectionId: string) => getJSON(`/detections/${encodeURIComponent(detectionId)}`);

export const fetchFaultTypes = () => getJSON('/lab/fault-types');
export const fetchFaults = (active = false) => getJSON(`/lab/faults${active ? '?active=true' : ''}`);
export const injectFault = (body: {
  station_id: string; fault_type: string; parameter?: string | null; severity: string; duration_minutes: number; radius_km?: number;
}) => sendJSON('POST', '/lab/faults', body);
export const cancelFault = (faultId: string) => sendJSON('DELETE', `/lab/faults/${encodeURIComponent(faultId)}`);
export const startReplay = (body: Record<string, unknown>) => sendJSON('POST', '/replay', body);
export const fetchReplay = (replayId: string) => getJSON(`/replay/${encodeURIComponent(replayId)}`);
