import React, { useEffect, useState } from 'react';
import { ShieldAlert, AlertTriangle, ChevronRight, Info, Loader2 } from 'lucide-react';
import { AnomaliesSummary, Station } from '../types/weather';
import { fetchIncidents } from '../services/api';

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
      <div key={stn.id} className={`anomaly-card ${isCritical ? 'critical' : 'warning'}`}>
        <div className="anomaly-card-severity-bar" />
        <div className="anomaly-card-body">
          <div className="anomaly-card-top">
            <span className={`anomaly-severity-pill ${isCritical ? 'critical' : 'warning'}`}>
              {isCritical ? 'CRITICAL' : 'WARNING'}
            </span>
            <span className="anomaly-card-station-id">{stn.id}</span>
          </div>
          <div className="anomaly-card-title">{a?.parameter || 'Telemetry'} anomaly</div>
          <div className="anomaly-card-location">{stn.name} · {stn.town}</div>
          <div className="anomaly-card-metrics">
            <div>
              <span className="metric-title">OBSERVED</span>
              <div className="metric-val">{a?.observed ?? '--'} {a?.unit ?? ''}</div>
            </div>
            <div>
              <span className="metric-title">CONFIDENCE</span>
              <div className="metric-val">{a?.confidence !== undefined ? `${Math.round(a.confidence * 100)}%` : '--'}</div>
            </div>
            <div>
              <span className="metric-title">ROOT CAUSE</span>
              <div className="metric-val">{a?.rootCause ? a.rootCause.replace(/_/g, ' ') : '--'}</div>
            </div>
          </div>
        </div>
        <button className="anomaly-card-view-btn" onClick={() => onViewStation(stn.id)}>
          VIEW <ChevronRight className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  };

  const renderIncidentCard = (inc: any) => {
    const snap = inc.latest_snapshot || {};
    const isCritical = snap.severity === 'HIGH';
    return (
      <div key={inc.incident_id} className={`anomaly-card ${isCritical ? 'critical' : 'warning'}`}>
        <div className="anomaly-card-severity-bar" />
        <div className="anomaly-card-body">
          <div className="anomaly-card-top">
            <span className={`incident-state-pill ${inc.state}`}>{inc.state}</span>
            <span className="anomaly-card-station-id">{inc.station_id}</span>
          </div>
          <div className="anomaly-card-title">{snap.parameter || 'Telemetry'} anomaly</div>
          <div className="anomaly-card-location">{snap.station_name} · {snap.town}</div>
          <div className="anomaly-card-metrics">
            <div><span className="metric-title">OBSERVED</span><div className="metric-val">{snap.observed ?? '--'} {snap.unit ?? ''}</div></div>
            <div><span className="metric-title">SEVERITY</span><div className="metric-val">{snap.severity ?? '--'}</div></div>
            <div><span className="metric-title">ROOT CAUSE</span><div className="metric-val">{snap.root_cause ? String(snap.root_cause).replace(/_/g, ' ') : '--'}</div></div>
          </div>
        </div>
        <button className="anomaly-card-view-btn" onClick={() => onViewStation(inc.station_id)}>
          VIEW <ChevronRight className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  };

  return (
    <div className="anomalies-workspace">
      <div className="workspace-page-header">
        <div className="workspace-page-title-group">
          <ShieldAlert className="w-5 h-5 text-red-400" />
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
