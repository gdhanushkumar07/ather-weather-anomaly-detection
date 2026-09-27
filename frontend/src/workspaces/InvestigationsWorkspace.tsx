import React, { useEffect, useMemo, useRef, useState } from 'react';
import { fetchIncidents } from '../services/api';
import { formatAge, useLiveEvents } from '../services/live';
import { Empty, SourceBadge } from '../components/live/LiveBits';
import { InvestigationConsole } from '../components/intel/InvestigationConsole';

interface Props {
  openIncidentId: string | null;
  onOpenIncident: (id: string | null) => void;
  onOpenStation: (id: string) => void;
  onShowOnMap: (id: string) => void;
}

type View = 'open' | 'critical' | 'closed' | 'all';
const VIEWS: [View, string][] = [['open', 'Open'], ['critical', 'Critical'], ['closed', 'Closed'], ['all', 'All']];
const isClosed = (i: any) => i.status === 'RESOLVED' || i.status === 'DISMISSED';
const SEV: Record<string, number> = { CRITICAL: 0, WARNING: 1, INFO: 2 };

/**
 * INVESTIGATIONS — every incident the pipeline opened, and the full
 * investigation for the selected one. Incidents are created by the backend
 * only; this page reads them and requests lifecycle transitions.
 */
export const InvestigationsWorkspace: React.FC<Props> = ({ openIncidentId, onOpenIncident, onOpenStation, onShowOnMap }) => {
  const [all, setAll] = useState<any[] | null>(null);
  const [view, setView] = useState<View>('open');
  const [error, setError] = useState<string | null>(null);
  const last = useRef(0);

  const load = () => fetchIncidents(null).then((r) => setAll(r.incidents || [])).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  useLiveEvents(['INCIDENT_CREATED', 'INCIDENT_UPDATED'], () => {
    if (Date.now() - last.current > 3000) { last.current = Date.now(); load(); }
  });

  const list = useMemo(() => {
    const rows = (all || []).filter((i) =>
      view === 'all' ? true : view === 'closed' ? isClosed(i) : view === 'critical' ? !isClosed(i) && i.severity === 'CRITICAL' : !isClosed(i));
    return rows.sort((a, b) => Number(isClosed(a)) - Number(isClosed(b)) || (SEV[a.severity] ?? 9) - (SEV[b.severity] ?? 9)
      || Date.parse(b.updated_at) - Date.parse(a.updated_at));
  }, [all, view]);

  const counts = useMemo(() => ({
    open: (all || []).filter((i) => !isClosed(i)).length,
    critical: (all || []).filter((i) => !isClosed(i) && i.severity === 'CRITICAL').length,
    closed: (all || []).filter(isClosed).length,
    all: (all || []).length,
  }), [all]);

  // Always show an investigation when there is one to show.
  useEffect(() => {
    if (!openIncidentId && list.length) onOpenIncident(list[0].incident_id);
  }, [openIncidentId, list, onOpenIncident]);

  return (
    <div className="lv-page">
      <div className="lv-page-head">
        <div>
          <div className="a-eyebrow">Investigations</div>
          <h1 className="a-h1">{counts.open} open investigation{counts.open === 1 ? '' : 's'}{counts.critical ? ` · ${counts.critical} critical` : ''}</h1>
          <p className="a-lead">Opened automatically when fused evidence confirms a sensor problem. Weather events corroborated by neighbours never open one.</p>
        </div>
      </div>
      {error && <div className="lv-callout danger">{error}</div>}
      <div className="a-inv">
        <div>
          <div className="lv-tabs" style={{ marginBottom: 8, width: '100%', boxSizing: 'border-box' }}>
            {VIEWS.map(([k, l]) => (
              <button key={k} className={`lv-tab ${view === k ? 'active' : ''}`} style={{ flex: 1, justifyContent: 'center' }} onClick={() => setView(k)}>
                {l} <span className="lv-mono" style={{ fontSize: '0.64rem', color: 'var(--a-ink-3)' }}>{counts[k]}</span>
              </button>
            ))}
          </div>
          <div className="a-inv-list">
            {all === null ? <Empty>Loading…</Empty> : !list.length ? <Empty>No {view === 'all' ? '' : view} investigations.</Empty> : list.map((i) => (
              <button key={i.incident_id} onClick={() => onOpenIncident(i.incident_id)}
                className={`a-inv-item ${i.severity === 'CRITICAL' ? 'critical' : ''} ${isClosed(i) ? 'closed' : ''} ${openIncidentId === i.incident_id ? 'selected' : ''}`}>
                <span className="bar" />
                <span style={{ minWidth: 0 }}>
                  <span className="lv-spread">
                    <span className="a-eyebrow" style={{ fontSize: '0.58rem' }}>{i.severity} · {i.status}</span>
                    <span className="lv-feed-time">{formatAge(i.updated_at)}</span>
                  </span>
                  <div style={{ fontWeight: 700, fontSize: '0.82rem', margin: '3px 0 1px' }}>{i.context?.rca_label || String(i.root_cause || '').replace(/_/g, ' ').toLowerCase()}</div>
                  <div className="lv-muted" style={{ fontSize: '0.72rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {i.parameter} · {i.station_name || i.station_id}
                  </div>
                  {i.source === 'SIMULATED_FEED' && <div style={{ marginTop: 4 }}><SourceBadge simulated /></div>}
                </span>
              </button>
            ))}
          </div>
        </div>
        <div style={{ minWidth: 0 }}>
          {openIncidentId ? (
            <InvestigationConsole incidentId={openIncidentId} onOpenStation={onOpenStation} onShowOnMap={onShowOnMap} />
          ) : (
            <Empty>{all?.length ? 'Select an investigation.' : 'No investigations yet. When ATHER confirms a sensor problem, the full investigation appears here.'}</Empty>
          )}
        </div>
      </div>
    </div>
  );
};
