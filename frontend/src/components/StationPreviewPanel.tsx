import React, { useEffect, useMemo, useState } from 'react';
import { mapStatus, useLive, formatAge } from '../services/live';
import { SourceBadge } from './live/LiveBits';
import { X, ArrowRight, Thermometer, Gauge, Droplets, ShieldAlert, CheckCircle2, AlertTriangle, Radio } from 'lucide-react';
import { Station, StationAnomalyAssessment } from '../types/weather';
import { fetchStationAnomaly } from '../services/api';

interface StationPreviewPanelProps {
  station: Station;
  onClose: () => void;
  onViewDetails: (stationId: string) => void;
}

export const StationPreviewPanel: React.FC<StationPreviewPanelProps> = ({
  station,
  onClose,
  onViewDetails,
}) => {
  const [anomalyData, setAnomalyData] = useState<StationAnomalyAssessment | null>(null);
  const [isLoadingAnomaly, setIsLoadingAnomaly] = useState<boolean>(false);

  useEffect(() => {
    let isMounted = true;
    if (station.id) {
      setIsLoadingAnomaly(true);
      fetchStationAnomaly(station.id)
        .then((data) => {
          if (isMounted) {
            setAnomalyData(data);
            setIsLoadingAnomaly(false);
          }
        })
        .catch(() => {
          if (isMounted) setIsLoadingAnomaly(false);
        });
    }
    return () => {
      isMounted = false;
    };
  }, [station.id]);

  // Live pipeline state wins; otherwise the (read-only) cached assessment.
  // No invented fallback numbers: missing values render as "—".
  const { stations: liveStations, stationsVersion } = useLive();
  const live = useMemo(() => liveStations.get(station.id), [liveStations, stationsVersion, station.id]);

  const liveStatus = live ? mapStatus(live.overall_status) : null;
  const statusLabel = liveStatus || (anomalyData?.status as string) || station.status || 'NORMAL';
  const isAnomaly = statusLabel === 'ANOMALY';
  const isWarning = statusLabel === 'WARNING';

  const severity = live?.severity || anomalyData?.overall?.severity || station.anomaly?.severity || 'NONE';
  const anomalyScore: number | null = anomalyData?.overall?.score ?? anomalyData?.anomaly_score ?? null;
  const confidence: number | null = live?.confidence ?? anomalyData?.overall?.confidence ?? anomalyData?.confidence ?? null;
  const confidencePct = confidence == null ? '—' : Math.round(confidence * 100);

  const reason =
    live?.summary ||
    anomalyData?.explanation ||
    station.anomaly?.reason ||
    (isLoadingAnomaly ? 'Loading diagnosis…' : 'No diagnosis available for this station.');

  const values = live?.values;
  const temperature = values ? values.temperature : station.temperature;
  const pressure = values ? values.pressure : station.pressure;
  const humidity = values ? values.humidity : station.humidity;

  const locationStr = [station.town, station.region, station.country]
    .filter(Boolean)
    .join(', ') || 'AWS Station Site';

  return (
    <div className="station-preview-panel" role="region" aria-label={`Preview for ${station.id}`}>
      {/* Header */}
      <div className="preview-header">
        <div className="preview-title-group">
          <div className="preview-id-badge">
            <Radio className="w-3.5 h-3.5 text-blue-600" />
            <span className="preview-station-id">{station.id}</span>
          </div>
          <h3 className="preview-station-name">{station.name}</h3>
          <p className="preview-station-loc">{locationStr}</p>
          <div className="lv-row" style={{ marginTop: 4 }}>
            <SourceBadge source={live?.source || (anomalyData?.observation?.source as string)} simulated={live?.simulated} />
            {live?.last_observed_at && <span className="lv-muted">observed {formatAge(live.last_observed_at)}</span>}
          </div>
        </div>
        <button
          className="preview-close-btn"
          onClick={onClose}
          aria-label="Close station preview"
          title="Close preview"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Status & Severity Banner */}
      <div className={`preview-status-banner ${statusLabel.toLowerCase()}`}>
        <div className="status-badge-left">
          {isAnomaly ? (
            <ShieldAlert className="w-4 h-4 text-red-600" />
          ) : isWarning ? (
            <AlertTriangle className="w-4 h-4 text-amber-600" />
          ) : (
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
          )}
          <span className="status-badge-text">● {statusLabel}</span>
        </div>
        {severity !== 'NONE' && (
          <span className={`severity-tag ${severity.toLowerCase()}`}>
            {severity} SEVERITY
          </span>
        )}
      </div>

      {/* Weather Parameters Grid */}
      <div className="preview-metrics-grid">
        <div className="preview-metric-card">
          <div className="metric-header">
            <Thermometer className="w-3.5 h-3.5 text-orange-500" />
            <span>Temperature</span>
          </div>
          <div className="metric-value">
            {temperature != null ? `${Number(temperature).toFixed(1)} °C` : '—'}
          </div>
        </div>

        <div className="preview-metric-card">
          <div className="metric-header">
            <Gauge className="w-3.5 h-3.5 text-blue-500" />
            <span>Pressure</span>
          </div>
          <div className="metric-value">
            {pressure != null ? `${Number(pressure).toFixed(1)} hPa` : '—'}
          </div>
        </div>

        <div className="preview-metric-card">
          <div className="metric-header">
            <Droplets className="w-3.5 h-3.5 text-teal-500" />
            <span>Humidity</span>
          </div>
          <div className="metric-value">
            {humidity != null ? `${Number(humidity).toFixed(1)} %` : '—'}
          </div>
        </div>
      </div>

      {/* ATHER Intelligence Metrics */}
      <div className="preview-intelligence-card">
        <div className="intelligence-row">
          <div className="intelligence-col">
            <span className="intel-label">Anomaly Score</span>
            <span className={`intel-val ${anomalyScore == null ? 'normal' : anomalyScore >= 0.7 ? 'critical' : anomalyScore >= 0.4 ? 'warning' : 'normal'}`}>
              {anomalyScore == null ? '—' : anomalyScore.toFixed(2)}
            </span>
          </div>
          <div className="intelligence-divider" />
          <div className="intelligence-col">
            <span className="intel-label">Confidence</span>
            <span className="intel-val normal">{confidencePct}{confidence == null ? '' : '%'}</span>
          </div>
          <div className="intelligence-divider" />
          <div className="intelligence-col">
            <span className="intel-label">Coordinates</span>
            <span className="intel-val-sub">
              {station.latitude?.toFixed(2)}°, {station.longitude?.toFixed(2)}°
            </span>
          </div>
        </div>

        {/* Why / Explanation section */}
        <div className="preview-why-section">
          <span className="why-title">Why?</span>
          <p className="why-text">{reason}</p>
        </div>
      </div>

      {/* Actions */}
      <div className="preview-actions-bar">
        <button
          className="preview-view-details-btn"
          onClick={() => onViewDetails(station.id)}
        >
          <span>VIEW DETAILS</span>
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
