import React from 'react';
import { ChevronRight } from 'lucide-react';

interface AnomalyCardMetric {
  label: string;
  value: React.ReactNode;
}

interface AnomalyCardProps {
  /** 'critical' | 'warning' | 'neutral' — drives the accent bar + pill color only. */
  accent: 'critical' | 'warning' | 'neutral';
  pillLabel: string;
  stationId: string;
  title: string;
  location: string;
  metrics: AnomalyCardMetric[];
  onView: () => void;
}

/**
 * Single, compact, single-row anomaly/incident/degradation card shared by the
 * Anomalies and Sensor Health workspaces (UI polish pass). Severity is a
 * small accent bar + pill, never the whole card. Identity (station + title +
 * location) sits in one column; metrics form their own aligned columns;
 * the view action is a plain right-aligned link, not a button.
 */
export const AnomalyCard: React.FC<AnomalyCardProps> = ({
  accent, pillLabel, stationId, title, location, metrics, onView
}) => {
  return (
    <div className={`anomaly-card ${accent}`}>
      <div className="anomaly-card-accent" />
      <div className="anomaly-card-identity">
        <div className="anomaly-card-identity-top">
          <span className={`anomaly-severity-pill ${accent}`}>{pillLabel}</span>
          <span className="anomaly-card-station-id">{stationId}</span>
        </div>
        <div className="anomaly-card-title">{title}</div>
        <div className="anomaly-card-location">{location}</div>
      </div>

      {metrics.map((m, i) => (
        <div className="anomaly-metric-col" key={i}>
          <span className="metric-title">{m.label}</span>
          <span className="metric-val">{m.value}</span>
        </div>
      ))}

      <button className="anomaly-card-view-btn" onClick={onView}>
        View details <ChevronRight className="w-3.5 h-3.5" />
      </button>
    </div>
  );
};
