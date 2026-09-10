import React, { useEffect, useState } from 'react';
import { ShieldAlert, Info, Loader2 } from 'lucide-react';
import { AnomaliesSummary } from '../types/weather';
import { fetchIncidents } from '../services/api';
import { AnomalyCard } from '../components/AnomalyCard';
import { IncidentDetail } from '../components/IncidentDetail';

interface AnomaliesWorkspaceProps {
  summary: AnomaliesSummary | null;
  activeIncidentCounts: Record<string, number> | null;
  onViewStation: (stationId: string) => void;
}

// UI tab label -> backend `status` filter. "ACTIVE" surfaces brand-new,
// not-yet-touched incidents (backend status NEW) — Phase 11.
const TABS: { label: string; status: string | null }[] = [
  { label: 'ACTIVE', status: 'NEW' },
  { label: 'ACKNOWLEDGED', status: 'ACKNOWLEDGED' },
  { label: 'INVESTIGATING', status: 'INVESTIGATING' },
  { label: 'ESCALATED', status: 'ESCALATED' },
  { label: 'RESOLVED', status: 'RESOLVED' },
  { label: 'ALL', status: null },
];

/**
 * ATHER ANOMALIES — persistent incident workspace (Phase 11-13). Reads
 * real, backend-persisted incidents (created automatically by the anomaly
 * pipeline — see app/stations/service.py._sync_incident) rather than
 * ephemeral per-request detection output. Master-detail: selecting an
 * incident opens its detail in place, without leaving this workspace or
 * stacking another panel on the map (Phase 37).
 */
export const AnomaliesWorkspace: React.FC<AnomaliesWorkspaceProps> = ({ summary, activeIncidentCounts, onViewStation }) => {
  const [tabIndex, setTabIndex] = useState(0);
  const [incidents, setIncidents] = useState<any[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);

  const tab = TABS[tabIndex];

  const load = () => {
    setIsLoading(true);
    setError(null);
    fetchIncidents(tab.status)
      .then((r) => setIncidents(r.incidents))
      .catch((e) => setError(e.message))
      .finally(() => setIsLoading(false));
  };

  useEffect(() => { load(); }, [tabIndex]);

  if (selectedIncidentId) {
    return (
      <div className="anomalies-workspace">
        <IncidentDetail
          incidentId={selectedIncidentId}
          onBack={() => { setSelectedIncidentId(null); load(); }}
          onViewStation={onViewStation}
        />
      </div>
    );
  }

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
        {TABS.map((t, i) => (
          <button key={t.label} className={`anomalies-tab-btn ${tabIndex === i ? 'active' : ''}`} onClick={() => setTabIndex(i)}>
            {t.label}
            {t.label === 'ACTIVE' && activeIncidentCounts?.new ? <span className="nav-badge-count anomaly">{activeIncidentCounts.new}</span> : null}
          </button>
        ))}
      </div>

      <div className="anomalies-list">
        {isLoading ? (
          <div className="anomalies-empty-state"><Loader2 className="w-4 h-4 animate-spin" /><span>Loading incidents...</span></div>
        ) : error ? (
          <div className="anomalies-empty-state"><Info className="w-4 h-4 text-slate-400" /><span>{error}</span></div>
        ) : !incidents || incidents.length === 0 ? (
          <div className="anomalies-empty-state">
            <Info className="w-4 h-4 text-slate-400" />
            <span>
              {tab.label === 'ACTIVE'
                ? 'No new incidents. All reporting stations are within nominal limits.'
                : `No ${tab.label.toLowerCase()} incidents.`}
            </span>
          </div>
        ) : (
          incidents.map((inc) => (
            <AnomalyCard
              key={inc.incident_id}
              accent={inc.severity === 'CRITICAL' ? 'critical' : inc.severity === 'INFO' ? 'neutral' : 'warning'}
              pillLabel={inc.status}
              stationId={inc.station_id}
              title={`${inc.parameter} anomaly`}
              location={`${inc.station_name || ''} · ${inc.town || ''}`}
              onView={() => setSelectedIncidentId(inc.incident_id)}
              metrics={[
                { label: 'OBSERVED', value: `${inc.observed_value ?? '--'} ${inc.unit ?? ''}` },
                { label: 'CONFIDENCE', value: inc.confidence !== undefined ? `${Math.round(inc.confidence * 100)}%` : '--' },
                { label: 'ROOT CAUSE', value: inc.root_cause ? String(inc.root_cause).replace(/_/g, ' ') : '--' },
              ]}
            />
          ))
        )}
      </div>
    </div>
  );
};
