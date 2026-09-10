import React, { useEffect, useState } from 'react';
import {
  ArrowLeft, UserCheck, Search as InvestigateIcon, Siren, XCircle, ExternalLink,
} from 'lucide-react';
import {
  fetchIncidentDetail, acknowledgeIncident, investigateIncident, resolveIncident, dismissIncident,
} from '../services/api';
import { EscalationPreviewModal } from './EscalationPreviewModal';
import { ResolveIncidentModal } from './ResolveIncidentModal';
import { DismissIncidentModal } from './DismissIncidentModal';

const VALID_TRANSITIONS: Record<string, string[]> = {
  NEW: ['ACKNOWLEDGED', 'DISMISSED'],
  ACKNOWLEDGED: ['INVESTIGATING', 'DISMISSED'],
  INVESTIGATING: ['ESCALATED', 'RESOLVED', 'DISMISSED'],
  ESCALATED: ['RESOLVED', 'DISMISSED'],
  RESOLVED: [],
  DISMISSED: [],
};

const LAYER_ORDER = [
  { key: 'physics', label: 'L1 Physics' },
  { key: 'temporal', label: 'L2 Temporal' },
  { key: 'multivariate', label: 'L3 Multivariate' },
  { key: 'spatial', label: 'L4 Spatial' },
  { key: 'sensor_health', label: 'L5 Sensor Health' },
];

interface IncidentDetailProps {
  incidentId: string;
  onBack: () => void;
  onViewStation: (stationId: string) => void;
}

/**
 * ATHER Incident Detail (Phase 13/39-42) — reached from the Anomalies
 * workspace's incident list. Backend is authoritative for every field
 * shown here; this component only renders and requests transitions.
 */
export const IncidentDetail: React.FC<IncidentDetailProps> = ({ incidentId, onBack, onViewStation }) => {
  const [incident, setIncident] = useState<any | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showEscalation, setShowEscalation] = useState(false);
  const [showResolve, setShowResolve] = useState(false);
  const [showDismiss, setShowDismiss] = useState(false);

  const load = () => {
    setIsLoading(true);
    fetchIncidentDetail(incidentId)
      .then(setIncident)
      .catch((e) => setError(e.message))
      .finally(() => setIsLoading(false));
  };

  useEffect(() => { load(); }, [incidentId]);

  const allowedNext = (target: string) => incident && (VALID_TRANSITIONS[incident.status]?.includes(target) ?? false);

  const runAction = async (fn: () => Promise<any>) => {
    setIsBusy(true);
    setError(null);
    try {
      const updated = await fn();
      setIncident(updated);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setIsBusy(false);
    }
  };

  if (isLoading) {
    return <div className="incident-detail-loading">Loading incident...</div>;
  }
  if (!incident) {
    return (
      <div className="incident-detail-loading">
        {error || 'Incident not found.'}
        <button className="back-to-map-btn" onClick={onBack} style={{ marginTop: 12 }}>
          <ArrowLeft className="w-3.5 h-3.5" /> Back
        </button>
      </div>
    );
  }

  const isCritical = incident.severity === 'CRITICAL';

  return (
    <div className="incident-detail">
      <button className="back-to-map-btn" onClick={onBack}>
        <ArrowLeft className="w-3.5 h-3.5" /> Back to Incidents
      </button>

      {/* Phase 40: Incident Summary */}
      <div className="section-card incident-detail-summary">
        <div className="incident-detail-summary-top">
          <div>
            <span className="metric-title">INCIDENT</span>
            <div className="incident-detail-id">{incident.incident_id}</div>
          </div>
          <span className={`anomaly-severity-pill ${isCritical ? 'critical' : 'warning'}`}>{incident.severity}</span>
        </div>
        <div className="incident-detail-title">{incident.parameter} anomaly</div>
        <div className="anomaly-card-location">
          {incident.station_name} · {incident.town}
          <button className="incident-view-station-link" onClick={() => onViewStation(incident.station_id)}>
            {incident.station_id} <ExternalLink className="w-3 h-3" />
          </button>
        </div>
        <div className="incident-detail-meta-row">
          <div><span className="metric-title">DETECTED</span><div className="metric-val">{new Date(incident.detected_at).toLocaleString()}</div></div>
          <div><span className="metric-title">FIRST SEEN</span><div className="metric-val">{new Date(incident.first_seen_at).toLocaleString()}</div></div>
          <div><span className="metric-title">LAST SEEN</span><div className="metric-val">{new Date(incident.last_seen_at).toLocaleString()}</div></div>
          <div><span className="metric-title">STATUS</span><div className="metric-val"><span className={`incident-state-pill ${incident.status}`}>{incident.status}</span></div></div>
          <div><span className="metric-title">CONFIDENCE</span><div className="metric-val">{Math.round((incident.confidence || 0) * 100)}%</div></div>
        </div>
      </div>

      {/* Phase 41: Evidence / Observation */}
      <div className="section-card">
        <div className="card-header-flex"><span className="card-section-title">OBSERVATION</span></div>
        <div className="anomaly-metrics-grid">
          <div className="anomaly-metric-box"><span className="anomaly-box-lbl">Observed:</span><span className="anomaly-box-val alert">{incident.observed_value} {incident.unit}</span></div>
          <div className="anomaly-metric-box"><span className="anomaly-box-lbl">Expected:</span><span className="anomaly-box-val">{incident.expected_min ?? '--'}–{incident.expected_max ?? '--'} {incident.unit}</span></div>
          <div className="anomaly-metric-box"><span className="anomaly-box-lbl">Source:</span><span className="anomaly-box-val">{incident.obs_source}</span></div>
          <div className="anomaly-metric-box"><span className="anomaly-box-lbl">Freshness:</span><span className="anomaly-box-val">{incident.freshness}</span></div>
        </div>
      </div>

      {/* Phase 41: Why ATHER flagged it */}
      {incident.diagnostic_layers && (
        <div className="section-card">
          <div className="card-header-flex"><span className="card-section-title">WHY ATHER FLAGGED IT</span></div>
          <div className="layer-cards-list">
            {LAYER_ORDER.map(({ key, label }) => {
              const layer = incident.diagnostic_layers[key];
              if (!layer) return null;
              return (
                <div key={key} className="layer-card-row">
                  <div className="layer-card-top">
                    <span className="layer-card-label">{label}</span>
                    <span className={`layer-status-pill ${layer.status}`}>{layer.status}</span>
                  </div>
                  {layer.reason && <div className="layer-card-reason">{layer.reason}</div>}
                </div>
              );
            })}
          </div>
          {incident.evidence?.length > 0 && (
            <ul className="why-flagged-list" style={{ marginTop: 8 }}>
              {incident.evidence.map((e: string, i: number) => <li key={i} className="why-flagged-item"><span>{e}</span></li>)}
            </ul>
          )}
        </div>
      )}

      {/* Root Cause + Recommended Action (Phase 42) */}
      <div className="section-card">
        <div className="card-header-flex"><span className="card-section-title">ROOT CAUSE</span></div>
        <div className="test-lab-root-cause-title">{String(incident.root_cause || '').replace(/_/g, ' ')}</div>
        <div className="action-header" style={{ marginTop: 10 }}><span>RECOMMENDED ACTION</span></div>
        <p className="action-text">{incident.recommended_action}</p>
      </div>

      {/* Phase 14: Timeline */}
      <div className="section-card">
        <div className="card-header-flex"><span className="card-section-title">INCIDENT TIMELINE</span></div>
        <div className="incident-timeline">
          {incident.timeline?.map((ev: any, i: number) => (
            <div key={i} className="incident-timeline-row">
              <span className="incident-timeline-time">{new Date(ev.at).toLocaleString()}</span>
              <span className="incident-timeline-event">{ev.event.replace(/_/g, ' ')}{ev.actor ? ` · ${ev.actor}` : ''}</span>
            </div>
          ))}
        </div>
      </div>

      {error && <div className="test-lab-error">{error}</div>}

      {/* Operations */}
      {incident.status !== 'RESOLVED' && incident.status !== 'DISMISSED' && (
        <div className="section-card">
          <div className="card-header-flex"><span className="card-section-title">OPERATIONS</span></div>
          <div className="incident-actions-row">
            <button className="incident-action-btn" disabled={isBusy || !allowedNext('ACKNOWLEDGED')}
              onClick={() => runAction(() => acknowledgeIncident(incident.incident_id))}>
              <UserCheck className="w-3 h-3" /> ACKNOWLEDGE
            </button>
            <button className="incident-action-btn" disabled={isBusy || !allowedNext('INVESTIGATING')}
              onClick={() => runAction(() => investigateIncident(incident.incident_id))}>
              <InvestigateIcon className="w-3 h-3" /> INVESTIGATE
            </button>
            <button className="incident-action-btn escalate" disabled={isBusy || !allowedNext('ESCALATED')}
              onClick={() => setShowEscalation(true)}>
              <Siren className="w-3 h-3" /> ESCALATE
            </button>
            <button className="incident-action-btn resolve" disabled={isBusy || !allowedNext('RESOLVED')}
              onClick={() => setShowResolve(true)}>
              RESOLVE
            </button>
            <button className="incident-action-btn" disabled={isBusy || !allowedNext('DISMISSED')}
              onClick={() => setShowDismiss(true)}>
              <XCircle className="w-3 h-3" /> DISMISS
            </button>
          </div>
        </div>
      )}

      {showEscalation && (
        <EscalationPreviewModal incidentId={incident.incident_id} onClose={() => setShowEscalation(false)} onEscalated={load} />
      )}
      {showResolve && (
        <ResolveIncidentModal
          incidentId={incident.incident_id}
          onClose={() => setShowResolve(false)}
          onResolve={async (notes, type) => { await runAction(() => resolveIncident(incident.incident_id, notes, type)); }}
        />
      )}
      {showDismiss && (
        <DismissIncidentModal
          incidentId={incident.incident_id}
          onClose={() => setShowDismiss(false)}
          onDismiss={async (reason) => { await runAction(() => dismissIncident(incident.incident_id, reason)); }}
        />
      )}
    </div>
  );
};
