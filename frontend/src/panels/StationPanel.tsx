import React, { useEffect, useState } from 'react';
import { X, AlertOctagon, TrendingUp, Compass, Clock, MapPin, Loader2, CloudSun, AlertTriangle } from 'lucide-react';
import { Station, ObservationHistory, OpenMeteoWeather } from '../types/weather';
import { fetchStationObservations, fetchCurrentWeather } from '../services/api';

interface StationPanelProps {
  station: Station | null;
  onClose: () => void;
}

export const StationPanel: React.FC<StationPanelProps> = ({ station, onClose }) => {
  const [history, setHistory] = useState<ObservationHistory | null>(null);
  const [cachedStation, setCachedStation] = useState<Station | null>(station);

  const [currentWeather, setCurrentWeather] = useState<OpenMeteoWeather | null>(null);
  const [isLoadingWeather, setIsLoadingWeather] = useState<boolean>(false);
  const [weatherError, setWeatherError] = useState<string | null>(null);

  useEffect(() => {
    if (station) {
      setCachedStation(station);
      setWeatherError(null);
      setIsLoadingWeather(true);

      // Fetch live current weather from Open-Meteo proxy for exact coordinates
      fetchCurrentWeather(station.latitude, station.longitude)
        .then((weather) => {
          setCurrentWeather(weather);
          setIsLoadingWeather(false);
        })
        .catch((err) => {
          console.error('Failed to load Open-Meteo weather', err);
          setWeatherError('Weather data temporarily unavailable.');
          setIsLoadingWeather(false);
        });

      // Fetch 24-hour diurnal trend
      fetchStationObservations(station.id)
        .then(setHistory)
        .catch((err) => console.error('Failed to load observations history', err));
    }
  }, [station?.id, station?.latitude, station?.longitude]);

  const displayStation = station || cachedStation;
  if (!displayStation) return null;

  const currentStation = displayStation;
  const anomaly = currentStation.anomaly;
  const isAnomaly = currentStation.status === 'ANOMALY' || !!anomaly;

  const displayTemp = currentWeather ? currentWeather.temperature : currentStation.temperature;
  const displayHumidity = currentWeather ? currentWeather.humidity : currentStation.humidity;
  const displayPressure = currentWeather ? currentWeather.pressure : currentStation.pressure;
  const displayWindSpeed = currentWeather ? currentWeather.windSpeed : currentStation.windSpeed;
  const displayWindDir = currentWeather ? currentWeather.windDirection : currentStation.windDirection;
  const displayCondition = currentWeather ? currentWeather.condition : currentStation.condition;

  // SVG Sparkline calculation
  const temps = history?.series.map((s) => s.temperature) || [];
  const minTemp = temps.length ? Math.min(...temps) : 20;
  const maxTemp = temps.length ? Math.max(...temps) : 35;
  const tempRange = maxTemp - minTemp || 1;

  const points = temps
    .map((t, idx) => {
      const x = (idx / (temps.length - 1 || 1)) * 320;
      const y = 52 - ((t - minTemp) / tempRange) * 42;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <div className={`station-panel-wrapper ${station ? 'expanded' : 'collapsed'}`}>
      {/* Header */}
      <div className="station-panel-header">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <span className="station-id-tag">{currentStation.id}</span>
            <span style={{ fontSize: '0.72rem', color: '#64748b', fontFamily: 'var(--font-mono)' }}>
              {currentStation.latitude.toFixed(2)}°, {currentStation.longitude.toFixed(2)}°
            </span>
          </div>
          <h2 className="station-title">{currentStation.name}</h2>
          <div className="station-location">
            <MapPin className="w-3.5 h-3.5 text-slate-400" />
            <span>{currentStation.town}</span>
          </div>
        </div>
        <button className="btn-close" onClick={onClose} title="Close Station Panel">
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="station-panel-body">
        {/* Status Indicator & Updated Time */}
        <div className="station-status-row">
          <div className={`status-badge ${currentStation.status}`}>
            <span className="status-dot" />
            <span>{currentStation.status}</span>
          </div>

          <div className="station-timestamp-meta">
            <Clock className="w-3.5 h-3.5 text-slate-400" />
            <span>
              {currentWeather ? `Updated: ${currentWeather.timestamp.split('T')[1] || 'Just now'}` : currentStation.timestamp}
            </span>
          </div>
        </div>

        {/* Anomaly Diagnostic Card */}
        {anomaly && (
          <div className={`anomaly-card ${anomaly.severity || 'HIGH'}`}>
            <div className="anomaly-card-header">
              <div className="anomaly-title">
                <AlertOctagon className="w-4 h-4" />
                <span>Anomaly Detected</span>
              </div>
              <span className={`anomaly-severity-pill ${anomaly.severity || 'HIGH'}`}>
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

        {/* Current Weather Section Header */}
        <div className="weather-section-header">
          <div className="weather-section-title">
            <CloudSun className="w-4 h-4 text-cyan-400" />
            <span>Current Weather</span>
          </div>

          <span className="source-tag">
            Source: {currentWeather ? 'Open-Meteo' : 'Station Ingest'}
          </span>
        </div>

        {/* Loading / Error States */}
        {isLoadingWeather && (
          <div className="weather-loading-state">
            <Loader2 className="w-4 h-4 animate-spin text-cyan-400" />
            <span>Loading live conditions from Open-Meteo...</span>
          </div>
        )}

        {weatherError && (
          <div className="weather-error-state">
            <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400" />
            <span>{weatherError}</span>
          </div>
        )}

        {/* Telemetry 2x2 Grid */}
        <div className="telemetry-grid">
          <div className="telemetry-card">
            <div className="label">Temperature</div>
            <div className="value">
              {displayTemp !== null && displayTemp !== undefined ? (
                <>
                  {displayTemp}
                  <span className="unit">°C</span>
                </>
              ) : (
                '--'
              )}
            </div>
            <div className="sub-meta">
              {currentWeather?.apparentTemperature !== undefined
                ? `Feels like: ${currentWeather.apparentTemperature} °C`
                : 'Observed'}
            </div>
          </div>

          <div className="telemetry-card">
            <div className="label">Barometric Pressure</div>
            <div className="value">
              {displayPressure !== null && displayPressure !== undefined ? (
                <>
                  {Math.round(displayPressure)}
                  <span className="unit">hPa</span>
                </>
              ) : (
                '--'
              )}
            </div>
            <div className="sub-meta">
              {displayCondition ? `Sky: ${displayCondition}` : 'Atmospheric'}
            </div>
          </div>

          <div className="telemetry-card">
            <div className="label">Relative Humidity</div>
            <div className="value">
              {displayHumidity !== null && displayHumidity !== undefined ? (
                <>
                  {Math.round(displayHumidity)}
                  <span className="unit">%</span>
                </>
              ) : (
                '--'
              )}
            </div>
            <div className="sub-meta">
              {currentWeather?.precipitation !== undefined
                ? `Precip: ${currentWeather.precipitation} mm`
                : 'Moisture'}
            </div>
          </div>

          <div className="telemetry-card">
            <div className="label">Wind Velocity</div>
            <div className="value">
              {displayWindSpeed !== null && displayWindSpeed !== undefined ? (
                <>
                  {displayWindSpeed}
                  <span className="unit">km/h</span>
                </>
              ) : (
                '0.0'
              )}
            </div>
            <div className="sub-meta">
              <Compass className="w-3 h-3 text-slate-400" />
              <span>{displayWindDir ? `Direction: ${displayWindDir}` : 'Calm'}</span>
            </div>
          </div>
        </div>

        {/* 24-Hour Diurnal Trend Sparkline */}
        {history && history.series.length > 0 && (
          <div className="trend-section">
            <div className="trend-header">
              <div className="trend-title">
                <TrendingUp className="w-3.5 h-3.5 text-cyan-400" />
                <span>24-Hour Thermal Trend</span>
              </div>
              <div className="trend-minmax">
                Low: {minTemp}°C · High: {maxTemp}°C
              </div>
            </div>

            <svg className="sparkline-svg" viewBox="0 0 320 56">
              <defs>
                <linearGradient id="trendGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#00e5ff" stopOpacity="0.4" />
                  <stop offset="100%" stopColor="#0284c7" stopOpacity="0.0" />
                </linearGradient>
              </defs>
              <polyline
                fill="none"
                stroke="#00e5ff"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                points={points}
              />
              {isAnomaly && (
                <circle
                  cx="320"
                  cy={52 - ((temps[temps.length - 1] - minTemp) / tempRange) * 42}
                  r="4.5"
                  fill="#ef4444"
                  stroke="#ffffff"
                  strokeWidth="2"
                />
              )}
            </svg>

            <div className="trend-timestamps">
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
