import React, { useEffect, useState } from 'react';
import { ShieldAlert, Info, Loader2 } from 'lucide-react';
import { AnomaliesSummary, Station } from '../types/weather';
import { fetchIncidents } from '../services/api';
import { AnomalyCard } from '../components/AnomalyCard';

interface AnomaliesWorkspaceProps {
  summary: AnomaliesSummary | null;
  onViewStation: (stationId: string) => void;
}

type Tab = 'ACTIVE' | 'RESOLVED' | 'ALL';

/**
 * ATHER ANOMALIES — dedicated operational workspace (UI architecture
 * restructure, Phase 12). Active tab uses the same real-time summary the
 * rest of the app already fetches (no duplicate data logic, no N+1 station
 * calls). Resolved/All read the incident ledger's tracked records, which is
 * honestly limited to incidents someone has actually opened — see the empty
 * state text.
 */
export const AnomaliesWorkspace: React.FC<AnomaliesWorkspaceProps> = ({ summary, onViewStation }) => {
  const [tab, setTab] = useState<Tab>('ACTIVE');
  const [resolvedIncidents, setResolvedIncidents] = useState<any[] | null>(null);
  const [allIncidents, setAllIncidents] = useState<any[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (tab === 'RESOLVED' && resolvedIncidents === null) {
      setIsLoading(true);
      fetchIncidents('RESOLVED').then((r) => setResolvedIncidents(r.incidents)).finally(() => setIsLoading(false));
    }
    if (tab === 'ALL' && allIncidents === null) {
      setIsLoading(true);
      fetchIncidents().then((r) => setAllIncidents(r.incidents)).finally(() => setIsLoading(false));
    }
  }, [tab, resolvedIncidents, allIncidents]);

  const activeAnomalies: Station[] = summary?.activeAnomalies ?? [];

  const renderActiveCard = (stn: Station) => {
    const a = stn.anomaly;
    const isCritical = a?.severity === 'HIGH';
    return (
      <AnomalyCard
        key={stn.id}
        accent={isCritical ? 'critical' : 'warning'}
        pillLabel={isCritical ? 'CRITICAL' : 'WARNING'}
        stationId={stn.id}
        title={`${a?.parameter || 'Telemetry'} anomaly`}
        location={`${stn.name} · ${stn.town}`}
        onView={() => onViewStation(stn.id)}
        metrics={[
          { label: 'OBSERVED', value: `${a?.observed ?? '--'} ${a?.unit ?? ''}` },
          { label: 'CONFIDENCE', value: a?.confidence !== undefined ? `${Math.round(a.confidence * 100)}%` : '--' },
          { label: 'ROOT CAUSE', value: a?.rootCause ? a.rootCause.replace(/_/g, ' ') : '--' },
        ]}
      />
    );
  };

  const renderIncidentCard = (inc: any) => {
    const snap = inc.latest_snapshot || {};
    const isCritical = snap.severity === 'HIGH';
    return (
      <AnomalyCard
        key={inc.incident_id}
        accent={isCritical ? 'critical' : 'warning'}
        pillLabel={inc.state}
        stationId={inc.station_id}
        title={`${snap.parameter || 'Telemetry'} anomaly`}
        location={`${snap.station_name} · ${snap.town}`}
        onView={() => onViewStation(inc.station_id)}
        metrics={[
          { label: 'OBSERVED', value: `${snap.observed ?? '--'} ${snap.unit ?? ''}` },
          { label: 'SEVERITY', value: snap.severity ?? '--' },
          { label: 'ROOT CAUSE', value: snap.root_cause ? String(snap.root_cause).replace(/_/g, ' ') : '--' },
        ]}
      />
    );
  };

  return (
    <div className="anomalies-workspace">
      <div className="workspace-page-header">
        <div className="workspace-page-title-group">
          <div className="workspace-page-icon-badge"><ShieldAlert className="w-4 h-4 text-red-400" /></div>
          <div>
            <div className="workspace-page-title">ATHER ANOMALIES</div>
            <div className="workspace-page-subtitle">Operational anomaly management — evidence, root cause, and incident actions.</div>
          </div>
        </div>
      </div>

      <div className="anomalies-tabs-row">
        {(['ACTIVE', 'RESOLVED', 'ALL'] as Tab[]).map((t) => (
          <button key={t} className={`anomalies-tab-btn ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {t}
            {t === 'ACTIVE' && activeAnomalies.length > 0 && <span className="nav-badge-count anomaly">{activeAnomalies.length}</span>}
          </button>
        ))}
      </div>

      <div className="anomalies-list">
        {tab === 'ACTIVE' && (
          activeAnomalies.length === 0 ? (
            <div className="anomalies-empty-state">
              <Info className="w-4 h-4 text-slate-400" />
              <span>No active anomalies. All reporting stations are within nominal limits.</span>
            </div>
          ) : (
            activeAnomalies.map(renderActiveCard)
          )
        )}

        {tab === 'RESOLVED' && (
          isLoading ? (
            <div className="anomalies-empty-state"><Loader2 className="w-4 h-4 animate-spin" /><span>Loading resolved incidents...</span></div>
          ) : !resolvedIncidents || resolvedIncidents.length === 0 ? (
            <div className="anomalies-empty-state">
              <Info className="w-4 h-4 text-slate-400" />
              <span>No resolved incidents tracked yet. Only incidents an operator has opened and resolved from Station Intelligence appear here.</span>
            </div>
          ) : (
            resolvedIncidents.map(renderIncidentCard)
          )
        )}

        {tab === 'ALL' && (
          isLoading ? (
            <div className="anomalies-empty-state"><Loader2 className="w-4 h-4 animate-spin" /><span>Loading incidents...</span></div>
          ) : !allIncidents || allIncidents.length === 0 ? (
            <div className="anomalies-empty-state">
              <Info className="w-4 h-4 text-slate-400" />
              <span>No incidents tracked yet.</span>
            </div>
          ) : (
            allIncidents.map(renderIncidentCard)
          )
        )}
      </div>
    </div>
  );
};
