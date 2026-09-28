import React, { useEffect, useState } from 'react';
import { LiveEvent, formatAge, useLive } from '../../services/live';
import { Empty, SourceBadge, pct } from './LiveBits';

/** Re-render every second so relative ages ("12s ago") stay honest. */
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

// ── event feed ───────────────────────────────────────────────────────────
function describe(e: LiveEvent): { cls: string; kind: string; title: string; text: string; stationId?: string; incidentId?: string } {
  const d = e.data || {};
  switch (e.type) {
    case 'ANOMALY_DETECTED':
      return {
        cls: d.overall_status === 'anomaly' ? 'anomaly' : 'suspect',
        kind: `${d.escalation ? 'Escalated to ' : ''}${d.overall_status === 'anomaly' ? 'Anomaly' : 'Suspect'} · ${pct(d.confidence)}`,
        title: `${d.station_id} — ${d.rca_label || d.root_cause}`,
        text: d.summary, stationId: d.station_id,
      };
    case 'WEATHER_EVENT_DETECTED':
      return { cls: 'weather', kind: 'Weather event · no incident', title: `${d.station_id} — neighbours corroborate`, text: d.summary, stationId: d.station_id };
    case 'STATION_RECOVERED':
      return { cls: 'recovered', kind: 'Recovered', title: `${d.station_id} back to nominal`, text: d.summary, stationId: d.station_id };
    case 'STATION_STALE':
      return { cls: 'system', kind: 'Stale telemetry', title: `${d.station_id} silent ${d.silent_s}s`, text: d.summary, stationId: d.station_id };
    case 'INCIDENT_CREATED':
      return { cls: 'incident', kind: `Incident opened · ${String(d.severity).toLowerCase()}`, title: `${d.station_name || d.station_id} — ${d.rca_label || String(d.root_cause).replace(/_/g, ' ').toLowerCase()}`, text: `${d.parameter} · ${d.incident_id} · ${pct(d.confidence)} confidence`, stationId: d.station_id, incidentId: d.incident_id };
    case 'INCIDENT_UPDATED':
      return { cls: 'incident', kind: `Incident updated · ${String(d.status || '').toLowerCase()}`, title: `${d.station_name || d.station_id} — ${d.rca_label || String(d.root_cause).replace(/_/g, ' ').toLowerCase()}`, text: `${String(d.severity).toLowerCase()} · ${d.observation_count} observation(s) · ${d.incident_id}`, stationId: d.station_id, incidentId: d.incident_id };
    case 'FAULT_INJECTED':
      return { cls: 'system', kind: 'Test Lab · fault injected', title: `${d.label} → ${d.station_name || d.station_id}`, text: `${d.parameter || 'station'} · ${d.severity} · ${Math.round(d.duration_s / 60)} min. Expect ${d.expected_layers?.join(', ') || 'freshness monitor'}.`, stationId: d.station_id };
    case 'FAULT_CLEARED':
      return { cls: 'recovered', kind: `Test Lab · fault ${String(d.state || '').toLowerCase()}`, title: `${d.label} on ${d.station_id}`, text: 'Injected fault no longer applied.', stationId: d.station_id };
    case 'DATA_SOURCE_STATUS_CHANGED':
      return { cls: 'system', kind: 'Data source', title: `${d.label}: ${d.state}`, text: d.reason || d.note || '' };
    default:
      return { cls: 'system', kind: e.type, title: '', text: '' };
  }
}

export const LiveEventFeed: React.FC<{
  onSelectStation?: (id: string) => void;
  onOpenIncident?: (id: string) => void;
  limit?: number;
  stationFilter?: string;
}> = ({ onSelectStation, onOpenIncident, limit = 40, stationFilter }) => {
  const { feed } = useLive();
  const now = useNow(5000);
  // One row per investigation update stream: keep only its most recent update.
  const seenUpdates = new Set<string>();
  const items = feed
    .filter((e) => !stationFilter || e.data?.station_id === stationFilter)
    .filter((e) => {
      if (e.type !== 'INCIDENT_UPDATED') return true;
      const id = e.data?.incident_id;
      if (seenUpdates.has(id)) return false;
      seenUpdates.add(id);
      return true;
    })
    .slice(0, limit);
  if (!items.length) {
    return <Empty>No events yet. New anomalies, incidents and weather events appear here the moment the backend detects them.</Empty>;
  }
  return (
    <div className="lv-feed">
      {items.map((e) => {
        const d = describe(e);
        return (
          <button
            key={`${e.id}-${e.type}`}
            className={`lv-feed-item ${d.cls}`}
            onClick={() => (d.incidentId && onOpenIncident ? onOpenIncident(d.incidentId) : d.stationId && onSelectStation?.(d.stationId))}
          >
            <span className="lv-feed-bar" />
            <span>
              <span className="lv-feed-top">
                <span className="lv-feed-kind">{d.kind}</span>
                <span className="lv-feed-time" title={new Date(e.ts * 1000).toISOString()}>{formatAge(e.ts, now)}</span>
              </span>
              <div className="lv-feed-title">{d.title}</div>
              {d.text && <div className="lv-feed-text">{d.text}</div>}
              {e.data?.triggered_layers && (
                <div style={{ marginTop: 4 }} className="lv-row">
                  {/* only layers that produced evidence — never imply the others passed */}
                  <span className="lv-mono" style={{ fontSize: '0.64rem', color: 'var(--a-ink-3)' }}>
                    {e.data.triggered_layers.length ? `evidence: ${e.data.triggered_layers.join(' ')}` : 'no layer evidence'}
                  </span>
                  {e.data.simulated && <SourceBadge simulated />}
                </div>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
};
