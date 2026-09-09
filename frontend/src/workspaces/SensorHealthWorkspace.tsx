import React, { useMemo } from 'react';
import { HeartPulse, Wifi, Radio, AlertTriangle, ChevronRight, Info } from 'lucide-react';
import { AnomaliesSummary } from '../types/weather';

interface SensorHealthWorkspaceProps {
  summary: AnomaliesSummary | null;
  onViewStation: (stationId: string) => void;
}

/**
 * ATHER SENSOR HEALTH — dedicated monitoring workspace (UI architecture
 * restructure, Phase 15). Reuses the SAME summary counts the rest of the
 * app already fetches (single source of truth, Phase 31) — it does not
 * recompute network health independently. Per-station health-index detail
 * is intentionally NOT fabricated here; it lives in Station Intelligence
 * (L5 Sensor Health card), which is one click away via VIEW.
 */
export const SensorHealthWorkspace: React.FC<SensorHealthWorkspaceProps> = ({ summary, onViewStation }) => {
  const total = summary?.totalStations ?? 0;
  const normal = summary?.normalCount ?? 0;
  const warning = summary?.warningCount ?? 0;
  const anomaly = summary?.anomalyCount ?? 0;
  const offline = summary?.offlineCount ?? 0;

  const coverage = total > 0 ? (((total - offline) / total) * 100).toFixed(1) : null;
  const degradedStations = summary?.activeWarnings ?? [];

  const distribution = useMemo(() => [
    { label: 'Normal', value: normal, cls: 'normal' },
    { label: 'Warning', value: warning, cls: 'warning' },
    { label: 'Anomaly', value: anomaly, cls: 'anomaly' },
    { label: 'Offline', value: offline, cls: 'offline' },
  ], [normal, warning, anomaly, offline]);

  return (
    <div className="sensor-health-workspace">
      <div className="workspace-page-header">
        <div className="workspace-page-title-group">
          <HeartPulse className="w-5 h-5 text-amber-400" />
          <div>
            <div className="workspace-page-title">SENSOR HEALTH</div>
            <div className="workspace-page-subtitle">How healthy is the AWS network right now?</div>
          </div>
        </div>
      </div>

      <div className="health-summary-grid">
        <div className="health-summary-card">
          <span className="metric-title">TELEMETRY COVERAGE</span>
          <div className="health-summary-value">{coverage !== null ? `${coverage}%` : 'DATA UNAVAILABLE'}</div>
          <div className="health-summary-note"><Wifi className="w-3 h-3" /> {total - offline} of {total} stations reporting</div>
        </div>
        <div className="health-summary-card">
          <span className="metric-title">OFFLINE STATIONS</span>
          <div className="health-summary-value">{offline}</div>
          <div className="health-summary-note"><Radio className="w-3 h-3" /> No telemetry within the freshness window</div>
        </div>
        <div className="health-summary-card">
          <span className="metric-title">DEGRADED / WARNING</span>
          <div className="health-summary-value">{warning}</div>
          <div className="health-summary-note"><AlertTriangle className="w-3 h-3" /> Sensor health or data-quality concern flagged</div>
        </div>
      </div>

      <div className="section-card">
        <div className="card-header-flex"><span className="card-section-title">SENSOR HEALTH DISTRIBUTION</span></div>
        <div className="station-distribution-container">
          <div className="distribution-bar">
            {distribution.map((d) => (
              <div key={d.label} className={`dist-segment ${d.cls}`} style={{ width: `${total ? (d.value / total) * 100 : 0}%` }} title={`${d.label}: ${d.value}`} />
            ))}
          </div>
          <div className="distribution-legend">
            {distribution.map((d) => (
              <span key={d.label}><i className={`dist-dot ${d.cls === 'normal' ? 'green' : d.cls === 'warning' ? 'amber' : d.cls === 'anomaly' ? 'red' : 'slate'}`} /> {d.value} {d.label}</span>
            ))}
          </div>
        </div>
        <div className="health-detail-note">
          Detailed per-station L5 sensor-health score, drift tier, and days-to-failure projection are available on each station's Station Intelligence page.
        </div>
      </div>

      <div className="section-card">
        <div className="card-header-flex"><span className="card-section-title">STATIONS WITH DEGRADATION</span></div>
        <div className="anomalies-list">
          {degradedStations.length === 0 ? (
            <div className="anomalies-empty-state">
              <Info className="w-4 h-4 text-slate-400" />
              <span>No stations currently flagged with a sensor-health warning.</span>
            </div>
          ) : (
            degradedStations.map((stn) => (
              <div key={stn.id} className="anomaly-card warning">
                <div className="anomaly-card-severity-bar" />
                <div className="anomaly-card-body">
                  <div className="anomaly-card-top">
                    <span className="anomaly-severity-pill warning">WARNING</span>
                    <span className="anomaly-card-station-id">{stn.id}</span>
                  </div>
                  <div className="anomaly-card-title">{stn.anomaly?.parameter || 'Sensor'} degradation</div>
                  <div className="anomaly-card-location">{stn.name} · {stn.town}</div>
                </div>
                <button className="anomaly-card-view-btn" onClick={() => onViewStation(stn.id)}>
                  VIEW <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
