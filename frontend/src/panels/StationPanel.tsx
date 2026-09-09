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
        <div className="header-meta">
          <div className="station-badge-row">
            <span className="station-panel-tag">ATHER STATION</span>
            <span className="station-coords">
              {currentStation.latitude.toFixed(2)}°, {currentStation.longitude.toFixed(2)}°
            </span>
          </div>
          <h2 className="station-id-heading">{currentStation.id}</h2>
          <div className="station-location-text">
            <span>{currentStation.name}</span>
            <span className="station-town-dot">·</span>
            <span>{currentStation.town}</span>
          </div>
        </div>
        <button className="btn-close-panel" onClick={onClose} title="Close Station Panel">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="station-panel-body">
        {/* Anomaly Diagnostic Card */}
        {anomaly && (
          <div className="anomaly-strip-card">
            <div className="anomaly-strip-header">
              <span className="anomaly-strip-title">
                <AlertOctagon className="w-3.5 h-3.5 text-red-400" />
                <span>ANOMALY DIAGNOSTIC</span>
              </span>
              <span className="anomaly-strip-severity">{anomaly.severity || 'HIGH'} SEVERITY</span>
            </div>

            <div className="anomaly-strip-grid">
              <div className="strip-grid-col">
                <span className="col-lbl">PARAMETER</span>
                <span className="col-val">{anomaly.parameter}</span>
              </div>
              <div className="strip-grid-col">
                <span className="col-lbl">OBSERVED</span>
                <span className="col-val alert">{anomaly.observed} {anomaly.unit}</span>
              </div>
              <div className="strip-grid-col">
                <span className="col-lbl">EXPECTED</span>
                <span className="col-val">{anomaly.expectedMin}–{anomaly.expectedMax} {anomaly.unit}</span>
              </div>
              <div className="strip-grid-col">
                <span className="col-lbl">DEVIATION</span>
                <span className="col-val alert">
                  {anomaly.observed > anomaly.expectedMax
                    ? `+${(anomaly.observed - anomaly.expectedMax).toFixed(1)}`
                    : `-${(anomaly.expectedMin - anomaly.observed).toFixed(1)}`} {anomaly.unit}
                </span>
              </div>
            </div>

            {anomaly.reason && (
              <div className="anomaly-reason-line">
                <span>{anomaly.reason}</span>
              </div>
            )}
          </div>
        )}

        {/* Current Weather Section Heading */}
        <div className="weather-section-title-row">
          <div className="weather-section-title">
            <CloudSun className="w-3.5 h-3.5 text-cyan-400" />
            <span>CURRENT WEATHER</span>
          </div>
        </div>

        {/* Loading / Error States (Subtle, non-intrusive) */}
        {isLoadingWeather && (
          <div className="weather-status-subtle loading">
            <span className="subtle-dot-pulse" />
            <span>Updating weather...</span>
          </div>
        )}

        {weatherError && (
          <div className="weather-status-subtle error">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
            <span>Current weather unavailable</span>
          </div>
        )}

        {/* Weather Values - 2x2 Grid with Clean Spacing */}
        <div className="weather-elegant-grid">
          <div className="weather-grid-row">
            <div className="weather-metric-col">
              <div className="weather-metric-val">
                {displayTemp !== null && displayTemp !== undefined ? `${displayTemp}°C` : '--'}
              </div>
              <div className="weather-metric-lbl">Temperature</div>
            </div>
            <div className="weather-metric-col">
              <div className="weather-metric-val">
                {displayHumidity !== null && displayHumidity !== undefined ? `${Math.round(displayHumidity)}%` : '--'}
              </div>
              <div className="weather-metric-lbl">Humidity</div>
            </div>
          </div>

          <div className="weather-grid-row">
            <div className="weather-metric-col">
              <div className="weather-metric-val">
                {displayPressure !== null && displayPressure !== undefined ? `${Math.round(displayPressure)} hPa` : '--'}
              </div>
              <div className="weather-metric-lbl">Pressure</div>
            </div>
            <div className="weather-metric-col">
              <div className="weather-metric-val">
                {displayWindSpeed !== null && displayWindSpeed !== undefined ? `${displayWindSpeed} km/h` : '0 km/h'}
              </div>
              <div className="weather-metric-lbl">Wind</div>
            </div>
          </div>
        </div>

        {/* Status Strip */}
        <div className="station-status-strip">
          <div className={`status-badge-compact ${currentStation.status}`}>
            <span className="status-dot-pulse" />
            <span>● {currentStation.status}</span>
          </div>
          <div className="source-update-meta">
            <span>Source: Open-Meteo</span>
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
