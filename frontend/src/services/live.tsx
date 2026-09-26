import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { fetchNetworkState } from './api';

/**
 * ATHER live network state.
 *
 * One EventSource per browser tab. On mount: GET /api/network/state (the
 * snapshot carries event_seq), then subscribe to /api/stream?since=event_seq
 * so no event between snapshot and subscription is lost. Afterwards state is
 * only ever updated incrementally from events — the browser never polls
 * stations. A RESYNC_REQUIRED event (slow client / gap) triggers a fresh
 * snapshot. EventSource reconnects on its own and resends Last-Event-ID.
 */

export type OverallStatus = 'nominal' | 'suspect' | 'degraded' | 'anomaly';

export interface LiveStation {
  station_id: string;
  name?: string;
  latitude?: number;
  longitude?: number;
  source?: string;
  simulated?: boolean;
  overall_status: OverallStatus;
  engine_status?: string;
  interpretation?: string;
  confidence?: number;
  severity?: string;
  root_cause?: string;
  rca_label?: string;
  triggered_layers?: string[];
  values?: Record<string, number | null>;
  last_observed_at?: string;
  last_processed_at?: string;
  freshness?: string;
  active_incident_id?: string | null;
  detection_id?: string;
  summary?: string;
  injected_fault?: any;
  watch?: boolean;
}

export interface LiveEvent {
  id: number;
  type: string;
  ts: number;
  data: any;
}

export type ConnectionState = 'connecting' | 'live' | 'reconnecting' | 'offline';

const FEED_TYPES = new Set([
  'ANOMALY_DETECTED', 'WEATHER_EVENT_DETECTED', 'STATION_RECOVERED', 'STATION_STALE',
  'INCIDENT_CREATED', 'INCIDENT_UPDATED', 'FAULT_INJECTED', 'FAULT_CLEARED', 'DATA_SOURCE_STATUS_CHANGED',
]);
const ALL_TYPES = [
  ...FEED_TYPES, 'STATION_UPDATED', 'SYSTEM_METRICS', 'REPLAY_STEP', 'REPLAY_COMPLETED', 'PROCESSING_ERROR', 'RESYNC_REQUIRED',
];

interface LiveContextValue {
  connection: ConnectionState;
  pipelineAvailable: boolean;
  stations: Map<string, LiveStation>;
  /** Increments (at most ~1/s) whenever station state changed — cheap memo key. */
  stationsVersion: number;
  counts: Record<string, number> | null;
  incidentCounts: Record<string, number> | null;
  system: any | null;
  feed: LiveEvent[];
  lastEventAt: number | null;
  subscribe: (fn: (e: LiveEvent) => void) => () => void;
  resync: () => void;
}

const LiveContext = createContext<LiveContextValue | null>(null);

function recount(stations: Map<string, LiveStation>, catalogueTotal?: number) {
  const c: Record<string, number> = {
    live_stations: 0, nominal: 0, suspect: 0, degraded: 0, anomaly: 0, stale: 0, watch: 0, weather_events: 0, simulated: 0, measured: 0,
  };
  stations.forEach((s) => {
    c.live_stations += 1;
    c[s.overall_status] = (c[s.overall_status] || 0) + 1;
    if (s.freshness === 'STALE') c.stale += 1;
    if (s.watch) c.watch += 1;
    if (s.interpretation === 'likely_weather_event') c.weather_events += 1;
    c[s.simulated ? 'simulated' : 'measured'] += 1;
  });
  if (catalogueTotal !== undefined) c.catalogue_total = catalogueTotal;
  return c;
}

export const LiveNetworkProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [connection, setConnection] = useState<ConnectionState>('connecting');
  const [pipelineAvailable, setPipelineAvailable] = useState(true);
  const [stationsVersion, setStationsVersion] = useState(0);
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [incidentCounts, setIncidentCounts] = useState<Record<string, number> | null>(null);
  const [system, setSystem] = useState<any | null>(null);
  const [feed, setFeed] = useState<LiveEvent[]>([]);
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);

  const stationsRef = useRef<Map<string, LiveStation>>(new Map());
  const catalogueTotal = useRef<number | undefined>(undefined);
  const listeners = useRef<Set<(e: LiveEvent) => void>>(new Set());
  const esRef = useRef<EventSource | null>(null);
  const dirty = useRef(false);
  const [resyncNonce, setResyncNonce] = useState(0);

  // Batch station-state renders to at most one per second: a 300-station
  // network emits ~5 STATION_UPDATED events/s and the map only needs 1 Hz.
  useEffect(() => {
    const t = setInterval(() => {
      if (!dirty.current) return;
      dirty.current = false;
      setStationsVersion((v) => v + 1);
      setCounts(recount(stationsRef.current, catalogueTotal.current));
    }, 1000);
    return () => clearInterval(t);
  }, []);

  const subscribe = useCallback((fn: (e: LiveEvent) => void) => {
    listeners.current.add(fn);
    return () => { listeners.current.delete(fn); };
  }, []);

  const resync = useCallback(() => setResyncNonce((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setConnection((c) => (c === 'live' ? 'reconnecting' : 'connecting'));

    const handle = (type: string, raw: MessageEvent) => {
      let data: any;
      try { data = JSON.parse(raw.data); } catch { return; }
      const ev: LiveEvent = { id: Number(raw.lastEventId) || 0, type, ts: (data._ts ?? Date.now() / 1000), data };
      setLastEventAt(Date.now());
      if (type === 'RESYNC_REQUIRED') { resync(); return; }
      if (type === 'STATION_UPDATED') {
        stationsRef.current.set(data.station_id, data);
        dirty.current = true;
      } else if (type === 'SYSTEM_METRICS') {
        setSystem(data);
        if (data?.counts?.catalogue_total) catalogueTotal.current = data.counts.catalogue_total;
      } else if (type === 'INCIDENT_CREATED' || type === 'INCIDENT_UPDATED') {
        // Refresh the counters from the authoritative API rather than guess.
        import('./api').then(({ fetchActiveIncidentCounts }) =>
          fetchActiveIncidentCounts().then((c) => !cancelled && setIncidentCounts(c)).catch(() => {}));
      }
      if (FEED_TYPES.has(type)) {
        setFeed((f) => [ev, ...f].slice(0, 150));
      }
      listeners.current.forEach((fn) => { try { fn(ev); } catch (e) { console.error(e); } });
    };

    fetchNetworkState()
      .then((snap) => {
        if (cancelled) return;
        setPipelineAvailable(true);
        const m = new Map<string, LiveStation>();
        (snap.stations || []).forEach((s: LiveStation) => m.set(s.station_id, s));
        stationsRef.current = m;
        catalogueTotal.current = snap.counts?.catalogue_total;
        setCounts(snap.counts);
        setIncidentCounts(snap.incident_counts);
        setSystem(snap.system);
        setFeed((snap.recent_events || []).map((e: any) => ({ id: e.id, type: e.type, ts: e.ts, data: e.data })));
        setStationsVersion((v) => v + 1);

        esRef.current?.close();
        const es = new EventSource(`/api/stream?since=${snap.event_seq}`);
        esRef.current = es;
        es.onopen = () => !cancelled && setConnection('live');
        es.onerror = () => !cancelled && setConnection(es.readyState === EventSource.CLOSED ? 'offline' : 'reconnecting');
        ALL_TYPES.forEach((t) => es.addEventListener(t, (e) => handle(t, e as MessageEvent)));
      })
      .catch(() => {
        if (cancelled) return;
        setPipelineAvailable(false);
        setConnection('offline');
        setTimeout(() => !cancelled && resync(), 10000);
      });

    return () => {
      cancelled = true;
      esRef.current?.close();
      esRef.current = null;
    };
  }, [resyncNonce, resync]);

  const value = useMemo<LiveContextValue>(() => ({
    connection, pipelineAvailable, stations: stationsRef.current, stationsVersion, counts, incidentCounts,
    system, feed, lastEventAt, subscribe, resync,
  }), [connection, pipelineAvailable, stationsVersion, counts, incidentCounts, system, feed, lastEventAt, subscribe, resync]);

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
};

export function useLive(): LiveContextValue {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error('useLive must be used inside LiveNetworkProvider');
  return ctx;
}

/** Calls `fn` for every live event of the given types (stable across renders). */
export function useLiveEvents(types: string[], fn: (e: LiveEvent) => void) {
  const { subscribe } = useLive();
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const key = types.join(',');
  useEffect(() => {
    const wanted = new Set(key.split(','));
    return subscribe((e) => { if (wanted.has(e.type)) fnRef.current(e); });
  }, [subscribe, key]);
}

/** Maps the pipeline's sensor-trust status onto the map layer's vocabulary. */
export function mapStatus(s: OverallStatus | undefined): 'NORMAL' | 'WARNING' | 'ANOMALY' {
  if (s === 'anomaly') return 'ANOMALY';
  if (s === 'suspect' || s === 'degraded') return 'WARNING';
  return 'NORMAL';
}

export function formatAge(iso?: string | number | null, now = Date.now()): string {
  if (!iso) return '—';
  const t = typeof iso === 'number' ? iso * (iso < 1e12 ? 1000 : 1) : Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return h < 48 ? `${h}h ${m % 60}m ago` : `${Math.floor(h / 24)}d ago`;
}

export const STATUS_LABEL: Record<string, string> = {
  nominal: 'Nominal', suspect: 'Suspect', degraded: 'Degraded', anomaly: 'Anomaly',
};

export const INTERPRETATION_LABEL: Record<string, string> = {
  nominal: 'Nominal',
  likely_sensor_fault: 'Likely sensor fault',
  likely_weather_event: 'Likely weather event',
  communication_issue: 'Communication issue',
  uncertain: 'Uncertain',
};
