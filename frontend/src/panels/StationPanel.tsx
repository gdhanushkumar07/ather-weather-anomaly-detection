import React, { useEffect, useState } from 'react';
import { X, AlertOctagon, TrendingUp, Compass, Clock, MapPin } from 'lucide-react';
import { Station, ObservationHistory } from '../types/weather';
import { fetchStationObservations } from '../services/api';

interface StationPanelProps {
  station: Station | null;
  onClose: () => void;
}

export const StationPanel: React.FC<StationPanelProps> = ({ station, onClose }) => {
  const [history, setHistory] = useState<ObservationHistory | null>(null);
  const [cachedStation, setCachedStation] = useState<Station | null>(station);

  useEffect(() => {
    if (station) {
      setCachedStation(station);
      fetchStationObservations(station.id)
        .then(setHistory)
        .catch((err) => console.error('Failed to load observations history', err));
    }
  }, [station?.id]);

  const displayStation = station || cachedStation;
  if (!displayStation) return null;

  const currentStation = displayStation;
  const anomaly = currentStation.anomaly;
  const isAnomaly = currentStation.status === 'ANOMALY' || !!anomaly;
  const isWarning = currentStation.status === 'WARNING';

  // SVG Sparkline calculation for temperature
  const temps = history?.series.map((s) => s.temperature) || [];
  const minTemp = temps.length ? Math.min(...temps) : 20;
  const maxTemp = temps.length ? Math.max(...temps) : 35;
  const tempRange = maxTemp - minTemp || 1;

  const points = temps
    .map((t, idx) => {
      const x = (idx / (temps.length - 1 || 1)) * 320;
      const y = 55 - ((t - minTemp) / tempRange) * 45;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <div className={`station-panel-wrapper ${station ? 'expanded' : 'collapsed'}`}>
      {/* Header */}
      <div className="station-panel-header">
        <div>
          <span className="station-id-tag">{currentStation.id}</span>
          <h2 className="station-title">{currentStation.name}</h2>
          <div className="station-location" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <MapPin className="w-3.5 h-3.5 text-slate-400" />
            <span>{currentStation.town}</span>
          </div>
        </div>
        <button className="btn-close" onClick={onClose} title="Close Panel">
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="station-panel-body">
        {/* Overall Status Badge */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div className={`status-badge ${currentStation.status}`}>
            <span className="status-dot" />
            <span>{currentStation.status}</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: '0.75rem', color: '#64748b' }}>
            <Clock className="w-3.5 h-3.5" />
            <span>Last Updated: {currentStation.timestamp || 'Just now'}</span>
          </div>
        </div>

        {/* Anomaly Highlight Card */}
        {anomaly && (
          <div className={`anomaly-card ${anomaly.severity || 'HIGH'}`}>
            <div className="anomaly-card-header">
              <div className="anomaly-title">
                <AlertOctagon className="w-4 h-4" />
                <span>Anomaly Detected</span>
              </div>
              <span
                style={{
                  fontSize: '0.7rem',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  padding: '2px 6px',
                  borderRadius: 4,
                  background: anomaly.severity === 'HIGH' ? '#fecaca' : '#fde68a',
                  color: anomaly.severity === 'HIGH' ? '#991b1b' : '#92400e'
                }}
              >
                {anomaly.severity} SEVERITY
              </span>
            </div>

            <div className="anomaly-meta-grid">
              <div className="anomaly-meta-item">
                <label>Parameter</label>
                <span>{anomaly.parameter}</span>
              </div>
              <div className="anomaly-meta-item">
                <label>Observed</label>
                <span style={{ color: '#ef4444' }}>
                  {anomaly.observed} {anomaly.unit}
                </span>
              </div>
              <div className="anomaly-meta-item">
                <label>Expected Range</label>
                <span>
                  {anomaly.expectedMin} – {anomaly.expectedMax} {anomaly.unit}
                </span>
              </div>
              <div className="anomaly-meta-item">
                <label>Deviation</label>
                <span>
                  {anomaly.observed > anomaly.expectedMax
                    ? `+${(anomaly.observed - anomaly.expectedMax).toFixed(1)} ${anomaly.unit}`
                    : `-${(anomaly.expectedMin - anomaly.observed).toFixed(1)} ${anomaly.unit}`}
                </span>
              </div>
            </div>

            <div className="anomaly-reason">
              <strong>Diagnostic:</strong> {anomaly.reason}
            </div>
          </div>
        )}

        {/* Primary Observation Telemetry Grid */}
        <div className="telemetry-grid">
          <div className="telemetry-card">
            <div className="label">Temperature</div>
            <div className="value">
              {currentStation.temperature !== null && currentStation.temperature !== undefined ? (
                <>
                  {currentStation.temperature}
                  <span className="unit">°C</span>
                </>
              ) : (
                '--'
              )}
            </div>
          </div>

          <div className="telemetry-card">
            <div className="label">Barometric Pressure</div>
            <div className="value">
              {currentStation.pressure !== null && currentStation.pressure !== undefined ? (
                <>
                  {currentStation.pressure}
                  <span className="unit">hPa</span>
                </>
              ) : (
                '--'
              )}
            </div>
          </div>

          <div className="telemetry-card">
            <div className="label">Relative Humidity</div>
            <div className="value">
              {currentStation.humidity !== null && currentStation.humidity !== undefined ? (
                <>
                  {currentStation.humidity}
                  <span className="unit">%</span>
                </>
              ) : (
                '--'
              )}
            </div>
          </div>

          <div className="telemetry-card">
            <div className="label">Wind Velocity</div>
            <div className="value">
              {currentStation.windSpeed !== null && currentStation.windSpeed !== undefined ? (
                <>
                  {currentStation.windSpeed}
                  <span className="unit">km/h</span>
                </>
              ) : (
                '0.0'
              )}
            </div>
            {currentStation.windDirection && (
              <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: 2, display: 'flex', alignItems: 'center', gap: 3 }}>
                <Compass className="w-3 h-3" />
                <span>Dir: {currentStation.windDirection}</span>
              </div>
            )}
          </div>
        </div>

        {/* 24-Hour Diurnal Trend Sparkline */}
        {history && history.series.length > 0 && (
          <div className="trend-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <div className="trend-title" style={{ display: 'flex', alignItems: 'center', gap: 4, margin: 0 }}>
                <TrendingUp className="w-3.5 h-3.5 text-sky-600" />
                <span>24-Hour Thermal Trend</span>
              </div>
              <div style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: '#64748b' }}>
                Low: {minTemp}°C · High: {maxTemp}°C
              </div>
            </div>

            <svg className="sparkline-svg" viewBox="0 0 320 60">
              <polyline
                fill="none"
                stroke="#0284c7"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                points={points}
              />
              {/* Highlight anomalous endpoint */}
              {isAnomaly && (
                <circle
                  cx="320"
                  cy={55 - ((temps[temps.length - 1] - minTemp) / tempRange) * 45}
                  r="4"
                  fill="#ef4444"
                  stroke="#ffffff"
                  strokeWidth="2"
                />
              )}
            </svg>

            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: '#94a3b8', marginTop: 4 }}>
              <span>24h ago</span>
              <span>12h ago</span>
              <span>Now</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
